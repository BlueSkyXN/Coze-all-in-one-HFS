#!/usr/bin/env bash
# Validate the repository-local HFS v2 hybrid contract without Docker or network.
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

errors=0

fail() {
  printf 'FAIL hfs-contract: %s\n' "$1" >&2
  errors=$((errors + 1))
}

require_file() {
  local path="$1"
  [ -f "$path" ] || fail "missing required file: $path"
}

require_grep() {
  local pattern="$1"
  local path="$2"
  local message="$3"
  grep -Eq "$pattern" "$path" || fail "$message"
}

require_ignore_pattern() {
  local pattern="$1"
  grep -qxF "$pattern" .dockerignore || fail ".dockerignore must include: $pattern"
}

frontmatter_value() {
  local key="$1"
  awk -v key="$key" '
    NR == 1 && $0 == "---" { in_yaml = 1; next }
    in_yaml && $0 == "---" { exit }
    in_yaml {
      split($0, parts, ":")
      if (parts[1] == key) {
        sub("^[^:]+:[[:space:]]*", "", $0)
        print $0
      }
    }
  ' README.md | tail -n 1
}

required_files=(
  README.md
  Dockerfile
  hfs-dev.toml
  hfs-dev.candidate.toml
  .env.example
  AGENTS.md
  hfs/AGENTS.md
  hfs/bin/entrypoint.sh
  hfs/bin/bootstrap_runtime.py
  hfs/bin/healthcheck.sh
  hfs/bin/ops_service.py
  hfs/bin/admin_service.py
  hfs/bin/run-admin-service.sh
  hfs/conf/nginx.conf
  hfs/conf/supervisord.conf
  hfs/tests/test_bootstrap_runtime.py
  scripts/verify-runtime-artifacts.py
  scripts/admin-smoke.sh
  scripts/hf-space-smoke.sh
  scripts/static-check.sh
  .github/workflows/build-pinned-coze.yml
  docs/hfs-alignment.md
  docs/release-checklist.md
)
for path in "${required_files[@]}"; do
  require_file "$path"
done

require_grep 'tar --dereference --hard-dereference --sort=name' .github/workflows/build-pinned-coze.yml \
  'runtime artifact producer must flatten image links before safe-tar validation'

python3 - "$repo_root" <<'PY'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest = tomllib.loads((root / "hfs-dev.toml").read_text(encoding="utf-8"))
candidate = tomllib.loads((root / "hfs-dev.candidate.toml").read_text(encoding="utf-8"))
expected = {
    "standard": "2.0",
    "project": "coze-all-in-one-hfs",
    "space": "BlueSkyXN/Coze-all-in-one-HFS",
    "sovereignty": "port",
    "lane": "artifact",
    "version_source": "commit",
    "dist_bucket": "hfs-dist",
}
required_secrets = {"COZE_RUNTIME_DOWNLOAD_TOKEN", "OPS_TOKEN", "ADMIN_TOKEN"}
required_variables = {"COZE_RUNTIME_MANIFEST_URI", "PERSISTENCE_REQUIRED", "CODE_RUNNER_TYPE", "MODEL_PROTOCOL_0", "S3_ENDPOINT"}
failures: list[str] = []
if candidate.get("space") != "BlueSkyXN/Coze-all-in-one-HFS-v2-candidate":
    failures.append("candidate manifest must target BlueSkyXN/Coze-all-in-one-HFS-v2-candidate")
for key in ("standard", "project", "sovereignty", "lane", "version_source", "local_only", "secrets", "variables", "dist_bucket", "seed_file", "other_objects", "deviations"):
    if candidate.get(key) != manifest.get(key):
        failures.append(f"candidate manifest {key} must match production manifest")
for key, value in expected.items():
    if manifest.get(key) != value:
        failures.append(f"hfs-dev.toml {key} must be {value!r}, got {manifest.get(key)!r}")
for legacy in ("schema_version", "pattern", "runtime_mode", "release_pins", "required_files"):
    if legacy in manifest:
        failures.append(f"hfs-dev.toml must not keep legacy field: {legacy}")
for field in ("local_only", "secrets", "variables", "deviations"):
    value = manifest.get(field)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        failures.append(f"hfs-dev.toml {field} must be a non-empty string array")
secrets = set(manifest.get("secrets", []))
variables = set(manifest.get("variables", []))
if not required_secrets <= secrets:
    failures.append("hfs-dev.toml secrets must register runtime download and ops/admin token names")
if not required_variables <= variables:
    failures.append("hfs-dev.toml variables must register runtime manifest and policy names")
if secrets & variables:
    failures.append("hfs-dev.toml secrets and variables must not overlap")
if not any(entry.startswith("hybrid-wrapper =") for entry in manifest.get("deviations", [])):
    failures.append("hfs-dev.toml must document the hybrid wrapper deviation")
if not any(entry.startswith("business-image =") for entry in manifest.get("deviations", [])):
    failures.append("hfs-dev.toml must document retained infrastructure images")
if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}", file=sys.stderr)
    raise SystemExit(1)
PY

sdk=$(frontmatter_value sdk)
app_port=$(frontmatter_value app_port)
[ "$sdk" = "docker" ] || fail "README.md frontmatter must set sdk: docker"
[ "$app_port" = "7860" ] || fail "README.md frontmatter must set app_port: 7860"
[ "$(awk 'toupper($1) == "EXPOSE" { print $2; exit }' Dockerfile)" = "$app_port" ] || fail "Dockerfile EXPOSE must match README app_port"
[ "$(awk '$1 == "listen" { value=$2; gsub(";", "", value); split(value, parts, ":"); print parts[length(parts)]; exit }' hfs/conf/nginx.conf)" = "$app_port" ] || fail "nginx listen must match README app_port"

if grep -Eq '^FROM cozedev/coze-studio-(server|web):' Dockerfile || grep -Eq '^COPY --from=coze-(server|web)' Dockerfile; then
  fail "Dockerfile must not assemble Coze server/web from business images"
fi
require_grep '^ARG COZE_SOURCE_COMMIT=[0-9a-f]{40}$' Dockerfile "Dockerfile must retain one immutable Coze product source commit"
require_grep '^ARG COZE_RELEASE_TAG=v0\.5\.1$' Dockerfile "Dockerfile may retain the Coze release tag only as a label"
require_grep 'coze-studio/\$\{COZE_SOURCE_COMMIT\}/docker/atlas/opencoze_latest_schema\.hcl' Dockerfile "Atlas schema must bind to the canonical Coze source commit"
for image_arg in ELASTICSEARCH_IMAGE ETCD_IMAGE MILVUS_IMAGE; do
  require_grep "^ARG ${image_arg}=[^ ]+@sha256:[0-9a-f]{64}$" Dockerfile "Dockerfile must keep ${image_arg} digest-pinned"
done
require_grep '^FROM \$\{ETCD_IMAGE\} AS etcd$' Dockerfile "Dockerfile must select etcd from its digest-pinned input"
require_grep '^FROM \$\{MILVUS_IMAGE\} AS milvus$' Dockerfile "Dockerfile must select Milvus from its digest-pinned input"
require_grep '^FROM \$\{ELASTICSEARCH_IMAGE\}$' Dockerfile "Dockerfile must select Elasticsearch from its digest-pinned input"
for checksum_arg in DENO_SHA256_AMD64 DENO_SHA256_ARM64 ATLAS_SHA256_AMD64 ATLAS_SHA256_ARM64 MINIO_SHA256_AMD64 MINIO_SHA256_ARM64 MC_SHA256_AMD64 MC_SHA256_ARM64; do
  require_grep "^ARG ${checksum_arg}=[0-9a-f]{64}$" Dockerfile "Dockerfile must pin ${checksum_arg}"
done
if grep -Eq 'curl .*\|[[:space:]]*sh' Dockerfile; then
  fail "Dockerfile must not pipe remote curl output directly into sh"
fi
require_grep '^      /app \\$' Dockerfile "Dockerfile must create the artifact destination before ownership checks"

require_grep 'bootstrap_runtime\.py' hfs/bin/entrypoint.sh "entrypoint must bootstrap artifacts before Supervisor"
require_grep 'COZE_RUNTIME_MANIFEST_URI' hfs/bin/bootstrap_runtime.py "runtime bootstrap must require a manifest URL"
require_grep 'source_kind must be commit' hfs/bin/bootstrap_runtime.py "runtime bootstrap must require immutable commit provenance"
require_grep 'expected_build_source_name' hfs/bin/bootstrap_runtime.py "runtime bootstrap must use commit-named build provenance"
require_grep 'checksum does not match' hfs/bin/bootstrap_runtime.py "runtime bootstrap must verify artifact checksums"
require_grep 'MAX_UNPACKED_BYTES' hfs/bin/bootstrap_runtime.py "runtime bootstrap must bound archive extraction"
require_grep 'install_runtime_components' hfs/bin/bootstrap_runtime.py "runtime bootstrap must stage the server and web pair together"
require_grep '\.xethub\.hf\.co' hfs/bin/bootstrap_runtime.py "runtime bootstrap may follow only an HF Xet download redirect"
require_grep 'bearer-authenticated runtime downloads must use huggingface\.co' hfs/bin/bootstrap_runtime.py "runtime bearer tokens must stay scoped to Hugging Face"
require_grep 'old /app|cache|directory scan' docs/hfs-alignment.md "docs must prohibit runtime fallback paths"
require_grep 'artifact-first' docs/release-checklist.md "release checklist must require manifest-last publication"
require_grep 'workflow_dispatch:' .github/workflows/build-pinned-coze.yml "artifact workflow must be manual"
require_grep 'confirmed' .github/workflows/build-pinned-coze.yml "artifact workflow must require explicit confirmation"
require_grep 'readback' .github/workflows/build-pinned-coze.yml "artifact workflow must perform post-write readback"
require_grep 'BUILD_SOURCE-\$\{UPSTREAM_REF\}\.json' .github/workflows/build-pinned-coze.yml "artifact workflow must publish commit-named build provenance"
require_grep 'targetCommitish' .github/workflows/build-pinned-coze.yml "release publication must read back its target commit"
require_grep 'verify-runtime-artifacts\.py' .github/workflows/build-pinned-coze.yml "artifact workflow must locally verify its output"
require_grep 'actions/checkout@[0-9a-f]{40}' .github/workflows/build-pinned-coze.yml "artifact workflow must pin checkout by immutable revision"
require_grep 'actions/upload-artifact@[0-9a-f]{40}' .github/workflows/build-pinned-coze.yml "artifact workflow must pin artifact upload by immutable revision"
require_grep 'actions/download-artifact@[0-9a-f]{40}' .github/workflows/build-pinned-coze.yml "artifact workflow must pin artifact download by immutable revision"
require_grep 'CANONICAL_SOURCE_COMMIT: 22275b1c2661d35344a7493cffe401e8cc61cf8e' .github/workflows/build-pinned-coze.yml "artifact workflow must bind server and web builds to the canonical Coze source commit"
require_grep 'huggingface_hub==1\.5\.0' .github/workflows/build-pinned-coze.yml "artifact publish jobs must install a pinned Hugging Face CLI"

require_grep '/nginx-health' scripts/hf-space-smoke.sh "smoke must check /nginx-health"
require_grep '/_ops/healthz' scripts/hf-space-smoke.sh "smoke must check /_ops/healthz"
require_grep 'ops-version.*_ops/version' scripts/hf-space-smoke.sh "smoke must check protected runtime provenance"
require_grep '/_admin/' scripts/hf-space-smoke.sh "smoke must check default /_admin behavior"
require_grep '/sign' scripts/hf-space-smoke.sh "smoke must check /sign"
require_grep 'tokens are not accepted in URLs' hfs/bin/ops_service.py "ops dashboard must reject query-string tokens"
require_grep 'runtime_provenance' hfs/bin/ops_service.py "ops version payload must expose safe runtime provenance"
require_grep 'runtime_provenance.*runtime_provenance_payload' hfs/bin/ops_service.py "canonical health must require bootstrap provenance"
require_grep 'emit CODE_RUNNER_TYPE "sandbox"' hfs/bin/render-env.sh "Coze must explicitly use the sandbox code runner"
require_grep 'RUN_DIR="\$\{RUN_DIR:-/run/coze\}"' hfs/bin/mysql-init.sh "mysql sockets must stay off the data volume"
require_grep '^file=/run/coze/supervisor\.sock' hfs/conf/supervisord.conf "supervisor socket must stay off the data volume"
require_grep '^pid /run/coze/nginx\.pid;' hfs/conf/nginx.conf "nginx pid must stay off the data volume"
require_grep 'location \^~ /api/admin/' hfs/conf/nginx.conf "nginx must block the upstream fail-open admin API"
require_grep 'Content-Security-Policy ".*frame-ancestors https://huggingface\.co https://\*\.hf\.space" always' hfs/conf/nginx.conf "nginx must retain Hugging Face iframe CSP"

require_ignore_pattern '.env'
require_ignore_pattern '.env.*'
require_ignore_pattern '/local/'
require_ignore_pattern '**/local/'
require_ignore_pattern '*.secret'
require_ignore_pattern '*.key'
require_ignore_pattern '*.pem'
git check-ignore -q .env
git check-ignore -q .env.local
git check-ignore -q local/coze-studio-hfs-poc/README.md

if [ "$errors" -ne 0 ]; then
  exit 1
fi
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s hfs/tests -p 'test_bootstrap_runtime.py'
printf 'hfs v2 hybrid contract checks passed\n'
