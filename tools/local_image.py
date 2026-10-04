"""Build the local Linux image used by Compose and kind development stacks."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_local_image(image: str) -> None:
    """Rebuild the source bundle and local image tag from current checkouts."""
    bundle = os.environ.get("BUNDLE_OUTPUT", str(ROOT / ".integration-state/artifacts/networkclaw-bundle.tar.gz"))
    bundle_cmd = [
        sys.executable,
        str(ROOT / "tools/build-bundle.py"),
        "--output",
        bundle,
        "--networkclaw",
        os.environ.get("NETWORKCLAW_PATH", str(ROOT.parent / "NetworkClaw")),
        "--harness",
        os.environ.get("HARNESS_PATH", str(ROOT.parent / "networkclaw-harness")),
    ]
    subprocess.run(bundle_cmd, cwd=ROOT, check=True)
    env = os.environ.copy()
    env["NETWORKCLAW_IMAGE_TAG"] = image
    subprocess.run([sys.executable, str(ROOT / "ci/ubuntu-22.04/build-artifacts.py")], cwd=ROOT, env=env, check=True)
