#!/usr/bin/env python3
"""Install or remove the exact macOS LaunchAgent for Converge autonomy service."""

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path


LABEL = "com.convergent-delivery.autonomy"


def path():
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--remove", action="store_true")
    arguments = parser.parse_args()
    target = path()
    domain = f"gui/{os.getuid()}/{LABEL}"
    if arguments.remove:
        subprocess.run(["launchctl", "bootout", domain], capture_output=True, check=False)
        if target.exists():
            target.unlink()
        return 0
    source = Path(arguments.source).expanduser().resolve()
    script = source / "scripts" / "autonomy_service.py"
    if not script.is_file():
        raise ValueError("autonomy service script is missing")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, str(script), "--serve"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 5,
        "ProcessType": "Background",
    }
    temporary = target.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)
    os.replace(temporary, target)
    subprocess.run(["launchctl", "bootout", domain], capture_output=True, check=False)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(target)], check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
