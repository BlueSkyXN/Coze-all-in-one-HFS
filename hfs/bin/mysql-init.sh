#!/usr/bin/env bash
set -euo pipefail

# Load generated Coze env.
# shellcheck disable=SC1090
source "${COZE_ENV_FILE:-/app/.env}"

DATA_DIR="${DATA_DIR:-/data/coze}"
MYSQL_DATA_DIR="${MYSQL_DATA_DIR:-$DATA_DIR/mysql}"
MYSQL_SOCKET="${MYSQL_SOCKET:-$DATA_DIR/run/mysql-init.sock}"
MYSQL_PID_FILE="${MYSQL_PID_FILE:-$DATA_DIR/run/mysql-init.pid}"
SCHEMA_SQL="${SCHEMA_SQL:-/opt/coze/bootstrap/schema.sql}"
SCHEMA_HCL="${SCHEMA_HCL:-/opt/coze/bootstrap/opencoze_latest_schema.hcl}"
BOOTSTRAP_MARKER="$MYSQL_DATA_DIR/.coze_bootstrap_done"
SCHEMA_MARKER="${MYSQL_SCHEMA_MARKER:-$MYSQL_DATA_DIR/.coze_schema_sha256}"
MYSQLD_USER="${MYSQLD_USER:-user}"
MYSQL_PORT="${MYSQL_PORT:-3306}"

: "${MYSQL_DATABASE:?MYSQL_DATABASE must be set by render-env.sh}"
: "${MYSQL_USER:?MYSQL_USER must be set by render-env.sh}"
: "${MYSQL_PASSWORD:?MYSQL_PASSWORD must be set by render-env.sh}"
: "${ATLAS_URL:?ATLAS_URL must be set by render-env.sh}"

validate_mysql_identifier() {
  local key="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "[mysql-init] $key may only contain letters, numbers, and underscores" >&2
    exit 1
  fi
}

sql_string_literal() {
  /usr/bin/python3 - "$1" <<'PY'
import sys

value = sys.argv[1].replace("\\", "\\\\").replace("'", "''")
print("'" + value + "'")
PY
}

file_sha256() {
  /usr/bin/python3 - "$1" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
}

validate_mysql_identifier MYSQL_DATABASE "$MYSQL_DATABASE"
validate_mysql_identifier MYSQL_USER "$MYSQL_USER"
MYSQL_PASSWORD_SQL="$(sql_string_literal "$MYSQL_PASSWORD")"

if [ ! -s "$SCHEMA_HCL" ]; then
  echo "[mysql-init] schema HCL not found or empty at $SCHEMA_HCL" >&2
  exit 1
fi
SCHEMA_SHA256="$(file_sha256 "$SCHEMA_HCL")"

mkdir -p "$MYSQL_DATA_DIR" "$DATA_DIR/run" "$DATA_DIR/logs"
if [ "$(id -u)" = "0" ]; then
  chown -R "$MYSQLD_USER:$MYSQLD_USER" "$MYSQL_DATA_DIR" "$DATA_DIR/run" "$DATA_DIR/logs"
fi

IS_NEW_DATABASE=false
if [ ! -d "$MYSQL_DATA_DIR/mysql" ]; then
  IS_NEW_DATABASE=true
fi

if [ "$IS_NEW_DATABASE" = "false" ] && [ -f "$SCHEMA_MARKER" ] && [ "$(tr -d '[:space:]' < "$SCHEMA_MARKER")" = "$SCHEMA_SHA256" ]; then
  echo "[mysql-init] schema fingerprint is current; skipping database bootstrap"
  exit 0
fi

if [ "$IS_NEW_DATABASE" = "true" ]; then
  echo "[mysql-init] initializing MariaDB datadir at $MYSQL_DATA_DIR"
  mariadb-install-db \
    --datadir="$MYSQL_DATA_DIR" \
    --auth-root-authentication-method=normal \
    --user="$MYSQLD_USER" \
    --skip-test-db
fi

echo "[mysql-init] starting temporary MariaDB for bootstrap"
mariadbd \
  --datadir="$MYSQL_DATA_DIR" \
  --socket="$MYSQL_SOCKET" \
  --pid-file="$MYSQL_PID_FILE" \
  --port="$MYSQL_PORT" \
  --bind-address="127.0.0.1" \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci \
  --skip-networking=0 \
  --user="$MYSQLD_USER" &
MYSQL_TMP_PID=$!

cleanup() {
  if kill -0 "$MYSQL_TMP_PID" >/dev/null 2>&1; then
    mysqladmin --protocol=socket --socket="$MYSQL_SOCKET" -uroot shutdown >/dev/null 2>&1 || kill "$MYSQL_TMP_PID" >/dev/null 2>&1 || true
  fi
  wait "$MYSQL_TMP_PID" 2>/dev/null || true
}
trap cleanup EXIT

for i in $(seq 1 90); do
  if mysqladmin --protocol=socket --socket="$MYSQL_SOCKET" -uroot ping --silent >/dev/null 2>&1; then
    break
  fi
  echo "[mysql-init] waiting for temporary MariaDB... ($i/90)"
  sleep 2
  if [ "$i" = "90" ]; then
    echo "[mysql-init] MariaDB did not become ready" >&2
    exit 1
  fi
done

mysql_root() {
  mysql --protocol=socket --socket="$MYSQL_SOCKET" -uroot "$@"
}

echo "[mysql-init] creating database/user"
mysql_root <<SQL
CREATE DATABASE IF NOT EXISTS \`${MYSQL_DATABASE}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'%' IDENTIFIED BY ${MYSQL_PASSWORD_SQL};
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'localhost' IDENTIFIED BY ${MYSQL_PASSWORD_SQL};
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

if [ "$IS_NEW_DATABASE" = "true" ] && [ -s "$SCHEMA_SQL" ]; then
  echo "[mysql-init] importing Coze schema.sql"
  mysql_root "$MYSQL_DATABASE" < "$SCHEMA_SQL"
elif [ "$IS_NEW_DATABASE" = "true" ]; then
  echo "[mysql-init] schema.sql not found or empty at $SCHEMA_SQL" >&2
  exit 1
else
  echo "[mysql-init] existing database detected; skipping initial schema.sql import"
fi

if ! command -v atlas >/dev/null 2>&1; then
  echo "[mysql-init] Atlas is required for schema reconciliation but is unavailable" >&2
  exit 1
fi

echo "[mysql-init] reconciling schema with Atlas"
atlas schema apply \
  -u "$ATLAS_URL" \
  --to "file://${SCHEMA_HCL}" \
  --exclude "atlas_schema_revisions,table_*" \
  --auto-approve

touch "$BOOTSTRAP_MARKER"
SCHEMA_MARKER_TMP="${SCHEMA_MARKER}.tmp.$$"
printf '%s\n' "$SCHEMA_SHA256" > "$SCHEMA_MARKER_TMP"
chmod 600 "$SCHEMA_MARKER_TMP"
mv "$SCHEMA_MARKER_TMP" "$SCHEMA_MARKER"
echo "[mysql-init] bootstrap/migration complete for schema $SCHEMA_SHA256"
