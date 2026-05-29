#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-coze-studio-hfs-poc:local}"
CONTAINER_NAME="${CONTAINER_NAME:-coze-studio-hfs-poc}"
DATA_DIR="${DATA_DIR:-$PWD/.data}"

mkdir -p "$DATA_DIR"

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

docker run --rm \
  --name "$CONTAINER_NAME" \
  -p 7860:7860 \
  -v "$DATA_DIR:/data/coze" \
  -e COZE_PUBLIC_URL="http://localhost:7860" \
  -e DISABLE_USER_REGISTRATION="false" \
  "$IMAGE_NAME"
