#!/usr/bin/env bash
set -euo pipefail

ETCD_AUTO_COMPACTION_MODE_VALUE="${ETCD_AUTO_COMPACTION_MODE:-revision}"
ETCD_AUTO_COMPACTION_RETENTION_VALUE="${ETCD_AUTO_COMPACTION_RETENTION:-1000}"
ETCD_QUOTA_BACKEND_BYTES_VALUE="${ETCD_QUOTA_BACKEND_BYTES:-4294967296}"
DATA_DIR="${DATA_DIR:-/data/coze}"

mkdir -p "$DATA_DIR/etcd"
if [ ! -L /bitnami/etcd ]; then
  rm -rf /bitnami/etcd
  ln -s "$DATA_DIR/etcd" /bitnami/etcd
fi
mkdir -p /bitnami/etcd/data
chown -R root:root /bitnami/etcd || true

unset ALLOW_NONE_AUTHENTICATION ETCD_AUTO_COMPACTION_MODE ETCD_AUTO_COMPACTION_RETENTION ETCD_QUOTA_BACKEND_BYTES

exec etcd \
  --name coze-hfs-etcd \
  --data-dir /bitnami/etcd/data \
  --listen-client-urls http://127.0.0.1:2379 \
  --advertise-client-urls http://127.0.0.1:2379 \
  --listen-peer-urls http://127.0.0.1:2380 \
  --initial-advertise-peer-urls http://127.0.0.1:2380 \
  --initial-cluster coze-hfs-etcd=http://127.0.0.1:2380 \
  --initial-cluster-state new \
  --auto-compaction-mode "$ETCD_AUTO_COMPACTION_MODE_VALUE" \
  --auto-compaction-retention "$ETCD_AUTO_COMPACTION_RETENTION_VALUE" \
  --quota-backend-bytes "$ETCD_QUOTA_BACKEND_BYTES_VALUE"
