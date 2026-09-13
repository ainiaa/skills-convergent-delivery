#!/usr/bin/env python3
"""Freeze the host's actual read result for implementation references."""

import hashlib
import json


RECEIPT_FIELDS = {
    1: {"schema_version", "references", "receipt_fingerprint"},
    2: {"schema_version", "references", "feature_bindings", "receipt_fingerprint"},
}
REFERENCE_FIELDS = {"reference", "status", "content_fingerprint"}
FEATURE_BINDING_FIELDS = {"target", "reference", "relation", "behaviors"}
BEHAVIOR_FIELDS = {"input", "state", "output", "effect", "caller", "verifier"}
RELATIONS = {"mirror", "analogy", "negative"}


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


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is invalid")
    return value.strip()


def _validate_feature_bindings(bindings, references):
    if not isinstance(bindings, list):
        raise ValueError("feature bindings must be a list")
    reference_status = {item["reference"]: item["status"] for item in references}
    targets = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != FEATURE_BINDING_FIELDS:
            raise ValueError("feature binding is invalid")
        target = _string(binding.get("target"), "feature binding target")
        reference = _string(binding.get("reference"), "feature binding reference")
        if target in targets or binding.get("relation") not in RELATIONS \
                or reference_status.get(reference) != "read":
            raise ValueError("feature binding is invalid")
        targets.add(target)
        behaviors = binding.get("behaviors")
        if not isinstance(behaviors, list) or not behaviors:
            raise ValueError("feature binding behaviors are invalid")
        for behavior in behaviors:
            if not isinstance(behavior, dict) or set(behavior) != BEHAVIOR_FIELDS:
                raise ValueError("feature behavior is invalid")
            for field in BEHAVIOR_FIELDS:
                _string(behavior[field], f"feature behavior {field}")


def freeze_receipt(references, *, feature_bindings=None):
    """Create a prompt-free receipt, including an explicit empty reference set."""
    _validate_references(references)
    value = {"schema_version": 1, "references": json.loads(json.dumps(references))}
    if feature_bindings is not None:
        _validate_feature_bindings(feature_bindings, references)
        value.update(schema_version=2, feature_bindings=json.loads(json.dumps(feature_bindings)))
    return {**value, "receipt_fingerprint": _fingerprint(value)}


def require_implementer_receipt(receipt):
    """Return the bound receipt fingerprint only when every required input was read."""
    schema_version = receipt.get("schema_version") if isinstance(receipt, dict) else None
    if schema_version not in RECEIPT_FIELDS or set(receipt) != RECEIPT_FIELDS[schema_version]:
        raise ValueError("implementation reference receipt is invalid")
    _validate_references(receipt["references"])
    if schema_version == 2:
        _validate_feature_bindings(receipt["feature_bindings"], receipt["references"])
    value = {key: item for key, item in receipt.items() if key != "receipt_fingerprint"}
    if receipt["receipt_fingerprint"] != _fingerprint(value):
        raise ValueError("implementation reference receipt fingerprint is invalid")
    if any(item["status"] != "read" for item in receipt["references"]):
        raise ValueError("unread implementation reference blocks the launch")
    return receipt["receipt_fingerprint"]


def require_feature_binding(receipt, target):
    """Return the declared binding for target, when this receipt has feature bindings."""
    require_implementer_receipt(receipt)
    target = _string(target, "feature binding target")
    if receipt["schema_version"] == 1:
        return None
    for binding in receipt["feature_bindings"]:
        if binding["target"] == target:
            return binding
    raise ValueError("feature binding target does not match work item target")
