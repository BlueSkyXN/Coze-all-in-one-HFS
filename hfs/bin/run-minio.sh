#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "${COZE_ENV_FILE:-/app/.env}"

if [ "${ENABLE_LOCAL_MINIO:-1}" != "1" ]; then
  echo "[minio] ENABLE_LOCAL_MINIO != 1; local MinIO fallback disabled"
  exit 0
fi

export MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
export MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin123}"

mkdir -p /data/coze/minio
exec minio server /data/coze/minio --address 127.0.0.1:9000 --console-address 127.0.0.1:9001
