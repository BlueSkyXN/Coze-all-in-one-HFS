import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MYSQL_INIT = ROOT / "hfs" / "bin" / "mysql-init.sh"


class MysqlInitTests(unittest.TestCase):
    def write_stub(self, directory: Path, name: str, body: str) -> None:
        path = directory / name
        path.write_text("#!/usr/bin/env bash\nset -euo pipefail\n" + body, encoding="utf-8")
        path.chmod(0o755)

    def run_mysql_init(
        self,
        root: Path,
        *,
        existing_database: bool,
        schema_marker: str | None = None,
        atlas_exit: int = 0,
    ) -> tuple[subprocess.CompletedProcess[str], Path, Path, str]:
        data_dir = root / "data"
        mysql_dir = data_dir / "mysql"
        fake_bin = root / "bin"
        env_file = root / "coze.env"
        schema_sql = root / "schema.sql"
        schema_hcl = root / "schema.hcl"
        command_log = root / "commands.log"

        fake_bin.mkdir(parents=True)
        mysql_dir.mkdir(parents=True)
        if existing_database:
            (mysql_dir / "mysql").mkdir()
            (mysql_dir / ".coze_bootstrap_done").touch()
        if schema_marker is not None:
            (mysql_dir / ".coze_schema_sha256").write_text(schema_marker + "\n", encoding="utf-8")

        schema_sql.write_text("CREATE TABLE example (id BIGINT PRIMARY KEY);\n", encoding="utf-8")
        schema_hcl.write_text('schema "opencoze" {}\n', encoding="utf-8")
        fingerprint = hashlib.sha256(schema_hcl.read_bytes()).hexdigest()
        env_file.write_text(
            "\n".join(
                [
                    "export MYSQL_DATABASE=opencoze",
                    "export MYSQL_USER=coze",
                    "export MYSQL_PASSWORD=test-password",
                    "export MYSQL_PORT=3306",
                    "export ATLAS_URL='mysql://coze:test-password@127.0.0.1:3306/opencoze?charset=utf8mb4&parseTime=True'",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        self.write_stub(
            fake_bin,
            "mariadb-install-db",
            'printf "mariadb-install-db %s\\n" "$*" >> "$COMMAND_LOG"\nmkdir -p "$MYSQL_DATA_DIR/mysql"\n',
        )
        self.write_stub(fake_bin, "mariadbd", 'printf "mariadbd %s\\n" "$*" >> "$COMMAND_LOG"\n')
        self.write_stub(fake_bin, "mysqladmin", 'printf "mysqladmin %s\\n" "$*" >> "$COMMAND_LOG"\n')
        self.write_stub(
            fake_bin,
            "mysql",
            'printf "mysql %s\\n" "$*" >> "$COMMAND_LOG"\ncat >/dev/null\n',
        )
        self.write_stub(
            fake_bin,
            "atlas",
            'printf "atlas %s\\n" "$*" >> "$COMMAND_LOG"\nexit "${ATLAS_EXIT:-0}"\n',
        )

        env = os.environ.copy()
        env.update(
            {
                "ATLAS_EXIT": str(atlas_exit),
                "COMMAND_LOG": str(command_log),
                "COZE_ENV_FILE": str(env_file),
                "DATA_DIR": str(data_dir),
                "MYSQL_DATA_DIR": str(mysql_dir),
                "MYSQL_SOCKET": str(data_dir / "run" / "mysql-init.sock"),
                "MYSQL_PID_FILE": str(data_dir / "run" / "mysql-init.pid"),
                "SCHEMA_SQL": str(schema_sql),
                "SCHEMA_HCL": str(schema_hcl),
                "PATH": f"{fake_bin}:{env['PATH']}",
            }
        )
        result = subprocess.run(
            ["bash", str(MYSQL_INIT)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result, mysql_dir, command_log, fingerprint

    def test_legacy_bootstrap_marker_runs_schema_migration(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, mysql_dir, command_log, fingerprint = self.run_mysql_init(
                Path(tmpdir), existing_database=True
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("atlas schema apply", command_log.read_text(encoding="utf-8"))
            self.assertEqual(
                (mysql_dir / ".coze_schema_sha256").read_text(encoding="utf-8").strip(),
                fingerprint,
            )

    def test_matching_schema_fingerprint_skips_database_start(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            schema_hcl = root / "schema.hcl"
            schema_hcl.write_text('schema "opencoze" {}\n', encoding="utf-8")
            fingerprint = hashlib.sha256(schema_hcl.read_bytes()).hexdigest()

            result, _, command_log, _ = self.run_mysql_init(
                root,
                existing_database=True,
                schema_marker=fingerprint,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(command_log.exists())
            self.assertIn("schema fingerprint is current", result.stdout)

    def test_atlas_failure_does_not_advance_schema_marker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, mysql_dir, _, _ = self.run_mysql_init(
                Path(tmpdir),
                existing_database=True,
                atlas_exit=9,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((mysql_dir / ".coze_schema_sha256").exists())

    def test_fresh_database_imports_schema_and_records_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, mysql_dir, command_log, fingerprint = self.run_mysql_init(
                Path(tmpdir), existing_database=False
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            commands = command_log.read_text(encoding="utf-8")
            self.assertIn("mariadb-install-db", commands)
            self.assertIn("mysql --protocol=socket", commands)
            self.assertIn("atlas schema apply", commands)
            self.assertTrue((mysql_dir / ".coze_bootstrap_done").exists())
            self.assertEqual(
                (mysql_dir / ".coze_schema_sha256").read_text(encoding="utf-8").strip(),
                fingerprint,
            )


if __name__ == "__main__":
    unittest.main()
