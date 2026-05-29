#!/usr/bin/env bash
set -euo pipefail

host="${1:?host required}"
port="${2:?port required}"
timeout="${3:-120}"

for _ in $(seq 1 "$timeout"); do
  if nc -z "$host" "$port" >/dev/null 2>&1; then
    exit 0
  fi
  sleep 1
done

echo "timeout waiting for $host:$port" >&2
exit 1
