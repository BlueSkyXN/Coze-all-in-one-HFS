#!/usr/bin/env bash
set -euo pipefail

find hfs scripts -type f -name '*.sh' -print0 | while IFS= read -r -d '' f; do
  echo "checking $f"
  bash -n "$f"
done
