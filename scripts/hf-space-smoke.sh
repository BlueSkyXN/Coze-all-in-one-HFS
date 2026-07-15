#!/usr/bin/env bash
set -euo pipefail

base="${1:-${HF_SPACE_URL:-${SMOKE_BASE_URL:-https://blueskyxn-coze-all-in-one-hfs.hf.space}}}"
base="${base%/}"
SMOKE_RETRIES="${SMOKE_RETRIES:-12}"
SMOKE_DELAY="${SMOKE_DELAY:-5}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-30}"
OPS_TOKEN="${OPS_TOKEN:-}"
ADMIN_TOKEN="${ADMIN_TOKEN:-}"
SMOKE_ADMIN_ENABLED="${SMOKE_ADMIN_ENABLED:-${ADMIN_ENABLED:-false}}"
SMOKE_ADMIN_ACTIONS="${SMOKE_ADMIN_ACTIONS:-false}"

tmp_body=$(mktemp)
tmp_headers=$(mktemp)
trap 'rm -f "$tmp_body" "$tmp_headers"' EXIT

fetch_path() {
  local label="$1"
  local path="$2"
  local expected="$3"
  local status=""
  local attempt

  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    : >"$tmp_body"
    : >"$tmp_headers"
    status=$(curl -sS -L -D "$tmp_headers" -o "$tmp_body" -w '%{http_code}' --max-time "$SMOKE_TIMEOUT" "${base}${path}" || true)
    if [ "$status" = "$expected" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return 0
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP %s, got %s (%s/%s)\n' "$label" "$expected" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done

  printf 'FAIL %s: expected HTTP %s, got %s\n' "$label" "$expected" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  return 1
}

check_no_x_frame_options() {
  local label="$1"
  if grep -qi '^x-frame-options:' "$tmp_headers"; then
    printf 'FAIL %s: X-Frame-Options blocks Hugging Face iframe embedding\n' "$label" >&2
    grep -i '^x-frame-options:' "$tmp_headers" >&2 || true
    return 1
  fi
}

check_ops_health_json() {
  python3 - "$tmp_body" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "ok":
    raise SystemExit(f"ops status is not ok: {payload.get('status')!r}")
if payload.get("code_runner_type") != "sandbox":
    raise SystemExit(f"code runner is not sandbox: {payload.get('code_runner_type')!r}")
checks = payload.get("checks")
if not isinstance(checks, dict) or not checks:
    raise SystemExit("ops checks must be a non-empty object")
failed = sorted(name for name, ok in checks.items() if ok is not True)
if failed:
    raise SystemExit("ops checks failed: " + ", ".join(failed))
PY
  printf 'PASS ops-health-json: status ok, code runner sandbox, and all checks true\n'
}

check_ops() {
  local label="$1"
  local path="$2"
  local status=""
  local attempt
  if [ -z "$OPS_TOKEN" ]; then
    printf 'SKIP %s: OPS_TOKEN is not set\n' "$label"
    return 0
  fi
  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    : >"$tmp_body"
    status=$(curl -sS -L -o "$tmp_body" -w '%{http_code}' --max-time "$SMOKE_TIMEOUT" \
      -H "X-Ops-Token: $OPS_TOKEN" \
      "${base}${path}" || true)
    if [ "$status" = "200" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return 0
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP 200, got %s (%s/%s)\n' "$label" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done
  printf 'FAIL %s: expected HTTP 200, got %s\n' "$label" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  return 1
}

check_admin() {
  local label="$1"
  local path="$2"
  local status=""
  local attempt
  if [ -z "$ADMIN_TOKEN" ]; then
    printf 'FAIL %s: ADMIN_TOKEN is not set\n' "$label" >&2
    return 1
  fi
  for attempt in $(seq 1 "$SMOKE_RETRIES"); do
    : >"$tmp_body"
    status=$(curl -sS -L -o "$tmp_body" -w '%{http_code}' --max-time "$SMOKE_TIMEOUT" \
      -H "X-Admin-Token: $ADMIN_TOKEN" \
      "${base}${path}" || true)
    if [ "$status" = "200" ]; then
      printf 'PASS %s: HTTP %s\n' "$label" "$status"
      return 0
    fi
    if [ "$attempt" != "$SMOKE_RETRIES" ]; then
      printf 'WAIT %s: expected HTTP 200, got %s (%s/%s)\n' "$label" "$status" "$attempt" "$SMOKE_RETRIES" >&2
      sleep "$SMOKE_DELAY"
    fi
  done
  printf 'FAIL %s: expected HTTP 200, got %s\n' "$label" "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  return 1
}

check_admin_action() {
  local status
  if [ "$SMOKE_ADMIN_ACTIONS" != "true" ]; then
    printf 'SKIP admin-run-health-checks: SMOKE_ADMIN_ACTIONS is not true\n'
    return 0
  fi
  status=$(curl -sS -o "$tmp_body" -w '%{http_code}' --max-time 60 \
    -X POST \
    -H "X-Admin-Token: $ADMIN_TOKEN" \
    -H "X-Admin-CSRF: smoke" \
    -H "Content-Type: application/json" \
    -d '{"confirm":true}' \
    "$base/_admin/api/actions/run-health-checks" || true)
  if [ "$status" = "200" ]; then
    printf 'PASS admin-run-health-checks: HTTP %s\n' "$status"
    return 0
  fi
  printf 'FAIL admin-run-health-checks: expected HTTP 200, got %s\n' "$status" >&2
  sed -n '1,80p' "$tmp_body" >&2 || true
  return 1
}

check_sign_page() {
  if ! grep -Eiq '(@coze-studio/app|coze)' "$tmp_body"; then
    printf 'FAIL sign-page: response does not look like Coze Web HTML\n' >&2
    sed -n '1,40p' "$tmp_body" >&2 || true
    return 1
  fi
  check_no_x_frame_options "sign-page"
  printf 'PASS sign-page: Coze Web HTML is iframe-compatible\n'
}

fetch_path "nginx-health" "/nginx-health" "200"
fetch_path "ops-healthz" "/_ops/healthz" "200"
check_ops_health_json
fetch_path "ops-query-token-rejected" "/_ops/?token=redacted-smoke-value" "400"
fetch_path "upstream-admin-ui-blocked" "/admin" "404"
fetch_path "upstream-admin-api-blocked" "/api/admin/config/basic/get" "404"
if [ "$SMOKE_ADMIN_ENABLED" = "true" ]; then
  fetch_path "admin-root" "/_admin/" "200"
  check_admin "admin-status" "/_admin/api/status"
  check_admin "admin-actions" "/_admin/api/actions"
  check_admin "admin-audit" "/_admin/api/audit?limit=5"
  check_admin_action
else
  fetch_path "admin-disabled" "/_admin/" "404"
fi
check_ops "ops-health" "/_ops/health"
check_ops "ops-system" "/_ops/system"
check_ops "ops-metrics" "/_ops/metrics"
check_ops "ops-errors" "/_ops/errors"
fetch_path "sign-page" "/sign" "200"
check_sign_page

echo "hf space smoke passed: $base"
