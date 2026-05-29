#!/usr/bin/env bash
set -euo pipefail

required=(
  README.md
  Dockerfile
  hfs-dev.toml
  hfs/bin/entrypoint.sh
  hfs/bin/render-env.sh
  hfs/bin/ops_service.py
  hfs/conf/nginx.conf
  hfs/conf/supervisord.conf
  docs/env-reference.md
)

for f in "${required[@]}"; do
  if [ ! -e "$f" ]; then
    echo "missing required file: $f" >&2
    exit 1
  fi
done

grep -q '^sdk: docker$' README.md
grep -q '^app_port: 7860$' README.md
grep -q '^EXPOSE 7860$' Dockerfile
grep -q 'canonical_health_endpoint = "/_ops/healthz"' hfs-dev.toml

find hfs scripts -type f -name '*.sh' -print0 | while IFS= read -r -d '' f; do
  echo "bash -n $f"
  bash -n "$f"
done

python3 -m py_compile hfs/bin/ops_service.py

if git ls-files | grep -q '\.DS_Store$'; then
  echo "tracked .DS_Store files are not allowed" >&2
  exit 1
fi

git check-ignore -q .env.local
git check-ignore -q local/coze-studio-hfs-poc/README.md

echo "static checks passed"
