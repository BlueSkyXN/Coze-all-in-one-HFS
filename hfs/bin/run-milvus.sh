#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1090
source "${COZE_ENV_FILE:-/app/.env}"
DATA_DIR="${DATA_DIR:-/data/coze}"

/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 2379 180

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

minio_scheme=""
minio_host_port="${MINIO_ADDRESS}"
case "$minio_host_port" in
  http://*)
    minio_scheme="http"
    minio_host_port="${minio_host_port#http://}"
    ;;
  https://*)
    minio_scheme="https"
    minio_host_port="${minio_host_port#https://}"
    ;;
esac
minio_host_port="${minio_host_port%%/*}"
minio_host="${minio_host_port%%:*}"
if [ "$minio_host" = "$minio_host_port" ]; then
  if [ "$minio_scheme" = "https" ] || [ "${MINIO_USE_SSL:-false}" = "true" ]; then
    minio_port="443"
  elif [ "$minio_scheme" = "http" ]; then
    minio_port="80"
  else
    minio_port="9000"
  fi
else
  minio_port="${minio_host_port##*:}"
fi

if [ "${ENABLE_LOCAL_MINIO:-1}" = "1" ]; then
  /opt/coze-hfs/bin/wait-for.sh 127.0.0.1 9000 180
elif [ "$minio_host_port" = "127.0.0.1:9000" ] || [ "$minio_host_port" = "localhost:9000" ]; then
  echo "[milvus] ENABLE_LOCAL_MINIO=0 requires external MINIO_ADDRESS; got $MINIO_ADDRESS" >&2
  exit 1
else
  echo "[milvus] local MinIO disabled; waiting for external MINIO_ADDRESS=$MINIO_ADDRESS"
  /opt/coze-hfs/bin/wait-for.sh "$minio_host" "$minio_port" 180
fi

mkdir -p "$DATA_DIR/milvus"
if [ ! -L /var/lib/milvus ]; then
  rm -rf /var/lib/milvus
  ln -s "$DATA_DIR/milvus" /var/lib/milvus
fi
mkdir -p /var/lib/milvus
chown -R root:root /var/lib/milvus
chmod g+s /var/lib/milvus

if [ "${ENABLE_LOCAL_MINIO:-1}" = "1" ]; then
  export MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@127.0.0.1:9000"
  mc mb --ignore-existing "local/${MINIO_BUCKET_NAME}" || true
else
  echo "[milvus] skipping local bucket creation for external object storage"
fi

exec milvus run standalone
