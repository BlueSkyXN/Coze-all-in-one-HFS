import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hfs" / "bin" / "render-env.sh"
NO_PAID_VARIABLE_KEYS = (
    "ALLOW_REGISTRATION_EMAIL",
    "MODEL_PROTOCOL_0",
    "MODEL_OPENCOZE_ID_0",
    "MODEL_NAME_0",
    "MODEL_ID_0",
    "MODEL_BASE_URL_0",
    "BUILTIN_CM_TYPE",
    "BUILTIN_CM_OPENAI_BASE_URL",
    "BUILTIN_CM_OPENAI_MODEL",
    "S3_ENDPOINT",
    "S3_BUCKET_ENDPOINT",
    "S3_REGION",
    "VIKING_DB_HOST",
    "VIKING_DB_REGION",
    "VIKING_DB_SCHEME",
)
NO_PAID_RUNTIME_DEFAULT_KEYS = (
    "ENABLE_LOCAL_MINIO",
    "STORAGE_TYPE",
    "MINIO_ADDRESS",
    "ES_ADDR",
    "ES_VERSION",
    "VECTOR_STORE_TYPE",
)


class RenderEnvTests(unittest.TestCase):
    def render(self, *, unset: tuple[str, ...] = (), **overrides: str) -> str:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env_file = root / "coze.env"
            generated_file = root / "generated.env"
            env = os.environ.copy()
            env.update(
                {
                    "COZE_ENV_FILE": str(env_file),
                    "COZE_GENERATED_ENV_FILE": str(generated_file),
                    "DATA_DIR": str(root / "data"),
                }
            )
            for key in unset:
                env.pop(key, None)
            env.update(overrides)
            subprocess.run(["bash", str(SCRIPT)], check=True, env=env, capture_output=True, text=True)
            return env_file.read_text(encoding="utf-8")

    def test_code_runner_defaults_to_sandbox(self):
        rendered = self.render()

        self.assertIn("export CODE_RUNNER_TYPE=sandbox\n", rendered)
        self.assertIn("export CODE_RUNNER_ALLOW_NET=cdn.jsdelivr.net\n", rendered)
        self.assertIn("export CODE_RUNNER_TIMEOUT_SECONDS=60\n", rendered)
        self.assertIn("export CODE_RUNNER_MEMORY_LIMIT_MB=100\n", rendered)

    def test_code_runner_allows_explicit_override(self):
        rendered = self.render(CODE_RUNNER_TYPE="local", CODE_RUNNER_TIMEOUT_SECONDS="15")

        self.assertIn("export CODE_RUNNER_TYPE=local\n", rendered)
        self.assertIn("export CODE_RUNNER_TIMEOUT_SECONDS=15\n", rendered)

    def test_persistence_gate_defaults_off_and_allows_override(self):
        self.assertIn("export PERSISTENCE_REQUIRED=false\n", self.render())
        self.assertIn("export PERSISTENCE_REQUIRED=true\n", self.render(PERSISTENCE_REQUIRED="true"))

    def test_no_paid_profile_uses_local_backends_without_provider_overrides(self):
        rendered = self.render(unset=NO_PAID_VARIABLE_KEYS + NO_PAID_RUNTIME_DEFAULT_KEYS)

        for expected in (
            "export ENABLE_LOCAL_MINIO=1\n",
            "export STORAGE_TYPE=minio\n",
            "export MINIO_ADDRESS=127.0.0.1:9000\n",
            "export ES_ADDR=http://127.0.0.1:9200\n",
            "export ES_VERSION=v8\n",
            "export VECTOR_STORE_TYPE=milvus\n",
            "export MODEL_OPENCOZE_ID_0=100001\n",
            "export VIKING_DB_SCHEME=https\n",
        ):
            self.assertIn(expected, rendered)
        defaulted_nonempty = {"MODEL_OPENCOZE_ID_0", "VIKING_DB_SCHEME"}
        for key in set(NO_PAID_VARIABLE_KEYS) - defaulted_nonempty:
            self.assertIn(f"export {key}=''\n", rendered)


if __name__ == "__main__":
    unittest.main()
