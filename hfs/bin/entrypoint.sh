#!/usr/bin/env bash
set -euo pipefail

export DATA_DIR="${DATA_DIR:-/data/coze}"

echo "[entrypoint] starting Coze HFS runtime with DATA_DIR=$DATA_DIR"
echo "[entrypoint] ensuring runtime directories"
mkdir -p \
  "$DATA_DIR/mysql" \
  "$DATA_DIR/redis" \
  "$DATA_DIR/nats" \
  "$DATA_DIR/minio" \
  "$DATA_DIR/elasticsearch" \
  "$DATA_DIR/etcd" \
  "$DATA_DIR/milvus" \
  "$DATA_DIR/logs" \
  "$DATA_DIR/run" \
  "$DATA_DIR/nginx/proxy_temp" \
  "$DATA_DIR/nginx/client_body_temp" \
  "$DATA_DIR/nginx/fastcgi_temp" \
  "$DATA_DIR/nginx/uwsgi_temp" \
  "$DATA_DIR/nginx/scgi_temp"

echo "[entrypoint] rendering env"
/opt/coze-hfs/bin/render-env.sh

echo "[entrypoint] fixing runtime directory ownership"
chown user:user \
  "$DATA_DIR" \
  "$DATA_DIR/mysql" \
  "$DATA_DIR/redis" \
  "$DATA_DIR/nats" \
  "$DATA_DIR/minio" \
  "$DATA_DIR/logs" \
  "$DATA_DIR/run" \
  "$DATA_DIR/nginx/proxy_temp" \
  "$DATA_DIR/nginx/client_body_temp" \
  "$DATA_DIR/nginx/fastcgi_temp" \
  "$DATA_DIR/nginx/uwsgi_temp" \
  "$DATA_DIR/nginx/scgi_temp" \
  /run/nginx /var/lib/nginx /var/log/nginx || true

echo "[entrypoint] bootstrapping MariaDB"
/opt/coze-hfs/bin/mysql-init.sh

echo "[entrypoint] starting supervisor"
exec /usr/bin/supervisord -c /opt/coze-hfs/conf/supervisord.conf
