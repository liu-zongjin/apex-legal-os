#!/usr/bin/env python3
"""Install the pinned official Claude Code client used by Stella's CC2API bridge."""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "2.1.295"

if __name__ == "__main__":
    npm = shutil.which("npm")
    if not npm:
        raise SystemExit("请先安装 Node.js 22 或更新版本（需要 npm）")
    subprocess.run([npm, "install", "--prefix", str(ROOT / "data/cc2api-runtime"),
                    "--no-audit", "--no-fund", f"@anthropic-ai/claude-code@{VERSION}"], check=True)
