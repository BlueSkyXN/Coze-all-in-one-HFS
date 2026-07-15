#!/usr/bin/env python3
"""Read-only operations service for the Coze HFS container."""

from __future__ import annotations

import hmac
import html
import json
import os
import shutil
import socket
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


STARTED_AT = time.time()
HOST = os.environ.get("OPS_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPS_PORT", "8081"))
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data/coze"))
LOG_DIR = Path(os.environ.get("OPS_LOG_DIR", f"{DATA_DIR}/logs"))
MAX_LOG_LINES = 1000
MAX_LOG_BYTES = 1024 * 1024

DEFAULT_SERVICE_LOGS = {
    "mariadb": "mariadb.log",
    "mariadb.err": "mariadb.err",
    "redis": "redis.log",
    "redis.err": "redis.err",
    "nats": "nats.log",
    "nats.err": "nats.err",
    "minio": "minio.log",
    "minio.err": "minio.err",
    "minio-init": "minio-init.log",
    "minio-init.err": "minio-init.err",
    "etcd": "etcd.log",
    "etcd.err": "etcd.err",
    "elasticsearch": "elasticsearch.log",
    "elasticsearch.err": "elasticsearch.err",
    "milvus": "milvus.log",
    "milvus.err": "milvus.err",
    "coze-server": "coze-server.log",
    "coze-server.err": "coze-server.err",
    "ops-service": "ops-service.log",
    "ops-service.err": "ops-service.err",
    "admin-service": "admin-service.log",
    "admin-service.err": "admin-service.err",
    "nginx": "nginx.log",
    "nginx.err": "nginx.err",
}

SAFE_CONFIG_KEYS = [
    "DATA_DIR",
    "COZE_PUBLIC_URL",
    "SPACE_HOST",
    "SPACE_ID",
    "DISABLE_USER_REGISTRATION",
    "ALLOW_REGISTRATION_EMAIL",
    "ENABLE_LOCAL_MINIO",
    "FILE_UPLOAD_COMPONENT_TYPE",
    "STORAGE_TYPE",
    "ES_ADDR",
    "ES_VERSION",
    "VECTOR_STORE_TYPE",
    "CODE_RUNNER_TYPE",
    "OPS_HOST",
    "OPS_PORT",
    "OPS_CACHE_TTL_SECONDS",
    "OPS_LOG_DIR",
    "OPS_LOG_LINES_MAX",
    "OPS_LOG_TAIL_MAX_BYTES",
    "ADMIN_ENABLED",
    "ADMIN_HOST",
    "ADMIN_PORT",
    "ADMIN_SESSION_TTL_SECONDS",
    "ADMIN_COOKIE_SECURE",
    "ADMIN_AUDIT_LOG",
]

SECRET_KEYS = [
    "OPS_TOKEN",
    "ADMIN_TOKEN",
    "ADMIN_CSRF_KEY",
    "MYSQL_ROOT_PASSWORD",
    "MYSQL_PASSWORD",
    "MINIO_ROOT_PASSWORD",
    "MINIO_SECRET_ACCESS_KEY",
    "MODEL_API_KEY_0",
    "BUILTIN_CM_OPENAI_API_KEY",
    "OPENAI_EMBEDDING_API_KEY",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "ES_PASSWORD",
    "VIKING_DB_AK",
    "VIKING_DB_SK",
    "TOS_ACCESS_KEY",
    "TOS_SECRET_KEY",
]

ERROR_PATTERNS = [
    "Permission denied",
    "Traceback",
    "panic:",
    "FATAL",
    "ERROR",
    "[error]",
    "connect() failed",
    "exited:",
    "cannot execute",
]

PROCESS_MATCHERS = {
    "mariadb": ("mariadbd", "mysqld"),
    "redis": ("redis-server",),
    "nats": ("nats-server",),
    "minio": ("minio server",),
    "etcd": ("/etcd",),
    "elasticsearch": ("elasticsearch",),
    "milvus": ("/milvus/bin/milvus",),
    "coze-server": ("/app/opencoze",),
    "ops-service": ("ops_service.py",),
    "admin-service": ("admin_service.py",),
    "nginx": ("nginx",),
}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


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


def ops_token() -> str:
    return env("OPS_TOKEN")


def ops_lock_reason() -> str:
    token = ops_token()
    if not token:
        return "OPS_TOKEN is not set"
    if len(token) < 24:
        return "OPS_TOKEN must contain at least 24 characters"
    return ""


def tcp_check(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def health_checks() -> dict[str, bool]:
    checks = {
        "mariadb": tcp_check("127.0.0.1", int(env("MYSQL_PORT", "3306"))),
        "redis": tcp_check("127.0.0.1", 6379),
        "nats": tcp_check("127.0.0.1", 4222),
        "etcd": tcp_check("127.0.0.1", 2379),
        "elasticsearch": tcp_check("127.0.0.1", 9200),
        "milvus": tcp_check("127.0.0.1", 19530),
        "coze_server": tcp_check("127.0.0.1", 8888),
        "data_dir": DATA_DIR.exists() and os.access(DATA_DIR, os.W_OK),
    }
    if env("ENABLE_LOCAL_MINIO", "1") == "1":
        checks["minio"] = tcp_check("127.0.0.1", 9000)
    return checks


def health_payload() -> tuple[int, dict[str, Any]]:
    checks = health_checks()
    status = "ok" if all(checks.values()) else "degraded"
    code = 200 if status == "ok" else 503
    return code, {
        "status": status,
        "ok": status == "ok",
        "service": "coze-all-in-one-hfs",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "uptime_seconds": int(time.time() - STARTED_AT),
        "checks": checks,
        "data_dir": str(DATA_DIR),
        "public_url": env("COZE_PUBLIC_URL") or env("SPACE_HOST"),
    }


def process_names_for(command: str) -> list[str]:
    lower = command.lower()
    return [
        name
        for name, matchers in PROCESS_MATCHERS.items()
        if any(matcher.lower() in lower for matcher in matchers)
    ]


def processes_payload() -> dict[str, Any]:
    found: dict[str, list[int]] = {name: [] for name in PROCESS_MATCHERS}
    scan_errors = 0
    proc_root = Path("/proc")
    if not proc_root.exists():
        return {"ok": False, "error": "/proc is unavailable", "programs": []}
    for process_dir in proc_root.iterdir():
        if not process_dir.name.isdigit():
            continue
        try:
            comm = (process_dir / "comm").read_text(encoding="utf-8", errors="replace").strip()
            cmdline = (process_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
        except OSError:
            scan_errors += 1
            continue
        for name in process_names_for(f"{comm} {cmdline}"):
            found[name].append(int(process_dir.name))
    programs = [
        {"name": name, "running": bool(pids), "pids": sorted(pids)}
        for name, pids in sorted(found.items())
        if name != "minio" or env("ENABLE_LOCAL_MINIO", "1") == "1"
    ]
    return {"ok": True, "programs": programs, "scan_errors": scan_errors}


def memory_payload() -> dict[str, Any]:
    info: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, value = line.split(":", 1)
            amount = value.strip().split()[0]
            info[key] = int(amount) * 1024
    except (OSError, ValueError, IndexError):
        return {"ok": False}
    total = info.get("MemTotal", 0)
    available = info.get("MemAvailable", 0)
    return {
        "ok": total > 0,
        "total_bytes": total,
        "available_bytes": available,
        "used_percent": round((1 - available / total) * 100, 2) if total else None,
    }


def disk_payload(path: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(path if path.exists() else path.parent)
    return {
        "path": str(path),
        "total_bytes": usage.total,
        "used_bytes": usage.used,
        "free_bytes": usage.free,
        "used_percent": round((usage.used / usage.total) * 100, 2) if usage.total else None,
    }


def system_payload() -> dict[str, Any]:
    loadavg: list[float] = []
    try:
        loadavg = list(os.getloadavg())
    except OSError:
        pass
    return {
        "ok": True,
        "service": "coze-all-in-one-ops",
        "uptime_seconds": int(time.time() - STARTED_AT),
        "process_count": len([p for p in Path("/proc").iterdir() if p.name.isdigit()]) if Path("/proc").exists() else None,
        "cpu_count": os.cpu_count(),
        "loadavg": loadavg,
        "memory": memory_payload(),
        "disk": {
            "root": disk_payload(Path("/")),
            "data": disk_payload(DATA_DIR),
        },
    }


def config_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "safe_config": {key: env(key) for key in SAFE_CONFIG_KEYS if key in os.environ},
        "secret_presence": {key: bool(env(key)) for key in SECRET_KEYS},
        "log_services": sorted(service_logs()),
        "ops": {
            "locked": bool(ops_lock_reason()),
            "lock_reason": ops_lock_reason(),
            "authentication": ["X-Ops-Token", "Authorization: Bearer"],
        },
    }


def version_payload() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "coze-all-in-one-hfs",
        "space": {
            "id": env("SPACE_ID"),
            "host": env("SPACE_HOST"),
        },
        "coze": {
            "server_tag": env("COZE_SERVER_TAG"),
            "web_tag": env("COZE_WEB_TAG"),
            "git_ref": env("COZE_GIT_REF"),
        },
        "runtime": {
            "data_dir": str(DATA_DIR),
            "started_at": int(STARTED_AT),
            "uptime_seconds": int(time.time() - STARTED_AT),
        },
    }


def safe_log_filename(filename: Any) -> str | None:
    if not isinstance(filename, str) or not filename:
        return None
    path = Path(filename)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if resolve_log_path(str(path)) is None:
        return None
    return str(path)


def resolve_log_path(filename: str) -> Path | None:
    root = LOG_DIR.resolve(strict=False)
    target = (root / filename).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def service_logs() -> dict[str, str]:
    logs = dict(DEFAULT_SERVICE_LOGS)
    raw = env("OPS_LOG_SERVICES_JSON")
    if not raw:
        return logs
    try:
        configured = json.loads(raw)
    except json.JSONDecodeError:
        return logs
    if not isinstance(configured, dict):
        return logs
    for service, filename in configured.items():
        if not isinstance(service, str) or not service:
            continue
        safe = safe_log_filename(filename)
        if safe:
            logs[service] = safe
    return logs


def tail_file(path: Path, lines: int) -> str:
    max_bytes = parse_int(env("OPS_LOG_TAIL_MAX_BYTES"), MAX_LOG_BYTES, minimum=1024, maximum=16 * 1024 * 1024)
    try:
        with path.open("rb") as file:
            file.seek(0, os.SEEK_END)
            end = file.tell()
            start = max(0, end - max_bytes)
            file.seek(start)
            data = file.read(max_bytes)
    except OSError as exc:
        return f"unable to read log: {exc}"
    text = data.decode("utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def logs_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    services = service_logs()
    service = query.get("service", [""])[0]
    lines = parse_int(query.get("lines", ["200"])[0], 200, minimum=1, maximum=parse_int(env("OPS_LOG_LINES_MAX"), MAX_LOG_LINES, 1, 5000))
    if service not in services:
        return {"ok": False, "error": "unknown log service", "available_services": sorted(services)}
    path = resolve_log_path(services[service])
    if path is None:
        return {"ok": False, "error": "log path is unsafe"}
    exists = path.exists() and path.is_file()
    return {
        "ok": exists,
        "service": service,
        "path": str(path),
        "exists": exists,
        "lines": lines,
        "content": tail_file(path, lines) if exists else "",
    }


def matched_error_pattern(line: str) -> str | None:
    lower = line.lower()
    for pattern in ERROR_PATTERNS:
        if pattern.lower() in lower:
            return pattern
    return None


def errors_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    lines = parse_int(query.get("lines", ["300"])[0], 300, minimum=1, maximum=1000)
    matches: dict[str, list[dict[str, str]]] = {}
    for service, filename in service_logs().items():
        path = resolve_log_path(filename)
        if path is None or not path.exists() or not path.is_file():
            continue
        service_matches = []
        for line in tail_file(path, lines).splitlines():
            pattern = matched_error_pattern(line)
            if pattern:
                service_matches.append({"pattern": pattern, "line": truncate_text(line, 1000)})
        if service_matches:
            matches[service] = service_matches[-50:]
    return {
        "ok": not matches,
        "services_scanned": len(service_logs()),
        "matches": matches,
    }


def metrics_payload() -> str:
    code, health = health_payload()
    system = system_payload()
    lines = [
        "# HELP coze_hfs_ops_up Ops service availability.",
        "# TYPE coze_hfs_ops_up gauge",
        "coze_hfs_ops_up 1",
        "# HELP coze_hfs_health_ok Overall HFS runtime health.",
        "# TYPE coze_hfs_health_ok gauge",
        f"coze_hfs_health_ok {1 if code == 200 else 0}",
        "# HELP coze_hfs_check_ok Individual health checks.",
        "# TYPE coze_hfs_check_ok gauge",
    ]
    for name, ok in sorted(health["checks"].items()):
        lines.append(f'coze_hfs_check_ok{{check="{name}"}} {1 if ok else 0}')
    memory = system["memory"]
    if memory.get("ok"):
        lines.append(f'coze_hfs_memory_available_bytes {memory["available_bytes"]}')
    lines.append(f'coze_hfs_uptime_seconds {system["uptime_seconds"]}')
    return "\n".join(lines) + "\n"


def html_index(authenticated: bool, locked_reason: str = "") -> str:
    locked_html = f"<p class=\"bad\">{html.escape(locked_reason)}</p>" if locked_reason else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" href="data:,">
  <title>Coze Ops</title>
  <style>
    :root {{ color-scheme: light; --bg: #f6f7f9; --panel: #fff; --line: #d7dce5; --text: #17202a; --muted: #647184; --ok: #177245; --bad: #b42318; --fill: #1d4ed8; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.45; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
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
    .pill {{ display: inline-flex; min-height: 28px; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 0 10px; background: #fff; color: var(--muted); font-size: 13px; }}
    .pill.ok {{ color: var(--ok); border-color: #a7d7bd; background: #eefaf3; }}
    .pill.bad {{ color: var(--bad); border-color: #f1b5ae; background: #fff1ef; }}
    pre {{ max-height: 360px; overflow: auto; margin: 10px 0 0; padding: 12px; border-radius: 6px; background: #111827; color: #e5e7eb; font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ padding: 7px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }}
    th {{ color: var(--muted); }}
    #login {{ max-width: 420px; margin: 12vh auto 0; }}
    #login input {{ width: 100%; margin: 10px 0; }}
    .hidden {{ display: none; }}
    @media (max-width: 760px) {{ main {{ padding: 16px; }} header {{ align-items: flex-start; flex-direction: column; }} .panel {{ grid-column: span 12; }} button, input, select {{ width: 100%; }} }}
  </style>
</head>
<body>
  <main>
    <section id="login" class="{'' if not authenticated else 'hidden'}">
      <h1>Coze Ops</h1>
      {locked_html}
      <p class="muted">Use the configured OPS_TOKEN. Header auth is preferred for automation.</p>
      <input id="token" type="password" autocomplete="current-password" placeholder="OPS_TOKEN">
      <button id="loginBtn">Open Dashboard</button>
      <pre id="loginError" class="hidden"></pre>
    </section>
    <section id="dashboard" class="{'' if authenticated else 'hidden'}">
      <header>
        <div>
          <h1>Coze Ops</h1>
          <div class="muted">Read-only runtime diagnostics</div>
        </div>
        <div class="toolbar">
          <button data-load="health">Health</button>
          <button data-load="processes">Processes</button>
          <button data-load="system">System</button>
          <button data-load="config">Config</button>
          <button data-load="errors">Errors</button>
          <button data-load="metrics">Metrics</button>
        </div>
      </header>
      <div class="grid">
        <section class="panel">
          <h2>Status</h2>
          <div id="summary" class="muted">Loading...</div>
        </section>
        <section class="panel">
          <h2>Logs</h2>
          <div class="toolbar">
            <select id="logService"></select>
            <button id="loadLog">Load</button>
          </div>
        </section>
        <section class="panel wide">
          <h2 id="detailTitle">Detail</h2>
          <pre id="detail"></pre>
        </section>
      </div>
    </section>
  </main>
  <script>
    const headers = {{}};
    const login = document.getElementById('login');
    const dashboard = document.getElementById('dashboard');
    const detail = document.getElementById('detail');
    const detailTitle = document.getElementById('detailTitle');
    const summary = document.getElementById('summary');
    const logService = document.getElementById('logService');
    function showError(message) {{
      const node = document.getElementById('loginError');
      node.textContent = message;
      node.classList.remove('hidden');
    }}
    async function api(path, options = {{}}) {{
      const response = await fetch('/_ops/' + path.replace(/^\\//, ''), {{...options, headers: {{...headers, ...(options.headers || {{}})}}}});
      const type = response.headers.get('content-type') || '';
      const body = type.includes('application/json') ? await response.json() : await response.text();
      if (!response.ok) throw new Error(typeof body === 'string' ? body : JSON.stringify(body, null, 2));
      return body;
    }}
    function render(value) {{ detail.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2); }}
    async function load(name) {{
      detailTitle.textContent = name;
      const endpoint = name === 'processes' ? 'processes' : name;
      const payload = await api(endpoint);
      render(payload);
      if (name === 'health') {{
        summary.innerHTML = '<span class="pill ' + (payload.status === 'ok' ? 'ok' : 'bad') + '">' + payload.status + '</span>';
      }}
      if (name === 'config') {{
        logService.innerHTML = '';
        for (const service of payload.log_services || []) {{
          const option = document.createElement('option');
          option.value = service;
          option.textContent = service;
          logService.appendChild(option);
        }}
      }}
    }}
    document.getElementById('loginBtn').addEventListener('click', async () => {{
      const token = document.getElementById('token').value;
      headers['X-Ops-Token'] = token;
      try {{
        await load('health');
        document.getElementById('token').value = '';
        login.classList.add('hidden');
        dashboard.classList.remove('hidden');
        await load('config');
      }} catch (error) {{
        showError(error.message);
      }}
    }});
    document.querySelectorAll('[data-load]').forEach(button => button.addEventListener('click', () => load(button.dataset.load).catch(error => render(String(error)))));
    document.getElementById('loadLog').addEventListener('click', () => api('logs?service=' + encodeURIComponent(logService.value)).then(render).catch(error => render(String(error))));
    if (!login.classList.contains('hidden')) {{
      document.getElementById('token').focus();
    }} else {{
      load('health').then(() => load('config')).catch(error => render(String(error)));
    }}
  </script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "CozeOps"
    sys_version = ""

    def log_message(self, fmt: str, *args: object) -> None:
        path = self.path.split("?", 1)[0]
        print("[ops] " + fmt % args + f" path={path}", flush=True)

    def send_json(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, code: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def normalised_path(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/_ops":
            path = "/"
        elif path.startswith("/_ops/"):
            path = path[len("/_ops") :]
        return path or "/", urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def auth_ok(self) -> bool:
        token = ops_token()
        if ops_lock_reason():
            return False
        header_token = self.headers.get("X-Ops-Token", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            header_token = auth.split(None, 1)[1]
        if header_token and hmac.compare_digest(header_token, token):
            return True
        return False

    def require_auth(self, path: str) -> bool:
        if self.auth_ok():
            return True
        reason = ops_lock_reason()
        if path == "/":
            self.send_text(503 if reason else 200, html_index(False, reason), "text/html; charset=utf-8")
        elif reason:
            self.send_json(503, {"ok": False, "status": "locked", "error": reason})
        else:
            self.send_json(401, {"ok": False, "status": "unauthorized"})
        return False

    def do_GET(self) -> None:
        path, query = self.normalised_path()
        if "token" in query:
            self.send_json(400, {"ok": False, "status": "bad_request", "error": "tokens are not accepted in URLs"})
            return
        if path in {"/healthz", "/readyz", "/status"}:
            code, payload = health_payload()
            self.send_json(code, payload)
            return
        if path not in {"/", "/health", "/processes", "/system", "/config", "/version", "/logs", "/errors", "/metrics"}:
            self.send_json(404, {"status": "not_found"})
            return
        if not self.require_auth(path):
            return
        if path == "/":
            self.send_text(200, html_index(True), "text/html; charset=utf-8")
            return
        if path == "/health":
            code, payload = health_payload()
            self.send_json(code, payload)
        elif path == "/processes":
            self.send_json(200, processes_payload())
        elif path == "/system":
            self.send_json(200, system_payload())
        elif path == "/config":
            self.send_json(200, config_payload())
        elif path == "/version":
            self.send_json(200, version_payload())
        elif path == "/logs":
            payload = logs_payload(query)
            self.send_json(200 if payload.get("ok") or payload.get("exists") is False else 400, payload)
        elif path == "/errors":
            self.send_json(200, errors_payload(query))
        elif path == "/metrics":
            self.send_text(200, metrics_payload(), "text/plain; version=0.0.4; charset=utf-8")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[ops] listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
