#!/usr/bin/env bash
set -euo pipefail

# shellcheck disable=SC1090
source "${COZE_ENV_FILE:-/app/.env}"

DATA_DIR="${DATA_DIR:-/data/coze}"
MYSQL_DATA_DIR="${MYSQL_DATA_DIR:-$DATA_DIR/mysql}"
MYSQL_SOCKET="${MYSQL_SOCKET:-$DATA_DIR/run/mysql.sock}"
MYSQL_PID_FILE="${MYSQL_PID_FILE:-$DATA_DIR/run/mariadb.pid}"

exec mariadbd \
  --datadir="$MYSQL_DATA_DIR" \
  --socket="$MYSQL_SOCKET" \
  --pid-file="$MYSQL_PID_FILE" \
  --port="${MYSQL_PORT:-3306}" \
  --bind-address="127.0.0.1" \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci \
  --skip-networking=0
