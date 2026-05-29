#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-coze-studio-hfs-poc:local}"
COZE_SERVER_TAG="${COZE_SERVER_TAG:-0.5.1}"
COZE_WEB_TAG="${COZE_WEB_TAG:-0.5.1}"
COZE_GIT_REF="${COZE_GIT_REF:-v0.5.1}"
ELASTICSEARCH_IMAGE="${ELASTICSEARCH_IMAGE:-bitnamilegacy/elasticsearch:8.18.0}"
ETCD_IMAGE="${ETCD_IMAGE:-bitnamilegacy/etcd:3.5}"
MILVUS_IMAGE="${MILVUS_IMAGE:-milvusdb/milvus:v2.5.10}"
DENO_VERSION="${DENO_VERSION:-2.4.5}"
ATLAS_INSTALL_URL="${ATLAS_INSTALL_URL:-https://atlasgo.sh}"
INSTALL_ATLAS="${INSTALL_ATLAS:-true}"

build_args=(
  --build-arg COZE_SERVER_TAG="$COZE_SERVER_TAG"
  --build-arg COZE_WEB_TAG="$COZE_WEB_TAG"
  --build-arg COZE_GIT_REF="$COZE_GIT_REF"
  --build-arg ELASTICSEARCH_IMAGE="$ELASTICSEARCH_IMAGE"
  --build-arg ETCD_IMAGE="$ETCD_IMAGE"
  --build-arg MILVUS_IMAGE="$MILVUS_IMAGE"
  --build-arg DENO_VERSION="$DENO_VERSION"
  --build-arg ATLAS_INSTALL_URL="$ATLAS_INSTALL_URL"
  --build-arg INSTALL_ATLAS="$INSTALL_ATLAS"
)

for key in \
  DENO_SHA256_AMD64 \
  DENO_SHA256_ARM64 \
  ATLAS_INSTALL_SHA256 \
  MINIO_SHA256_AMD64 \
  MINIO_SHA256_ARM64 \
  MC_SHA256_AMD64 \
  MC_SHA256_ARM64; do
  if [ -n "${!key:-}" ]; then
    build_args+=(--build-arg "$key=${!key}")
  fi
done

docker build \
  "${build_args[@]}" \
  -t "$IMAGE_NAME" \
  .
