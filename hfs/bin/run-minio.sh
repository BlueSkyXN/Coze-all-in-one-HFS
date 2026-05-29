#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1090
source "${COZE_ENV_FILE:-/app/.env}"
DATA_DIR="${DATA_DIR:-/data/coze}"

if [ "${ENABLE_LOCAL_MINIO:-1}" != "1" ]; then
  echo "[minio] ENABLE_LOCAL_MINIO != 1; local MinIO fallback disabled"
  exit 0
fi

: "${MINIO_ROOT_USER:?MINIO_ROOT_USER must be set by render-env.sh}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD must be set by render-env.sh}"

mkdir -p "$DATA_DIR/minio"
exec minio server "$DATA_DIR/minio" --address 127.0.0.1:9000 --console-address 127.0.0.1:9001
