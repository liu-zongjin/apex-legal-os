import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
URL_SCRIPT = ROOT / "scripts" / "private_https_url.sh"


class PrivateHttpsScriptTests(unittest.TestCase):
    def run_script(self, dns_name: str) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_tailscale = Path(temp_dir) / "tailscale"
            fake_tailscale.write_text(
                "#!/bin/bash\n"
                "if [ \"$1\" = status ] && [ \"$2\" = --json ]; then\n"
                f"  printf '%s\\n' '{json.dumps({'Self': {'DNSName': dns_name}})}'\n"
                "  exit 0\n"
                "fi\n"
                "exit 1\n",
                encoding="utf-8",
            )
            fake_tailscale.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = f"{temp_dir}:{env['PATH']}"
            env["LEGAL_KB_TAILSCALE_BIN"] = str(fake_tailscale)
            return subprocess.run(
                ["bash", str(URL_SCRIPT)],
                text=True,
                capture_output=True,
                check=False,
                env=env,
            )

    def test_returns_https_url_for_tailscale_dns_name(self):
        result = self.run_script("legal-kb-mac.example.ts.net.")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "https://legal-kb-mac.example.ts.net\n")

    def test_rejects_non_tailscale_dns_name(self):
        result = self.run_script("legal-kb-mac.local")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Could not determine", result.stderr)


if __name__ == "__main__":
    unittest.main()
