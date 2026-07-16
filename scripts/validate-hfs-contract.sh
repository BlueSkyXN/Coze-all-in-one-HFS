#!/usr/bin/env bash
# shellcheck disable=SC2016
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
  if [ ! -f "$path" ]; then
    fail "missing required file: $path"
  fi
}

require_grep() {
  local pattern="$1"
  local path="$2"
  local message="$3"
  if ! grep -Eq "$pattern" "$path"; then
    fail "$message"
  fi
}

require_ignore_pattern() {
  local pattern="$1"
  if ! grep -qxF "$pattern" .dockerignore; then
    fail ".dockerignore must include: $pattern"
  fi
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
  AGENTS.md
  hfs/AGENTS.md
  hfs/bin/entrypoint.sh
  hfs/bin/healthcheck.sh
  hfs/bin/ops_service.py
  hfs/bin/admin_service.py
  hfs/bin/run-admin-service.sh
  hfs/conf/nginx.conf
  hfs/conf/supervisord.conf
  scripts/admin-smoke.sh
  scripts/hf-space-smoke.sh
  scripts/static-check.sh
  docs/hfs-alignment.md
  docs/release-checklist.md
)

for path in "${required_files[@]}"; do
  require_file "$path"
done

python3 - "$repo_root" <<'PY'
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

root = Path(sys.argv[1])
manifest = tomllib.loads((root / "hfs-dev.toml").read_text(encoding="utf-8"))

expected = {
    "schema_version": 2,
    "standard": "hfs-dev",
    "pattern": "A",
    "runtime_mode": "image-assembly",
    "space_root_mode": "repo-root",
    "hfs_dir": ".",
    "public_port": 7860,
    "canonical_health_endpoint": "/_ops/healthz",
    "release_pin_required": True,
}

expected_pins = {
    "COZE_SERVER_TAG": {
        "type": "image_tag",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_digest": True,
    },
    "COZE_WEB_TAG": {
        "type": "image_tag",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_digest": True,
    },
    "COZE_GIT_REF": {
        "type": "git_ref",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_commit_or_tag": True,
    },
    "ELASTICSEARCH_IMAGE": {
        "type": "image_ref",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_digest": True,
    },
    "ETCD_IMAGE": {
        "type": "image_ref",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_digest": True,
    },
    "MILVUS_IMAGE": {
        "type": "image_ref",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_digest": True,
    },
    "DENO_VERSION": {
        "type": "artifact_version",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_checksum": True,
    },
    "ATLAS_VERSION": {
        "type": "artifact_version",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_checksum": True,
    },
    "MINIO_VERSION": {
        "type": "artifact_version",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_checksum": True,
    },
    "MC_VERSION": {
        "type": "artifact_version",
        "source": "Dockerfile ARG",
        "required_for_release": True,
        "dev_mutable_default_allowed": False,
        "release_requires_checksum": True,
    },
}

failures: list[str] = []
for key, value in expected.items():
    if manifest.get(key) != value:
        failures.append(f"hfs-dev.toml {key} must be {value!r}, got {manifest.get(key)!r}")

if "release_pin_surfaces" in manifest:
    failures.append("hfs-dev.toml v2 must use structured [[release_pins]], not release_pin_surfaces")

release_pins = manifest.get("release_pins")
if not isinstance(release_pins, list) or not release_pins:
    failures.append("hfs-dev.toml release_pins must be a non-empty structured array")
else:
    pins_by_name: dict[str, dict[str, object]] = {}
    for index, pin in enumerate(release_pins, start=1):
        if not isinstance(pin, dict):
            failures.append(f"hfs-dev.toml release_pins[{index}] must be a table")
            continue
        name = pin.get("name")
        if not isinstance(name, str) or not name:
            failures.append(f"hfs-dev.toml release_pins[{index}] must set name")
            continue
        if name in pins_by_name:
            failures.append(f"hfs-dev.toml release_pins duplicate name: {name}")
        pins_by_name[name] = pin

    missing = sorted(set(expected_pins) - set(pins_by_name))
    if missing:
        failures.append("hfs-dev.toml release_pins missing: " + ", ".join(missing))
    unexpected = sorted(set(pins_by_name) - set(expected_pins))
    if unexpected:
        failures.append("hfs-dev.toml release_pins unexpected: " + ", ".join(unexpected))

    for name, expected_pin in expected_pins.items():
        pin = pins_by_name.get(name)
        if not pin:
            continue
        if not isinstance(pin.get("current_dev_default"), str) or not pin.get("current_dev_default"):
            failures.append(f"hfs-dev.toml release_pins {name} must set current_dev_default")
        for key, value in expected_pin.items():
            if pin.get(key) != value:
                failures.append(
                    f"hfs-dev.toml release_pins {name}.{key} must be {value!r}, got {pin.get(key)!r}"
                )

required_files = manifest.get("required_files")
if not isinstance(required_files, list) or not required_files:
    failures.append("hfs-dev.toml required_files must be a non-empty list")
else:
    for rel_path in required_files:
        if not isinstance(rel_path, str) or not (root / rel_path).exists():
            failures.append(f"hfs-dev.toml required file is missing: {rel_path!r}")

if failures:
    for failure in failures:
        print(f"FAIL hfs-contract: {failure}", file=sys.stderr)
    raise SystemExit(1)
PY

sdk=$(frontmatter_value sdk)
app_port=$(frontmatter_value app_port)
if [ "$sdk" != "docker" ]; then
  fail "README.md frontmatter must set sdk: docker"
fi
if [ -z "$app_port" ]; then
  fail "README.md frontmatter must set app_port"
fi

docker_expose=$(awk 'toupper($1) == "EXPOSE" { print $2; exit }' Dockerfile)
nginx_listen=$(awk '
  $1 == "listen" {
    value = $2
    gsub(";", "", value)
    split(value, parts, ":")
    print parts[length(parts)]
    exit
  }
' hfs/conf/nginx.conf)

if [ -n "$app_port" ] && [ "$docker_expose" != "$app_port" ]; then
  fail "Dockerfile EXPOSE ($docker_expose) must match README.md app_port ($app_port)"
fi
if [ -n "$app_port" ] && [ "$nginx_listen" != "$app_port" ]; then
  fail "hfs/conf/nginx.conf listen ($nginx_listen) must match README.md app_port ($app_port)"
fi

if [ -f cloud/hfs/README.md ] || [ -f cloud/hfs/Dockerfile ]; then
  fail "Pattern A repo must keep Space root at repo root, not cloud/hfs/"
fi

require_grep 'Pattern A: HFS Port Repository' docs/hfs-alignment.md \
  "docs/hfs-alignment.md must declare Pattern A"
require_grep 'Runtime mode: image-assembly' docs/hfs-alignment.md \
  "docs/hfs-alignment.md must declare image-assembly runtime mode"
require_grep 'Space root: repo root' docs/hfs-alignment.md \
  "docs/hfs-alignment.md must declare repo root as Space root"

require_grep '^ARG COZE_SERVER_TAG=' Dockerfile \
  "Dockerfile must expose COZE_SERVER_TAG build input"
require_grep '^ARG COZE_WEB_TAG=' Dockerfile \
  "Dockerfile must expose COZE_WEB_TAG build input"
require_grep '^ARG COZE_SERVER_TAG=[^ ]+@sha256:[0-9a-f]{64}$' Dockerfile \
  "Dockerfile default Coze server image must be digest-pinned"
require_grep '^ARG COZE_WEB_TAG=[^ ]+@sha256:[0-9a-f]{64}$' Dockerfile \
  "Dockerfile default Coze web image must be digest-pinned"
require_grep '^ARG COZE_GIT_REF=' Dockerfile \
  "Dockerfile must expose COZE_GIT_REF build input"
require_grep '^ARG ELASTICSEARCH_IMAGE=' Dockerfile \
  "Dockerfile must expose ELASTICSEARCH_IMAGE build input"
require_grep '^ARG ELASTICSEARCH_IMAGE=[^ ]+@sha256:[0-9a-f]{64}$' Dockerfile \
  "Dockerfile default Elasticsearch image must be digest-pinned"
require_grep '^ARG ETCD_IMAGE=' Dockerfile \
  "Dockerfile must expose ETCD_IMAGE build input"
require_grep '^ARG ETCD_IMAGE=[^ ]+@sha256:[0-9a-f]{64}$' Dockerfile \
  "Dockerfile default etcd image must be digest-pinned"
require_grep '^ARG MILVUS_IMAGE=' Dockerfile \
  "Dockerfile must expose MILVUS_IMAGE build input"
require_grep '^ARG MILVUS_IMAGE=[^ ]+@sha256:[0-9a-f]{64}$' Dockerfile \
  "Dockerfile default Milvus image must be digest-pinned"
require_grep '^ARG DENO_VERSION=' Dockerfile \
  "Dockerfile must expose DENO_VERSION build input"
require_grep '^ARG DENO_SHA256_AMD64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the Deno amd64 checksum"
require_grep '^ARG DENO_SHA256_ARM64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the Deno arm64 checksum"
require_grep '^ARG ATLAS_VERSION=' Dockerfile \
  "Dockerfile must expose ATLAS_VERSION build input"
require_grep '^ARG ATLAS_SHA256_AMD64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the Atlas amd64 checksum"
require_grep '^ARG ATLAS_SHA256_ARM64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the Atlas arm64 checksum"
require_grep '^ARG MINIO_VERSION=' Dockerfile \
  "Dockerfile must expose MINIO_VERSION build input"
require_grep '^ARG MINIO_SHA256_AMD64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the MinIO amd64 checksum"
require_grep '^ARG MINIO_SHA256_ARM64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the MinIO arm64 checksum"
require_grep '^ARG MC_VERSION=' Dockerfile \
  "Dockerfile must expose MC_VERSION build input"
require_grep '^ARG MC_SHA256_AMD64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the MinIO client amd64 checksum"
require_grep '^ARG MC_SHA256_ARM64=[0-9a-f]{64}$' Dockerfile \
  "Dockerfile must pin the MinIO client arm64 checksum"
require_grep '^FROM cozedev/coze-studio-server:\$\{COZE_SERVER_TAG\} AS coze-server$' Dockerfile \
  "Dockerfile must select server image from COZE_SERVER_TAG"
require_grep '^FROM cozedev/coze-studio-web:\$\{COZE_WEB_TAG\} AS coze-web$' Dockerfile \
  "Dockerfile must select web image from COZE_WEB_TAG"
require_grep '^FROM \$\{ETCD_IMAGE\} AS etcd$' Dockerfile \
  "Dockerfile must select etcd image from ETCD_IMAGE"
require_grep '^FROM \$\{MILVUS_IMAGE\} AS milvus$' Dockerfile \
  "Dockerfile must select Milvus image from MILVUS_IMAGE"
require_grep '^FROM \$\{ELASTICSEARCH_IMAGE\}$' Dockerfile \
  "Dockerfile must select runtime image from ELASTICSEARCH_IMAGE"
require_grep 'denoland/deno/releases/download/v\$\{DENO_VERSION\}' Dockerfile \
  "Dockerfile must select Deno version from DENO_VERSION"
require_grep 'verify_sha256 "\$deno_sha" /tmp/deno\.zip' Dockerfile \
  "Dockerfile must verify Deno checksum when provided"
require_grep 'atlas-community-linux-\$\{atlas_arch\}-\$\{ATLAS_VERSION\}' Dockerfile \
  "Dockerfile must select the pinned Atlas version"
require_grep 'verify_sha256 "\$atlas_sha" /usr/local/bin/atlas' Dockerfile \
  "Dockerfile must verify the Atlas binary checksum"
require_grep 'dl\.min\.io/server/minio/release/linux-\$\{minio_arch\}/archive/minio\.\$\{MINIO_VERSION\}' Dockerfile \
  "Dockerfile must select the pinned MinIO version"
require_grep 'dl\.min\.io/client/mc/release/linux-\$\{minio_arch\}/archive/mc\.\$\{MC_VERSION\}' Dockerfile \
  "Dockerfile must select the pinned MinIO client version"
require_grep 'verify_sha256 "\$minio_sha" /usr/local/bin/minio' Dockerfile \
  "Dockerfile must verify MinIO server checksum when provided"
require_grep 'verify_sha256 "\$mc_sha" /usr/local/bin/mc' Dockerfile \
  "Dockerfile must verify MinIO client checksum when provided"
if grep -Eq 'curl .*\|[[:space:]]*sh' Dockerfile; then
  fail "Dockerfile must not pipe remote curl output directly into sh"
fi

require_grep '/nginx-health' scripts/hf-space-smoke.sh \
  "smoke must check /nginx-health"
require_grep '/_ops/healthz' scripts/hf-space-smoke.sh \
  "smoke must check /_ops/healthz"
require_grep '/_admin/' scripts/hf-space-smoke.sh \
  "smoke must check default /_admin behavior"
require_grep '/sign' scripts/hf-space-smoke.sh \
  "smoke must check /sign"
require_grep 'x-frame-options' scripts/hf-space-smoke.sh \
  "smoke must reject X-Frame-Options on web entry"
require_grep 'status.*ok|ops status is not ok' scripts/hf-space-smoke.sh \
  "smoke must assert ops JSON status"
require_grep 'code runner is not sandbox' scripts/hf-space-smoke.sh \
  "smoke must assert the live sandbox policy"
require_grep 'ops-query-token-rejected' scripts/hf-space-smoke.sh \
  "smoke must reject tokens supplied in URLs"
require_grep 'upstream-admin-api-blocked' scripts/hf-space-smoke.sh \
  "smoke must verify the Coze v0.5.1 admin API guard"

require_grep 'location /_ops/' hfs/conf/nginx.conf \
  "nginx must expose /_ops/ control-plane route"
require_grep 'proxy_pass http://127\.0\.0\.1:8081/' hfs/conf/nginx.conf \
  "nginx must proxy /_ops/ to ops service"
require_grep 'location /_admin/' hfs/conf/nginx.conf \
  "nginx must expose /_admin/ control-plane route"
require_grep 'proxy_pass http://127\.0\.0\.1:8082/' hfs/conf/nginx.conf \
  "nginx must proxy /_admin/ to admin service"
require_grep '\[unix_http_server\]' hfs/conf/supervisord.conf \
  "supervisor must expose local unix control socket"
require_grep 'chmod=0700' hfs/conf/supervisord.conf \
  "supervisor control socket must be owner-only"
require_grep 'chown=cozeadmin:cozeadmin' hfs/conf/supervisord.conf \
  "supervisor control socket must be isolated from the Coze runtime user"
require_grep '\[program:admin-service\]' hfs/conf/supervisord.conf \
  "supervisor must run admin-service"
require_grep 'user=cozeadmin' hfs/conf/supervisord.conf \
  "admin service must run as the dedicated cozeadmin user"
require_grep 'ADMIN_ENABLED.*false|admin_enabled\(\).*false' hfs/bin/admin_service.py \
  "admin service must be default-off"
require_grep 'ALLOWED_RESTART_SERVICES' hfs/bin/admin_service.py \
  "admin service must use a restart whitelist"
require_grep 'OPS_TOKEN' hfs/bin/ops_service.py \
  "ops dashboard must be token protected"
require_grep 'tokens are not accepted in URLs' hfs/bin/ops_service.py \
  "ops dashboard must reject query-string tokens"
require_grep 'emit CODE_RUNNER_TYPE "sandbox"' hfs/bin/render-env.sh \
  "Coze v0.5.1 must explicitly use the sandbox code runner"
require_grep 'location \^~ /api/admin/' hfs/conf/nginx.conf \
  "nginx must block the fail-open Coze v0.5.1 admin API"
require_grep 'admin-disabled-root' scripts/admin-smoke.sh \
  "admin smoke must verify default disabled behavior"
require_grep 'Content-Security-Policy ".*frame-ancestors https://huggingface\.co https://\*\.hf\.space" always' hfs/conf/nginx.conf \
  "nginx must emit frame-ancestors CSP for Hugging Face iframe embedding"

require_ignore_pattern ".env.local"
require_ignore_pattern "/local/"
require_ignore_pattern "**/local/"
require_ignore_pattern "*.secret"
require_ignore_pattern "*.key"
require_ignore_pattern "*.pem"

if [ "$errors" -ne 0 ]; then
  exit 1
fi

echo "hfs contract checks passed"
