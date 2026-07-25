#!/usr/bin/env bash
set -euo pipefail

DATA_DIR="${DATA_DIR:-/data/coze}"
ES_LOCAL_DIR="${ES_LOCAL_DIR:-/var/lib/elasticsearch-data}"
export ES_JAVA_OPTS="${ES_JAVA_OPTS:--Xms512m -Xmx512m}"
export ELASTICSEARCH_HEAP_SIZE="${ELASTICSEARCH_HEAP_SIZE:-512m}"

# HF bucket volumes cannot chown or hold Lucene native locks; keep the ES
# node data on container-local storage and treat indices as rebuildable.
mkdir -p "$ES_LOCAL_DIR"
if [ ! -L /bitnami/elasticsearch ]; then
  rm -rf /bitnami/elasticsearch
  ln -s "$ES_LOCAL_DIR" /bitnami/elasticsearch
fi
mkdir -p /bitnami/elasticsearch/data
chown -R 1001:0 /bitnami/elasticsearch /opt/bitnami/elasticsearch/config || true

/opt/coze-hfs/bin/init-elasticsearch.sh &

exec /opt/bitnami/scripts/elasticsearch/entrypoint.sh /opt/bitnami/scripts/elasticsearch/run.sh
