#!/usr/bin/env python3
"""Remove the legacy macOS LaunchAgent for Converge autonomy service."""

import argparse
import os
import subprocess
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
    raise ValueError("autonomy service LaunchAgent installation is no longer supported")


if __name__ == "__main__":
    raise SystemExit(main())
