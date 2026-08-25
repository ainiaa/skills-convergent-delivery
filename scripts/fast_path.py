#!/usr/bin/env python3
"""Block the disabled generic fast path."""

import sys


def validate_fast_path(*_args):
    """Keep callers on the full verification path until a formatter contract exists."""
    raise ValueError("fast path is disabled pending a formatter-specific contract")


def main():
    print("fast path blocked: fast path is disabled pending a formatter-specific contract", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
