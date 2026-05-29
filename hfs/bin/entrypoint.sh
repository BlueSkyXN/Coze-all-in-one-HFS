#!/usr/bin/env bash
set -euo pipefail

export DATA_DIR="${DATA_DIR:-/data/coze}"

mkdir -p \
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
  "$DATA_DIR/nginx/scgi_temp"

/opt/coze-hfs/bin/render-env.sh
/opt/coze-hfs/bin/mysql-init.sh

exec /usr/bin/supervisord -c /opt/coze-hfs/conf/supervisord.conf
