#!/usr/bin/env python3
"""Freeze the host's actual read result for implementation references."""

import hashlib
import json
from pathlib import PurePosixPath


RECEIPT_FIELDS = {
    1: {"schema_version", "references", "receipt_fingerprint"},
    2: {"schema_version", "references", "feature_bindings", "receipt_fingerprint"},
    3: {"schema_version", "references", "feature_bindings", "alignment_bindings", "receipt_fingerprint"},
}
REFERENCE_FIELDS = {"reference", "status", "content_fingerprint"}
FEATURE_BINDING_FIELDS = {"target", "reference", "relation", "behaviors"}
BEHAVIOR_FIELDS = {"input", "state", "output", "effect", "caller", "verifier"}
ALIGNMENT_BINDING_FIELDS = {"target", "reference", "scope", "differences"}
ALIGNMENT_DIFFERENCE_FIELDS = {"path", "classification", "reason", "decision"}
RELATIONS = {"mirror", "analogy", "negative"}
ALIGNMENT_CLASSIFICATIONS = {"must-align", "allowed"}


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


def _paths(values, name):
    if not isinstance(values, list) or not values:
        raise ValueError(f"{name} is invalid")
    paths = []
    for value in values:
        path = PurePosixPath(_string(value, name).replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"{name} is invalid")
        paths.append(str(path))
    if len(paths) != len(set(paths)):
        raise ValueError(f"{name} is invalid")
    return paths


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


def _validate_alignment_bindings(bindings, references):
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("alignment bindings are invalid")
    reference_status = {item["reference"]: item["status"] for item in references}
    targets = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != ALIGNMENT_BINDING_FIELDS:
            raise ValueError("alignment binding is invalid")
        target = _string(binding.get("target"), "alignment binding target")
        reference = _string(binding.get("reference"), "alignment binding reference")
        if target in targets or reference_status.get(reference) != "read":
            raise ValueError("alignment binding is invalid")
        targets.add(target)
        scope = _paths(binding.get("scope"), "alignment binding scope")
        differences = binding.get("differences")
        if not isinstance(differences, list):
            raise ValueError("alignment differences are invalid")
        paths = set()
        for difference in differences:
            if not isinstance(difference, dict) or set(difference) != ALIGNMENT_DIFFERENCE_FIELDS:
                raise ValueError("alignment difference is invalid")
            path = _paths([difference.get("path")], "alignment difference path")[0]
            classification = difference.get("classification")
            decision = difference.get("decision")
            if path not in scope or path in paths or classification not in ALIGNMENT_CLASSIFICATIONS:
                raise ValueError("alignment difference is invalid")
            _string(difference.get("reason"), "alignment difference reason")
            if classification == "allowed" and not isinstance(decision, str):
                raise ValueError("allowed alignment difference requires a decision")
            if classification == "must-align" and decision is not None:
                raise ValueError("must-align difference cannot have a decision")
            if classification == "allowed":
                _string(decision, "allowed alignment decision")
            paths.add(path)


def freeze_receipt(references, *, feature_bindings=None, alignment_bindings=None):
    """Create a prompt-free receipt, including an explicit empty reference set."""
    _validate_references(references)
    value = {"schema_version": 1, "references": json.loads(json.dumps(references))}
    if feature_bindings is not None:
        _validate_feature_bindings(feature_bindings, references)
        value.update(schema_version=2, feature_bindings=json.loads(json.dumps(feature_bindings)))
    if alignment_bindings is not None:
        _validate_alignment_bindings(alignment_bindings, references)
        value.update(
            schema_version=3,
            feature_bindings=json.loads(json.dumps(feature_bindings or [])),
            alignment_bindings=json.loads(json.dumps(alignment_bindings)),
        )
    return {**value, "receipt_fingerprint": _fingerprint(value)}


def require_implementer_receipt(receipt):
    """Return the bound receipt fingerprint only when every required input was read."""
    schema_version = receipt.get("schema_version") if isinstance(receipt, dict) else None
    if schema_version not in RECEIPT_FIELDS or set(receipt) != RECEIPT_FIELDS[schema_version]:
        raise ValueError("implementation reference receipt is invalid")
    _validate_references(receipt["references"])
    if schema_version in {2, 3}:
        _validate_feature_bindings(receipt["feature_bindings"], receipt["references"])
    if schema_version == 3:
        _validate_alignment_bindings(receipt["alignment_bindings"], receipt["references"])
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
    if receipt["schema_version"] == 3 and not receipt["feature_bindings"]:
        return None
    raise ValueError("feature binding target does not match work item target")


def require_alignment_binding(receipt, target):
    """Return the frozen alignment binding when the receipt carries one."""
    require_implementer_receipt(receipt)
    target = _string(target, "alignment binding target")
    if receipt["schema_version"] != 3:
        return None
    for binding in receipt["alignment_bindings"]:
        if binding["target"] == target:
            return binding
    raise ValueError("alignment binding target does not match work item target")


def alignment_launch_binding(receipt, target, decisions):
    """Freeze the target and approved exceptions before a writer launch."""
    require_implementer_receipt(receipt)
    if receipt["schema_version"] != 3:
        if target is not None or decisions is not None:
            raise ValueError("alignment metadata requires an alignment receipt")
        return None
    binding = require_alignment_binding(receipt, target)
    if not isinstance(decisions, list) or any(
            not isinstance(item, str) or not item.strip() for item in decisions):
        raise ValueError("alignment decisions are invalid")
    normalized_decisions = sorted({item.strip() for item in decisions})
    approved = {
        difference["decision"] for difference in binding["differences"]
        if difference["classification"] == "allowed"
    }
    if not approved <= set(normalized_decisions):
        raise ValueError("alignment decision is not frozen for launch")
    return _fingerprint({
        "reference_receipt_fingerprint": receipt["receipt_fingerprint"],
        "target": _string(target, "alignment target"),
        "decisions": normalized_decisions,
    })
