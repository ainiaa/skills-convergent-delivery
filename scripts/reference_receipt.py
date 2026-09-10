#!/usr/bin/env python3
"""Freeze the host's actual read result for implementation references."""

import hashlib
import json


RECEIPT_FIELDS = {"schema_version", "references", "receipt_fingerprint"}
REFERENCE_FIELDS = {"reference", "status", "content_fingerprint"}


def _fingerprint(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def _sha256(value):
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _validate_references(references):
    if not isinstance(references, list):
        raise ValueError("implementation references must be a list")
    seen = set()
    for item in references:
        if not isinstance(item, dict) or set(item) != REFERENCE_FIELDS \
                or not isinstance(item.get("reference"), str) or not item["reference"].strip() \
                or item.get("status") not in {"read", "unavailable"}:
            raise ValueError("implementation reference is invalid")
        if item["reference"] in seen:
            raise ValueError("implementation references must be unique")
        seen.add(item["reference"])
        content = item["content_fingerprint"]
        if item["status"] == "read" and not _sha256(content):
            raise ValueError("read implementation reference content is invalid")
        if item["status"] == "unavailable" and content is not None:
            raise ValueError("unavailable implementation reference cannot have content")


def freeze_receipt(references):
    """Create a prompt-free receipt, including an explicit empty reference set."""
    _validate_references(references)
    value = {"schema_version": 1, "references": json.loads(json.dumps(references))}
    return {**value, "receipt_fingerprint": _fingerprint(value)}


def require_implementer_receipt(receipt):
    """Return the bound receipt fingerprint only when every required input was read."""
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS \
            or receipt.get("schema_version") != 1:
        raise ValueError("implementation reference receipt is invalid")
    _validate_references(receipt["references"])
    value = {key: item for key, item in receipt.items() if key != "receipt_fingerprint"}
    if receipt["receipt_fingerprint"] != _fingerprint(value):
        raise ValueError("implementation reference receipt fingerprint is invalid")
    if any(item["status"] != "read" for item in receipt["references"]):
        raise ValueError("unread implementation reference blocks the launch")
    return receipt["receipt_fingerprint"]
