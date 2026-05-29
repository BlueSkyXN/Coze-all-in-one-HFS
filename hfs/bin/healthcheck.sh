#!/usr/bin/env bash
set -euo pipefail

curl -fsS http://127.0.0.1:7860/_ops/healthz >/dev/null
