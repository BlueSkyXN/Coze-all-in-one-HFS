#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-coze-studio-hfs-poc:local}"
COZE_SERVER_TAG="${COZE_SERVER_TAG:-0.5.1}"
COZE_WEB_TAG="${COZE_WEB_TAG:-0.5.1}"
COZE_GIT_REF="${COZE_GIT_REF:-v0.5.1}"

docker build \
  --build-arg COZE_SERVER_TAG="$COZE_SERVER_TAG" \
  --build-arg COZE_WEB_TAG="$COZE_WEB_TAG" \
  --build-arg COZE_GIT_REF="$COZE_GIT_REF" \
  -t "$IMAGE_NAME" \
  .
