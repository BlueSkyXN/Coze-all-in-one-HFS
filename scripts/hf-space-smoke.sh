#!/usr/bin/env bash
set -euo pipefail

base="${1:-${SMOKE_BASE_URL:-https://blueskyxn-coze-all-in-one-hfs.hf.space}}"
base="${base%/}"

curl_json() {
  local path="$1"
  echo "GET ${base}${path}"
  curl -fsS --retry 3 --retry-delay 5 --max-time 30 "${base}${path}"
  echo
}

curl_text() {
  local path="$1"
  echo "GET ${base}${path}"
  curl -fsS --retry 3 --retry-delay 5 --max-time 30 "${base}${path}" >/dev/null
}

curl_text /nginx-health
curl_json /_ops/healthz
curl_text /sign

echo "hf space smoke passed: $base"
