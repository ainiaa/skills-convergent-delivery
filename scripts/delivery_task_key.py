#!/usr/bin/env python3
"""Generate a deterministic task key from a frozen delivery scope."""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def normalized_items(values, field):
    normalized = sorted({value.strip() for value in values if value.strip()})
    if not normalized and field == "acceptance":
        raise ValueError("at least one acceptance is required")
    return normalized


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--acceptance", action="append", default=[])
    parser.add_argument("--module", action="append", default=[])
    arguments = parser.parse_args()

    try:
        repo = Path(arguments.repo).expanduser()
        if not repo.is_absolute():
            raise ValueError("repo must be absolute")
        if not arguments.baseline.strip():
            raise ValueError("baseline must be non-empty")
        scope = {
            "acceptance": normalized_items(arguments.acceptance, "acceptance"),
            "baseline": arguments.baseline.strip(),
            "modules": normalized_items(arguments.module, "module"),
            "repo": str(repo.resolve()),
        }
        encoded = json.dumps(scope, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        print(f"task-{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}")
        return 0
    except ValueError as error:
        print(f"task key blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
