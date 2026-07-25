#!/usr/bin/env bash
set -euo pipefail

export DATA_DIR="${DATA_DIR:-/data/coze}"
export RUN_DIR="${RUN_DIR:-/run/coze}"

echo "[entrypoint] starting Coze HFS runtime with DATA_DIR=$DATA_DIR"
echo "[entrypoint] ensuring runtime directories"
mkdir -p \
  "$RUN_DIR" \
  "$DATA_DIR/admin" \
  "$DATA_DIR/mysql" \
  "$DATA_DIR/redis" \
  "$DATA_DIR/nats" \
  "$DATA_DIR/minio" \
  "$DATA_DIR/etcd" \
  "$DATA_DIR/logs"

echo "[entrypoint] rendering env"
/opt/coze-hfs/bin/render-env.sh

echo "[entrypoint] fixing runtime directory ownership"
chown user:user \
  "$RUN_DIR" \
  "$DATA_DIR" \
  "$DATA_DIR/mysql" \
  "$DATA_DIR/redis" \
  "$DATA_DIR/nats" \
  "$DATA_DIR/minio" \
  "$DATA_DIR/logs" \
  /run/nginx /var/lib/nginx /var/log/nginx || true
chown -R user:user "$DATA_DIR/logs" || true
chown -R cozeadmin:cozeadmin "$DATA_DIR/admin"

echo "[entrypoint] bootstrapping MariaDB"
/opt/coze-hfs/bin/mysql-init.sh

echo "[entrypoint] starting supervisor"
exec /usr/bin/supervisord -c /opt/coze-hfs/conf/supervisord.conf
