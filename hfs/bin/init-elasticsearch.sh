#!/usr/bin/env bash
set -euo pipefail

ES_ADDR="${ES_ADDR:-http://127.0.0.1:9200}"
INDEX_DIR="${ES_INDEX_TEMPLATE_DIR:-/opt/coze-hfs/elasticsearch/es_index_schema}"

for i in $(seq 1 120); do
  if curl -fsS "${ES_ADDR}/_cat/health" >/dev/null 2>&1; then
    break
  fi
  echo "[elasticsearch-init] waiting for Elasticsearch... ($i/120)"
  sleep 2
  if [ "$i" = "120" ]; then
    echo "[elasticsearch-init] Elasticsearch did not become ready" >&2
    exit 1
  fi
done

if ! curl -fsS "${ES_ADDR}/_cat/plugins" | grep -q "analysis-smartcn"; then
  echo "[elasticsearch-init] analysis-smartcn plugin is not loaded" >&2
  exit 1
fi

for template_file in "$INDEX_DIR"/*.index-template.json; do
  [ -f "$template_file" ] || continue
  template_name="$(basename "$template_file" | sed 's/\.index-template\.json$//')"
  if ! curl -fsS -I "${ES_ADDR}/_index_template/${template_name}" >/dev/null 2>&1; then
    echo "[elasticsearch-init] registering template $template_name"
    curl -fsS -X PUT "${ES_ADDR}/_index_template/${template_name}" \
      -H "Content-Type: application/json" \
      -d @"$template_file" >/dev/null
  fi
  if ! curl -fsS "${ES_ADDR}/_cat/indices/${template_name}" >/dev/null 2>&1; then
    echo "[elasticsearch-init] creating index $template_name"
    curl -fsS -X PUT "${ES_ADDR}/${template_name}" -H "Content-Type: application/json" >/dev/null
    curl -fsS -X PUT "${ES_ADDR}/${template_name}/_settings" \
      -H "Content-Type: application/json" \
      -d '{"index":{"refresh_interval":"10ms"}}' >/dev/null
  fi
done

touch /tmp/es_init_complete
echo "[elasticsearch-init] complete"
