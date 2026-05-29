#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "${COZE_ENV_FILE:-/app/.env}"

if [ "${ENABLE_LOCAL_MINIO:-1}" != "1" ]; then
  echo "[minio-init] local MinIO disabled; skipping"
  exit 0
fi

export MC_HOST_local="http://${MINIO_ROOT_USER:-minioadmin}:${MINIO_ROOT_PASSWORD:-minioadmin123}@127.0.0.1:9000"

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
    [ -n "$b" ] && mc mb --ignore-existing "local/$b" || true
  done
fi

echo "[minio-init] buckets ready"
