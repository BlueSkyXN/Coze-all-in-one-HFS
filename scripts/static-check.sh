#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

check_changed_file_trailing_whitespace() {
  local -a files=()
  local file
  while IFS= read -r -d '' file; do
    [ -f "$file" ] || continue
    files+=("$file")
  done < <(
    git diff --name-only -z --diff-filter=ACMR
    git diff --cached --name-only -z --diff-filter=ACMR
    git ls-files --others --exclude-standard -z
  )

  [ "${#files[@]}" -gt 0 ] || return 0

  local output status
  set +e
  if command -v rg >/dev/null 2>&1; then
    output=$(rg -n '[[:blank:]]$' -- "${files[@]}" 2>&1)
    status=$?
  else
    output=$(grep -n -E '[[:blank:]]$' -- "${files[@]}" 2>&1)
    status=$?
  fi
  set -e

  if [ "$status" -eq 0 ]; then
    printf 'Trailing whitespace found in changed or untracked files:\n%s\n' "$output" >&2
    return 1
  fi
  if [ "$status" -gt 1 ]; then
    printf 'Unable to check trailing whitespace:\n%s\n' "$output" >&2
    return "$status"
  fi
}

required=(
  README.md
  Dockerfile
  hfs-dev.toml
  AGENTS.md
  hfs/AGENTS.md
  hfs/bin/entrypoint.sh
  hfs/bin/render-env.sh
  hfs/bin/ops_service.py
  hfs/bin/admin_service.py
  hfs/bin/run-admin-service.sh
  hfs/conf/nginx.conf
  hfs/conf/supervisord.conf
  docs/env-reference.md
  docs/hfs-alignment.md
  docs/release-checklist.md
  scripts/admin-smoke.sh
  scripts/validate-hfs-contract.sh
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
grep -q '/_admin/' hfs/conf/nginx.conf

scripts/validate-hfs-contract.sh

find hfs scripts -type f -name '*.sh' -print0 | while IFS= read -r -d '' f; do
  echo "bash -n $f"
  bash -n "$f"
done

python3 -m py_compile hfs/bin/ops_service.py hfs/bin/admin_service.py
python3 -m unittest discover -s hfs/tests -p 'test_*.py'
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck hfs/bin/*.sh scripts/*.sh
else
  echo "shellcheck not found; skipping optional shell lint"
fi
git diff --check
check_changed_file_trailing_whitespace

if git ls-files | grep -q '\.DS_Store$'; then
  echo "tracked .DS_Store files are not allowed" >&2
  exit 1
fi

git check-ignore -q .env.local
git check-ignore -q local/coze-studio-hfs-poc/README.md

echo "static checks passed"
