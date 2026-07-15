import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "hfs" / "bin" / "render-env.sh"


class RenderEnvTests(unittest.TestCase):
    def render(self, **overrides: str) -> str:
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


if __name__ == "__main__":
    unittest.main()
