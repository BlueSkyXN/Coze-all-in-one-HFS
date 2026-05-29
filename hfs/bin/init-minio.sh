#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1090
source "${COZE_ENV_FILE:-/app/.env}"

if [ "${ENABLE_LOCAL_MINIO:-1}" != "1" ]; then
  echo "[minio-init] local MinIO disabled; skipping"
  exit 0
fi

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER must be set by render-env.sh}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD must be set by render-env.sh}"

export MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@127.0.0.1:9000"

for i in $(seq 1 90); do
  if mc ready local >/dev/null 2>&1; then
    break
  fi
  echo "[minio-init] waiting for MinIO... ($i/90)"
  sleep 2
  if [ "$i" = "90" ]; then
    echo "[minio-init] MinIO did not become ready" >&2
    exit 1
  fi
done

mc mb --ignore-existing "local/${STORAGE_BUCKET:-opencoze}"
if [ -n "${MINIO_DEFAULT_BUCKETS:-}" ]; then
  IFS=',' read -ra buckets <<< "${MINIO_DEFAULT_BUCKETS}"
  for b in "${buckets[@]}"; do
    if [ -n "$b" ]; then
      mc mb --ignore-existing "local/$b" || true
    fi
  done
fi

echo "[minio-init] buckets ready"
