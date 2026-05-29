#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1091
source "${COZE_ENV_FILE:-/app/.env}"

/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 "${MYSQL_PORT:-3306}" 180
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 6379 120
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 4222 120

if [ "${ENABLE_LOCAL_MINIO:-1}" = "1" ]; then
  /opt/coze-hfs/bin/wait-for.sh 127.0.0.1 9000 120 || true
fi

cd /app
exec /app/opencoze
