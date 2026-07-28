#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1090
source "${COZE_ENV_FILE:-/app/runtime/.env}"

/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 "${MYSQL_PORT:-3306}" 180
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 6379 120
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 4222 120

if [ "${ENABLE_LOCAL_MINIO:-1}" = "1" ]; then
  /opt/coze-hfs/bin/wait-for.sh 127.0.0.1 9000 180
fi

/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 9200 300
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 19530 300
/opt/coze-hfs/bin/wait-for.sh 127.0.0.1 9091 300

# TCP listen is not enough on slower volume IO: the Milvus proxy can accept
# connections before it is ready, and Coze panics instead of retrying.
echo "[coze-server] waiting for Milvus proxy readiness"
milvus_ready=false
for _ in $(seq 1 300); do
  if curl -fsS "http://127.0.0.1:9091/healthz" >/dev/null 2>&1; then
    milvus_ready=true
    break
  fi
  sleep 1
done
if [ "$milvus_ready" != "true" ]; then
  echo "[coze-server] Milvus proxy did not become ready within 300s" >&2
  exit 1
fi

cd /app/runtime
exec /app/runtime/opencoze
