#!/usr/bin/env bash
set -euo pipefail

# Load generated Coze env.
# shellcheck disable=SC1091
source "${COZE_ENV_FILE:-/app/.env}"

DATA_DIR="${DATA_DIR:-/data/coze}"
MYSQL_DATA_DIR="${MYSQL_DATA_DIR:-$DATA_DIR/mysql}"
MYSQL_SOCKET="${MYSQL_SOCKET:-$DATA_DIR/run/mysql-init.sock}"
MYSQL_PID_FILE="${MYSQL_PID_FILE:-$DATA_DIR/run/mysql-init.pid}"
SCHEMA_SQL="${SCHEMA_SQL:-/opt/coze/bootstrap/schema.sql}"
SCHEMA_HCL="${SCHEMA_HCL:-/opt/coze/bootstrap/opencoze_latest_schema.hcl}"
BOOTSTRAP_MARKER="$MYSQL_DATA_DIR/.coze_bootstrap_done"

mkdir -p "$MYSQL_DATA_DIR" "$DATA_DIR/run" "$DATA_DIR/logs"

if [ -f "$BOOTSTRAP_MARKER" ]; then
  echo "[mysql-init] existing database bootstrap marker found; skipping init"
  exit 0
fi

if [ ! -d "$MYSQL_DATA_DIR/mysql" ]; then
  echo "[mysql-init] initializing MariaDB datadir at $MYSQL_DATA_DIR"
  mariadb-install-db \
    --datadir="$MYSQL_DATA_DIR" \
    --auth-root-authentication-method=normal \
    --user="$(id -un)" \
    --skip-test-db
fi

echo "[mysql-init] starting temporary MariaDB for bootstrap"
mariadbd \
  --datadir="$MYSQL_DATA_DIR" \
  --socket="$MYSQL_SOCKET" \
  --pid-file="$MYSQL_PID_FILE" \
  --port="${MYSQL_PORT:-3306}" \
  --bind-address="127.0.0.1" \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci \
  --skip-networking=0 &
MYSQL_TMP_PID=$!

cleanup() {
  if kill -0 "$MYSQL_TMP_PID" >/dev/null 2>&1; then
    mysqladmin --protocol=socket --socket="$MYSQL_SOCKET" -uroot shutdown >/dev/null 2>&1 || kill "$MYSQL_TMP_PID" >/dev/null 2>&1 || true
  fi
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
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'%' IDENTIFIED BY '${MYSQL_PASSWORD}';
CREATE USER IF NOT EXISTS '${MYSQL_USER}'@'localhost' IDENTIFIED BY '${MYSQL_PASSWORD}';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'%';
GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}\`.* TO '${MYSQL_USER}'@'localhost';
FLUSH PRIVILEGES;
SQL

if [ -s "$SCHEMA_SQL" ]; then
  echo "[mysql-init] importing Coze schema.sql"
  mysql_root "$MYSQL_DATABASE" < "$SCHEMA_SQL"
else
  echo "[mysql-init] schema.sql not found or empty at $SCHEMA_SQL" >&2
  exit 1
fi

if command -v atlas >/dev/null 2>&1 && [ -s "$SCHEMA_HCL" ]; then
  echo "[mysql-init] running Atlas schema apply"
  atlas schema apply \
    -u "mysql://${MYSQL_USER}:${MYSQL_PASSWORD}@127.0.0.1:${MYSQL_PORT}/${MYSQL_DATABASE}" \
    --to "file://${SCHEMA_HCL}" \
    --exclude "atlas_schema_revisions,table_*" \
    --auto-approve || echo "[mysql-init] Atlas apply failed; continuing after schema.sql import"
else
  echo "[mysql-init] Atlas not available or schema HCL missing; skipping Atlas apply"
fi

touch "$BOOTSTRAP_MARKER"
echo "[mysql-init] bootstrap complete"
