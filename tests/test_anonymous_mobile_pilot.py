from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from backend.anonymous_pilot import PILOT_DB_FILENAME, validate_anonymous_pilot_environment


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AnonymousMobilePilotTests(unittest.TestCase):
    def pilot_environment(self, root: Path) -> dict[str, str]:
        environment = {
            "APEX_ANONYMOUS_PILOT": "1",
            "LEGAL_KB_RUNTIME_DIR": str(root),
            "LEGAL_KB_DB_PATH": str(root / PILOT_DB_FILENAME),
            "LEGAL_KB_UPLOAD_DIR": str(root / "uploads"),
            "LEGAL_KB_ARTICLE_IMAGE_DIR": str(root / "article_images"),
            "LEGAL_KB_DATA_DIR": str(root / "service-data"),
            "LEGAL_KB_ACCESS_PASSWORD": "test-password-without-real-data",
            "LEGAL_KB_SESSION_SECRET": "test-session-secret-without-real-data",
        }
        return environment

    def test_rejects_normal_database_name_and_external_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = self.pilot_environment(root)
            environment["LEGAL_KB_DB_PATH"] = str(root / "legal_kb.db")
            with self.assertRaisesRegex(RuntimeError, "apex-anonymous-pilot.db"):
                validate_anonymous_pilot_environment(environment)

            environment = self.pilot_environment(root)
            environment["DEEPSEEK_API_KEY"] = "not-allowed-in-anonymous-pilot"
            with self.assertRaisesRegex(RuntimeError, "DEEPSEEK_API_KEY"):
                validate_anonymous_pilot_environment(environment)

    def test_prepares_fictional_database_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = os.environ.copy()
            for key in list(environment):
                if key.endswith(("_API_KEY", "_API_SECRET", "_ACCESS_TOKEN", "_AUTHORIZATION")):
                    environment.pop(key)
            environment.update(self.pilot_environment(root))
            probe = """
from backend.anonymous_pilot import prepare_anonymous_pilot
from backend.main import get_db
prepare_anonymous_pilot()
prepare_anonymous_pilot()
with get_db() as connection:
    print(connection.execute("SELECT count(*) FROM case_manager_clients").fetchone()[0])
    print(connection.execute("SELECT count(*) FROM case_manager_cases").fetchone()[0])
    print(connection.execute("SELECT count(*) FROM case_manager_todos").fetchone()[0])
    print(connection.execute("SELECT count(*) FROM case_manager_hearings").fetchone()[0])
"""
            result = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=PROJECT_ROOT,
                env=environment,
                check=True,
                text=True,
                capture_output=True,
            )
            counts = [line.strip() for line in result.stdout.splitlines() if line.strip().isdigit()]
            self.assertEqual(counts[-4:], ["2", "2", "1", "1"])

    def test_container_configuration_keeps_data_outside_the_image(self):
        dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
        compose = (PROJECT_ROOT / "deploy/mobile-pilot/compose.yaml").read_text(encoding="utf-8")
        dockerfile = (PROJECT_ROOT / "deploy/mobile-pilot/Dockerfile").read_text(encoding="utf-8")
        for forbidden_path in ("*.db", "uploads/", "article_images/", ".env.*", "**/cookies*.json"):
            self.assertIn(forbidden_path, dockerignore)
        self.assertIn("LEGAL_KB_DB_PATH: \"/var/lib/apex/apex-anonymous-pilot.db\"", compose)
        self.assertIn("COURT_ONLINE_SCHEDULER_DISABLED: \"1\"", compose)
        self.assertIn("JUDICIAL_SMS_SCHEDULER_DISABLED: \"1\"", compose)
        self.assertIn("scripts/mobile_pilot_entrypoint.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
