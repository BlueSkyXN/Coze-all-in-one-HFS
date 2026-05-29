#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data/coze}"
export ES_JAVA_OPTS="${ES_JAVA_OPTS:--Xms512m -Xmx512m}"
export ELASTICSEARCH_HEAP_SIZE="${ELASTICSEARCH_HEAP_SIZE:-512m}"

mkdir -p "$DATA_DIR/elasticsearch"
if [ ! -L /bitnami/elasticsearch ]; then
  rm -rf /bitnami/elasticsearch
  ln -s "$DATA_DIR/elasticsearch" /bitnami/elasticsearch
fi
mkdir -p /bitnami/elasticsearch/data
chown -R 1001:0 /bitnami/elasticsearch /opt/bitnami/elasticsearch/config || true

/opt/coze-hfs/bin/init-elasticsearch.sh &

exec /opt/bitnami/scripts/elasticsearch/entrypoint.sh /opt/bitnami/scripts/elasticsearch/run.sh
