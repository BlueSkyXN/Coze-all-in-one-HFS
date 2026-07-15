#!/usr/bin/env python3
"""Default-off admin service for the Coze HFS container."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
from collections import defaultdict, deque
from dataclasses import dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any


STARTED_AT = time.time()
HOST = os.environ.get("ADMIN_HOST", "127.0.0.1")
PORT = int(os.environ.get("ADMIN_PORT", "8082"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data/coze"))
SUPERVISOR_CONFIG = os.environ.get("SUPERVISOR_CONFIG", "/opt/coze-hfs/conf/supervisord.conf")
HEALTHCHECK = os.environ.get("COZE_HFS_HEALTHCHECK", "/opt/coze-hfs/bin/healthcheck.sh")
SESSION_COOKIE = "coze_admin_session"
MAX_JSON_BYTES = 1024 * 1024
MAX_AUDIT_EVENTS = 500
LOGIN_FAILURES_BY_IP: dict[str, deque[float]] = defaultdict(deque)
LOGIN_FAILURES_GLOBAL: deque[float] = deque()
LOGIN_RATE_LOCK = Lock()
ACTION_LOCK = Lock()

ALLOWED_RESTART_SERVICES = [
    "mariadb",
    "redis",
    "nats",
    "minio",
    "minio-init",
    "etcd",
    "elasticsearch",
    "milvus",
    "coze-server",
    "ops-service",
    "nginx",
]

SENSITIVE_DETAIL_KEYS = (
    "authorization",
    "apikey",
    "cookie",
    "credential",
    "privatekey",
    "secret",
    "token",
    "password",
)


@dataclass
class AuthContext:
    kind: str
    csrf_token: str
    expires_at: int | None = None
    nonce: str = ""


class AdminError(Exception):
    def __init__(self, status: int, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def parse_bool(value: str, default: bool = False) -> bool:
    if value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_int(value: Any, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if minimum is not None:
        parsed = max(parsed, minimum)
    if maximum is not None:
        parsed = min(parsed, maximum)
    return parsed


def truncate_text(value: str, limit: int = 4096) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"


def subprocess_text(value: bytes | str | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def admin_enabled() -> bool:
    return parse_bool(env("ADMIN_ENABLED", "false"), default=False)


def admin_token() -> str:
    return env("ADMIN_TOKEN")


def admin_available() -> tuple[bool, str]:
    if not admin_enabled():
        return False, "admin is disabled"
    token = admin_token()
    if not token:
        return False, "ADMIN_TOKEN is required when ADMIN_ENABLED=true"
    if len(token) < 24:
        return False, "ADMIN_TOKEN must contain at least 24 characters"
    if env("OPS_TOKEN") and hmac.compare_digest(token, env("OPS_TOKEN")):
        return False, "ADMIN_TOKEN must not reuse OPS_TOKEN"
    return True, ""


def admin_csrf_key() -> str:
    configured = env("ADMIN_CSRF_KEY")
    if configured:
        return configured
    secret_key = env("SECRET_KEY")
    if secret_key:
        return hmac.new(secret_key.encode("utf-8"), b"coze-hfs-admin-csrf", hashlib.sha256).hexdigest()
    return admin_token()


def session_ttl_seconds() -> int:
    return parse_int(env("ADMIN_SESSION_TTL_SECONDS"), 3600, minimum=60, maximum=86400)


def login_rate_limit_window_seconds() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_WINDOW_SECONDS"), 300, minimum=10, maximum=3600)


def login_rate_limit_block_seconds() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_BLOCK_SECONDS"), 300, minimum=10, maximum=3600)


def login_rate_limit_max_per_ip() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_MAX_PER_IP"), 5, minimum=1, maximum=1000)


def login_rate_limit_max_global() -> int:
    return parse_int(env("ADMIN_LOGIN_RATE_LIMIT_MAX_GLOBAL"), 30, minimum=1, maximum=10000)


def trusted_remote_addr(headers: Any, client_address: Any) -> str:
    real_ip = str(headers.get("X-Real-IP", "")).strip()
    if real_ip:
        return real_ip
    try:
        return str(client_address[0]) if client_address else ""
    except (IndexError, TypeError):
        return ""


def prune_failures(values: deque[float], now: float, window: int) -> None:
    while values and values[0] <= now - window:
        values.popleft()


def prune_login_failure_entries(now: float, window: int) -> None:
    for remote_addr in list(LOGIN_FAILURES_BY_IP):
        failures = LOGIN_FAILURES_BY_IP[remote_addr]
        prune_failures(failures, now, window)
        if not failures:
            LOGIN_FAILURES_BY_IP.pop(remote_addr, None)


def login_retry_after(remote_addr: str) -> int:
    now = time.time()
    window = login_rate_limit_window_seconds()
    block = login_rate_limit_block_seconds()
    with LOGIN_RATE_LOCK:
        prune_login_failure_entries(now, max(window, block))
        ip_failures = LOGIN_FAILURES_BY_IP.get(remote_addr, deque())
        prune_failures(ip_failures, now, max(window, block))
        prune_failures(LOGIN_FAILURES_GLOBAL, now, max(window, block))
        if len(ip_failures) >= login_rate_limit_max_per_ip() and now - ip_failures[-1] < block:
            return max(1, int(block - (now - ip_failures[-1])))
        if len(LOGIN_FAILURES_GLOBAL) >= login_rate_limit_max_global() and now - LOGIN_FAILURES_GLOBAL[-1] < block:
            return max(1, int(block - (now - LOGIN_FAILURES_GLOBAL[-1])))
    return 0


def record_login_failure(remote_addr: str) -> None:
    now = time.time()
    window = login_rate_limit_window_seconds()
    with LOGIN_RATE_LOCK:
        prune_login_failure_entries(now, max(window, login_rate_limit_block_seconds()))
        ip_failures = LOGIN_FAILURES_BY_IP[remote_addr]
        prune_failures(ip_failures, now, window)
        prune_failures(LOGIN_FAILURES_GLOBAL, now, window)
        ip_failures.append(now)
        LOGIN_FAILURES_GLOBAL.append(now)


def clear_login_failures(remote_addr: str) -> None:
    with LOGIN_RATE_LOCK:
        LOGIN_FAILURES_BY_IP.pop(remote_addr, None)


def sign_message(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(admin_token().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def sign_csrf_message(*parts: str) -> str:
    payload = "|".join(parts).encode("utf-8")
    return hmac.new(admin_csrf_key().encode("utf-8"), payload, hashlib.sha256).hexdigest()


def csrf_for(expires_at: int, nonce: str) -> str:
    return sign_csrf_message("csrf", str(expires_at), nonce)


def make_session() -> tuple[str, str, int]:
    expires_at = int(time.time()) + session_ttl_seconds()
    nonce = secrets.token_urlsafe(24)
    signature = sign_message("session", str(expires_at), nonce)
    return f"{expires_at}.{nonce}.{signature}", csrf_for(expires_at, nonce), expires_at


def parse_session(cookie_value: str) -> AuthContext | None:
    try:
        expires_raw, nonce, signature = cookie_value.split(".", 2)
        expires_at = int(expires_raw)
    except (ValueError, TypeError):
        return None
    if expires_at < int(time.time()):
        return None
    expected = sign_message("session", expires_raw, nonce)
    if not hmac.compare_digest(expected, signature):
        return None
    return AuthContext(kind="cookie", csrf_token=csrf_for(expires_at, nonce), expires_at=expires_at, nonce=nonce)


def run_cmd(args: list[str], timeout: float = 10.0) -> dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": completed.returncode == 0,
            "returncode": completed.returncode,
            "stdout": truncate_text(completed.stdout.strip()),
            "stderr": truncate_text(completed.stderr.strip()),
            "duration_ms": round((time.time() - started) * 1000),
        }
    except FileNotFoundError as exc:
        return {
            "ok": False,
            "returncode": 127,
            "stdout": "",
            "stderr": str(exc),
            "duration_ms": round((time.time() - started) * 1000),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "returncode": None,
            "stdout": truncate_text(subprocess_text(exc.stdout).strip()),
            "stderr": f"timeout after {timeout}s",
            "duration_ms": round((time.time() - started) * 1000),
        }


def supervisor_status() -> dict[str, Any]:
    result = run_cmd(["supervisorctl", "-c", SUPERVISOR_CONFIG, "status"], timeout=5.0)
    programs = []
    for line in result["stdout"].splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2:
            programs.append(
                {
                    "name": parts[0],
                    "state": parts[1],
                    "description": parts[2] if len(parts) > 2 else "",
                    "ok": parts[1] == "RUNNING",
                }
            )
    result["programs"] = programs
    result["ok"] = result["ok"] and bool(programs)
    return result


def status_payload(auth: AuthContext) -> dict[str, Any]:
    return {
        "ok": True,
        "service": "coze-all-in-one-admin",
        "uptime_seconds": int(time.time() - STARTED_AT),
        "public_url": env("COZE_PUBLIC_URL") or env("SPACE_HOST"),
        "auth": {
            "kind": auth.kind,
            "session_expires_at": auth.expires_at,
            "csrf_token": auth.csrf_token,
        },
        "admin": {
            "enabled": admin_enabled(),
            "host": env("ADMIN_HOST", "127.0.0.1"),
            "port": parse_int(env("ADMIN_PORT"), 8082, minimum=1, maximum=65535),
            "session_ttl_seconds": session_ttl_seconds(),
            "audit_log": str(audit_log_path()),
        },
        "supervisor": supervisor_status(),
    }


def actions_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "actions": [
            {
                "id": "restart-service",
                "method": "POST",
                "path": "/_admin/api/actions/restart-service",
                "requires_confirm": True,
                "allowed_services": ALLOWED_RESTART_SERVICES,
            },
            {
                "id": "run-health-checks",
                "method": "POST",
                "path": "/_admin/api/actions/run-health-checks",
                "requires_confirm": True,
            },
        ],
    }


def new_action_id(action: str) -> str:
    return f"{int(time.time() * 1000)}-{action}-{secrets.token_hex(4)}"


def audit_log_path() -> Path:
    return Path(env("ADMIN_AUDIT_LOG", f"{DATA_DIR}/admin/audit.jsonl"))


def redact_sensitive_details(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            normalized_key = str(key).lower().replace("_", "").replace("-", "")
            if any(marker in normalized_key for marker in SENSITIVE_DETAIL_KEYS):
                redacted[str(key)] = "[redacted]"
            else:
                redacted[str(key)] = redact_sensitive_details(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_details(item) for item in value[:100]]
    if isinstance(value, str):
        return truncate_text(value, 1000)
    return value


def audit_event(action: str, ok: bool, actor: str, target: str = "", details: dict[str, Any] | None = None) -> None:
    entry = {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "action": action,
        "ok": ok,
        "actor": actor,
        "target": target,
        "details": redact_sensitive_details(details or {}),
    }
    path = audit_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        sys.stderr.write(f"[coze-admin] audit write failed: {exc}\n")
        sys.stderr.flush()


def tail_lines(path: Path, lines: int) -> list[str]:
    if not path.exists():
        return []
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            end = file.tell()
            block_size = 8192
            blocks = []
            newline_count = 0
            position = end
            while position > 0 and newline_count <= lines:
                read_size = min(block_size, position)
                position -= read_size
                file.seek(position)
                block = file.read(read_size)
                blocks.append(block)
                newline_count += block.count(b"\n")
        data = b"".join(reversed(blocks))
    except OSError as exc:
        raise AdminError(500, f"unable to read audit log: {exc}") from exc
    return data.decode("utf-8", errors="replace").splitlines()[-lines:]


def audit_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    limit = parse_int(query.get("limit", ["100"])[0], 100, minimum=1, maximum=MAX_AUDIT_EVENTS)
    path = audit_log_path()
    if not path.exists():
        return {
            "ok": True,
            "path": str(path),
            "exists": False,
            "limit": limit,
            "returned": 0,
            "invalid_lines": 0,
            "events": [],
        }
    invalid_lines = 0
    events: list[dict[str, Any]] = []
    for line in reversed(tail_lines(path, limit * 4)):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if not isinstance(event, dict):
            invalid_lines += 1
            continue
        events.append(
            {
                "time": str(event.get("time", "")),
                "action": str(event.get("action", "")),
                "ok": bool(event.get("ok", False)),
                "actor": str(event.get("actor", "")),
                "target": str(event.get("target", "")),
                "details": redact_sensitive_details(event.get("details", {})),
            }
        )
        if len(events) >= limit:
            break
    events.reverse()
    return {
        "ok": True,
        "path": str(path),
        "exists": True,
        "limit": limit,
        "returned": len(events),
        "invalid_lines": invalid_lines,
        "events": events,
    }


def confirmed(payload: dict[str, Any]) -> bool:
    value = payload.get("confirm", False)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def restart_service(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    service = payload.get("service")
    if service not in ALLOWED_RESTART_SERVICES:
        raise AdminError(400, "service is not in restart whitelist", allowed_services=ALLOWED_RESTART_SERVICES)
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    action_id = new_action_id("restart-service")
    result = run_cmd(["supervisorctl", "-c", SUPERVISOR_CONFIG, "restart", service], timeout=45.0)
    response = {"ok": result["ok"], "action_id": action_id, "action": "restart-service", "service": service, "result": result}
    audit_event("restart-service", result["ok"], auth.kind, service, {"action_id": action_id, "returncode": result["returncode"]})
    return response


def run_health_checks(payload: dict[str, Any], auth: AuthContext) -> dict[str, Any]:
    if not confirmed(payload):
        raise AdminError(400, "confirm=true is required")
    action_id = new_action_id("run-health-checks")
    result = run_cmd([HEALTHCHECK], timeout=45.0)
    response = {"ok": result["ok"], "action_id": action_id, "action": "run-health-checks", "result": result}
    audit_event("run-health-checks", result["ok"], auth.kind, "healthcheck", {"action_id": action_id})
    return response


def html_index(authenticated: bool, unavailable_reason: str = "") -> str:
    unavailable_html = f"<p class=\"bad\">{html.escape(unavailable_reason)}</p>" if unavailable_reason else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Coze Admin</title>
  <style>
    :root {{ color-scheme: light; --bg: #f6f7f9; --panel: #fff; --line: #d7dce5; --text: #17202a; --muted: #647184; --ok: #177245; --bad: #b42318; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }}
    h1 {{ margin: 0; font-size: 24px; letter-spacing: 0; }}
    h2 {{ margin: 0 0 10px; font-size: 16px; letter-spacing: 0; }}
    button, input, select {{ min-height: 36px; border: 1px solid var(--line); border-radius: 6px; background: #fff; color: var(--text); font: inherit; padding: 0 10px; }}
    button {{ cursor: pointer; }}
    .grid {{ display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 14px; }}
    .panel {{ grid-column: span 6; background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-width: 0; }}
    .wide {{ grid-column: span 12; }}
    .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    .muted {{ color: var(--muted); }}
    .ok {{ color: var(--ok); }}
    .bad {{ color: var(--bad); }}
    pre {{ max-height: 360px; overflow: auto; margin: 10px 0 0; padding: 12px; border-radius: 6px; background: #111827; color: #e5e7eb; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }}
    #login {{ max-width: 420px; margin: 12vh auto 0; }}
    #login input {{ width: 100%; margin: 10px 0; }}
    .hidden {{ display: none; }}
    @media (max-width: 760px) {{ main {{ padding: 16px; }} header {{ align-items: flex-start; flex-direction: column; }} .panel {{ grid-column: span 12; }} button, input, select {{ width: 100%; }} }}
  </style>
</head>
<body>
  <main>
    <section id="login" class="{'' if not authenticated else 'hidden'}">
      <h1>Coze Admin</h1>
      {unavailable_html}
      <p class="muted">Admin is default-off and requires ADMIN_TOKEN.</p>
      <input id="token" type="password" autocomplete="current-password" placeholder="ADMIN_TOKEN">
      <button id="loginBtn">Open Admin</button>
      <pre id="loginError" class="hidden"></pre>
    </section>
    <section id="dashboard" class="{'' if authenticated else 'hidden'}">
      <header>
        <div>
          <h1>Coze Admin</h1>
          <div class="muted">Whitelisted runtime actions</div>
        </div>
        <div class="toolbar">
          <button data-load="status">Status</button>
          <button data-load="actions">Actions</button>
          <button data-load="audit">Audit</button>
        </div>
      </header>
      <div class="grid">
        <section class="panel">
          <h2>Run Action</h2>
          <div class="toolbar">
            <select id="action">
              <option value="run-health-checks">run-health-checks</option>
              <option value="restart-service">restart-service</option>
            </select>
            <select id="service">
              {''.join(f'<option value="{html.escape(service)}">{html.escape(service)}</option>' for service in ALLOWED_RESTART_SERVICES)}
            </select>
            <button id="runAction">Run</button>
          </div>
        </section>
        <section class="panel">
          <h2>Confirm</h2>
          <p class="muted">Every write action sends confirm=true and is recorded in the audit log.</p>
        </section>
        <section class="panel wide">
          <h2 id="detailTitle">Detail</h2>
          <pre id="detail"></pre>
        </section>
      </div>
    </section>
  </main>
  <script>
    let csrf = '';
    const headers = {{}};
    const login = document.getElementById('login');
    const dashboard = document.getElementById('dashboard');
    const detail = document.getElementById('detail');
    const detailTitle = document.getElementById('detailTitle');
    function showError(message) {{
      const node = document.getElementById('loginError');
      node.textContent = message;
      node.classList.remove('hidden');
    }}
    async function api(path, options = {{}}) {{
      const response = await fetch('/_admin/' + path.replace(/^\\//, ''), {{...options, headers: {{...headers, ...(options.headers || {{}})}}}});
      const type = response.headers.get('content-type') || '';
      const body = type.includes('application/json') ? await response.json() : await response.text();
      if (!response.ok) throw new Error(typeof body === 'string' ? body : JSON.stringify(body, null, 2));
      return body;
    }}
    function render(value) {{ detail.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }}
    async function load(name) {{
      detailTitle.textContent = name;
      const payload = await api('api/' + name);
      if (payload.auth && payload.auth.csrf_token) csrf = payload.auth.csrf_token;
      render(payload);
    }}
    document.getElementById('loginBtn').addEventListener('click', async () => {{
      try {{
        const payload = await api('api/login', {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json'}},
          body: JSON.stringify({{token: document.getElementById('token').value}})
        }});
        csrf = payload.csrf_token || '';
        document.getElementById('token').value = '';
        login.classList.add('hidden');
        dashboard.classList.remove('hidden');
        await load('status');
      }} catch (error) {{
        showError(error.message);
      }}
    }});
    document.querySelectorAll('[data-load]').forEach(button => button.addEventListener('click', () => load(button.dataset.load).catch(error => render(String(error)))));
    document.getElementById('runAction').addEventListener('click', async () => {{
      const action = document.getElementById('action').value;
      const payload = {{confirm: true}};
      if (action === 'restart-service') payload.service = document.getElementById('service').value;
      try {{
        const result = await api('api/actions/' + action, {{
          method: 'POST',
          headers: {{'Content-Type': 'application/json', 'X-Admin-CSRF': csrf}},
          body: JSON.stringify(payload)
        }});
        render(result);
      }} catch (error) {{
        render(String(error));
      }}
    }});
    if (!login.classList.contains('hidden')) document.getElementById('token').focus();
    else load('status').catch(error => render(String(error)));
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CozeAdmin"
    sys_version = ""

    def log_message(self, fmt: str, *args: object) -> None:
        path = self.path.split("?", 1)[0]
        print("[admin] " + fmt % args + f" path={path}", flush=True)

    def normalised_path(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/_admin":
            path = "/"
        elif path.startswith("/_admin/"):
            path = path[len("/_admin") :]
        return path or "/", urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def set_session_cookie(self, cookie_value: str, expires_at: int) -> None:
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE] = cookie_value
        cookie[SESSION_COOKIE]["path"] = "/_admin/"
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        cookie[SESSION_COOKIE]["max-age"] = str(max(0, expires_at - int(time.time())))
        if self.secure_cookie():
            cookie[SESSION_COOKIE]["secure"] = True
        self.send_header("Set-Cookie", cookie.output(header="").strip())

    def secure_cookie(self) -> bool:
        secure_mode = env("ADMIN_COOKIE_SECURE", "auto").lower()
        if secure_mode == "true":
            return True
        if secure_mode == "false":
            return False
        public_url = env("COZE_PUBLIC_URL")
        return (
            self.headers.get("X-Forwarded-Proto") == "https"
            or public_url.startswith("https://")
            or bool(env("SPACE_HOST"))
        )

    def clear_session_cookie(self) -> None:
        cookie = SimpleCookie()
        cookie[SESSION_COOKIE] = ""
        cookie[SESSION_COOKIE]["path"] = "/_admin/"
        cookie[SESSION_COOKIE]["max-age"] = "0"
        cookie[SESSION_COOKIE]["httponly"] = True
        cookie[SESSION_COOKIE]["samesite"] = "Lax"
        if self.secure_cookie():
            cookie[SESSION_COOKIE]["secure"] = True
        self.send_header("Set-Cookie", cookie.output(header="").strip())

    def admin_gate(self, html_response: bool = False) -> bool:
        available, reason = admin_available()
        if available:
            return True
        if admin_enabled():
            if html_response:
                self.send_text(html_index(False, reason), status=503)
            else:
                self.send_json({"ok": False, "status": "locked", "error": reason}, status=503)
        else:
            if html_response:
                self.send_text("not found\n", status=404, content_type="text/plain; charset=utf-8")
            else:
                self.send_json({"status": "not_found"}, status=404)
        return False

    def read_json_payload(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise AdminError(400, "invalid Content-Length") from exc
        if length < 0:
            raise AdminError(400, "invalid Content-Length")
        if length > MAX_JSON_BYTES:
            raise AdminError(413, "JSON payload is too large")
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AdminError(400, f"invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise AdminError(400, "payload must be a JSON object")
        return payload

    def auth_context(self) -> AuthContext | None:
        token = self.headers.get("X-Admin-Token", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(None, 1)[1]
        if token and hmac.compare_digest(token, admin_token()):
            return AuthContext(kind="header", csrf_token="")
        cookie_header = self.headers.get("Cookie", "")
        if cookie_header:
            cookie = SimpleCookie()
            cookie.load(cookie_header)
            morsel = cookie.get(SESSION_COOKIE)
            if morsel:
                return parse_session(morsel.value)
        return None

    def require_auth(self) -> AuthContext | None:
        auth = self.auth_context()
        if auth is None:
            self.send_json({"ok": False, "status": "unauthorized"}, status=401)
            return None
        return auth

    def require_csrf(self, auth: AuthContext) -> bool:
        if auth.kind != "cookie":
            return True
        csrf_header = self.headers.get("X-Admin-CSRF", "")
        if csrf_header and hmac.compare_digest(csrf_header, auth.csrf_token):
            return True
        self.send_json({"ok": False, "status": "forbidden", "error": "valid X-Admin-CSRF header is required"}, status=403)
        return False

    def do_GET(self) -> None:
        path, query = self.normalised_path()
        if path == "/":
            if not self.admin_gate(html_response=True):
                return
            auth = self.auth_context()
            self.send_text(html_index(auth is not None))
            return
        if not self.admin_gate():
            return
        if path not in {"/api/status", "/api/actions", "/api/audit"}:
            self.send_json({"status": "not_found"}, status=404)
            return
        auth = self.require_auth()
        if auth is None:
            return
        if path == "/api/status":
            self.send_json(status_payload(auth))
        elif path == "/api/actions":
            self.send_json(actions_payload())
        elif path == "/api/audit":
            self.send_json(audit_payload(query))

    def do_POST(self) -> None:
        path, _query = self.normalised_path()
        if not self.admin_gate():
            return
        try:
            if path == "/api/login":
                self.handle_login()
                return
            if path == "/api/logout":
                self.handle_logout()
                return
            if path not in {
                "/api/actions/restart-service",
                "/api/actions/run-health-checks",
            }:
                self.send_json({"status": "not_found"}, status=404)
                return
            auth = self.require_auth()
            if auth is None or not self.require_csrf(auth):
                return
            payload = self.read_json_payload()
            if not ACTION_LOCK.acquire(blocking=False):
                raise AdminError(409, "another admin action is already running")
            try:
                if path.endswith("/restart-service"):
                    result = restart_service(payload, auth)
                else:
                    result = run_health_checks(payload, auth)
            finally:
                ACTION_LOCK.release()
            self.send_json(result, status=200 if result.get("ok") else 500)
        except AdminError as exc:
            payload = {"ok": False, "error": exc.message}
            payload.update(exc.extra)
            self.send_json(payload, status=exc.status)

    def handle_login(self) -> None:
        remote_addr = trusted_remote_addr(self.headers, self.client_address)
        retry_after = login_retry_after(remote_addr)
        if retry_after:
            self.send_json({"ok": False, "error": "too many login attempts", "retry_after_seconds": retry_after}, status=429)
            return
        payload = self.read_json_payload()
        supplied = str(payload.get("token", ""))
        if not hmac.compare_digest(supplied, admin_token()):
            record_login_failure(remote_addr)
            audit_event("login", False, "password", remote_addr)
            self.send_json({"ok": False, "status": "unauthorized"}, status=401)
            return
        clear_login_failures(remote_addr)
        cookie_value, csrf_token, expires_at = make_session()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.set_session_cookie(cookie_value, expires_at)
        body = json.dumps({"ok": True, "csrf_token": csrf_token, "expires_at": expires_at}).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        audit_event("login", True, "password", remote_addr)

    def handle_logout(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.clear_session_cookie()
        body = b'{"ok":true}\n'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[admin] listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
