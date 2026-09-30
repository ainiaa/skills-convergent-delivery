#!/usr/bin/env python3
"""Report whether the opt-in weekly Skill review is enabled."""

import argparse
import json
from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".convergent-delivery" / "skill-improvement.toml"
GLOBAL_CONFIG = Path.home() / ".convergent-delivery" / "skill-improvement.toml"


def configured_value(config_path):
    """Return an explicit setting, or None when this file does not set one."""
    try:
        with Path(config_path).open("rb") as stream:
            config = tomllib.load(stream)
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"invalid TOML: {error}") from error

    section = config.get("skill_review")
    if section is None:
        return None
    if not isinstance(section, dict):
        raise ValueError("skill_review must be a TOML table")
    if "enabled" not in section:
        return None
    enabled = section.get("enabled", False)
    if type(enabled) is not bool:
        raise ValueError("skill_review.enabled must be true or false")
    return enabled


def review_enabled(config_path, global_config_path):
    """The project setting wins; absent settings inherit globally and default off."""
    for path in (config_path, global_config_path):
        enabled = configured_value(path)
        if enabled is not None:
            return enabled
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--global-config", type=Path, default=GLOBAL_CONFIG)
    arguments = parser.parse_args()
    try:
        enabled = review_enabled(arguments.config, arguments.global_config)
    except (OSError, ValueError) as error:
        print(f"skill review policy invalid: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "enabled": enabled,
        "action": "review" if enabled else "skip",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
