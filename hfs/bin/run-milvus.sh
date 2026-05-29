#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "${COZE_ENV_FILE:-/app/.env}"
DATA_DIR="${DATA_DIR:-/data/coze}"

/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 2379 180
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 9000 180

export ETCD_ENDPOINTS="${ETCD_ENDPOINTS:-127.0.0.1:2379}"
export MINIO_ADDRESS="${MINIO_ADDRESS:-127.0.0.1:9000}"
export MINIO_BUCKET_NAME="${MINIO_BUCKET_NAME:-${MINIO_DEFAULT_BUCKETS:-milvus}}"
export MINIO_ACCESS_KEY_ID="${MINIO_ACCESS_KEY_ID:-${MINIO_ROOT_USER}}"
export MINIO_SECRET_ACCESS_KEY="${MINIO_SECRET_ACCESS_KEY:-${MINIO_ROOT_PASSWORD}}"
export MINIO_USE_SSL="${MINIO_USE_SSL:-false}"
export LOG_LEVEL="${MILVUS_LOG_LEVEL:-warn}"
export LD_LIBRARY_PATH="/milvus/lib:${LD_LIBRARY_PATH:-}"
if [ -f /milvus/lib/libjemalloc.so ]; then
  export LD_PRELOAD="${LD_PRELOAD:-/milvus/lib/libjemalloc.so}"
fi
export MALLOC_CONF="${MALLOC_CONF:-background_thread:true}"

mkdir -p "$DATA_DIR/milvus"
if [ ! -L /var/lib/milvus ]; then
  rm -rf /var/lib/milvus
  ln -s "$DATA_DIR/milvus" /var/lib/milvus
fi
mkdir -p /var/lib/milvus
chown -R root:root /var/lib/milvus
chmod g+s /var/lib/milvus

export MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@127.0.0.1:9000"
mc mb --ignore-existing "local/${MINIO_BUCKET_NAME}" || true

exec milvus run standalone
