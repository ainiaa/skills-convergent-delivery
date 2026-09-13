#!/usr/bin/env python3
"""Regression tests for implementation-reference launch receipts."""

import hashlib
import unittest

from reference_receipt import (
    freeze_receipt,
    require_feature_binding,
    require_implementer_receipt,
)


class ReferenceReceiptTest(unittest.TestCase):
    def test_reference_receipt_rejects_malformed_and_duplicate_references(self):
        cases = (
            "not-a-list",
            [{"reference": "", "status": "read", "content_fingerprint": "a" * 64}],
            [{"reference": "same", "status": "read", "content_fingerprint": "a" * 64}] * 2,
            [{"reference": "read", "status": "read", "content_fingerprint": "bad"}],
            [{"reference": "missing", "status": "unavailable", "content_fingerprint": "a" * 64}],
        )
        for references in cases:
            with self.subTest(references=references), self.assertRaises(ValueError):
                freeze_receipt(references)

    def test_implementer_receipt_accepts_an_explicitly_empty_reference_set(self):
        receipt = freeze_receipt([])

        self.assertEqual(1, receipt["schema_version"])
        self.assertEqual(receipt["receipt_fingerprint"], require_implementer_receipt(receipt))

    def test_feature_binding_freezes_one_read_reference_and_its_behavior_matrix(self):
        reference = "codex://thread/source-feature"
        receipt = freeze_receipt(
            [{"reference": reference, "status": "read", "content_fingerprint": "a" * 64}],
            feature_bindings=[{
                "target": "delivery-status-normalization",
                "reference": reference,
                "relation": "analogy",
                "behaviors": [{
                    "input": "missing status", "state": "new", "output": "normalized status",
                    "effect": "no remote write", "caller": "delivery controller",
                    "verifier": "python3 -m unittest scripts.test_status_normalizer",
                }],
            }],
        )

        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual(receipt["receipt_fingerprint"], require_implementer_receipt(receipt))

    def test_feature_binding_rejects_unread_reference_empty_matrix_and_duplicate_target(self):
        reference = {"reference": "codex://thread/source-feature", "status": "read", "content_fingerprint": "a" * 64}
        binding = {
            "target": "delivery-status-normalization", "reference": reference["reference"],
            "relation": "mirror", "behaviors": [{
                "input": "input", "state": "state", "output": "output", "effect": "effect",
                "caller": "caller", "verifier": "python3 -m unittest",
            }],
        }
        cases = (
            ([{**reference, "status": "unavailable", "content_fingerprint": None}], [binding]),
            ([reference], [{**binding, "behaviors": []}]),
            ([reference], [binding, {**binding, "reference": "codex://thread/other"}]),
            ([reference], [{**binding, "relation": "copy"}]),
        )

        for references, bindings in cases:
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                freeze_receipt(references, feature_bindings=bindings)

    def test_feature_binding_rejects_malformed_binding_structures(self):
        reference = {"reference": "codex://thread/source-feature", "status": "read", "content_fingerprint": "a" * 64}
        behavior = {
            "input": "input", "state": "state", "output": "output", "effect": "effect",
            "caller": "caller", "verifier": "python3 -m unittest",
        }
        binding = {
            "target": "delivery-status-normalization", "reference": reference["reference"],
            "relation": "mirror", "behaviors": [behavior],
        }
        cases = (
            "not-a-list",
            ["not-a-binding"],
            [{**binding, "target": 5}],
            [{**binding, "behaviors": [{"input": "only"}]}],
        )

        for bindings in cases:
            with self.subTest(bindings=bindings), self.assertRaises(ValueError):
                freeze_receipt([reference], feature_bindings=bindings)

    def test_require_feature_binding_returns_the_declared_binding_for_its_target(self):
        reference = "codex://thread/source-feature"
        binding = {
            "target": "delivery-status-normalization", "reference": reference,
            "relation": "analogy", "behaviors": [{
                "input": "missing status", "state": "new", "output": "normalized status",
                "effect": "no remote write", "caller": "delivery controller",
                "verifier": "python3 -m unittest",
            }],
        }
        receipt = freeze_receipt(
            [{"reference": reference, "status": "read", "content_fingerprint": "a" * 64}],
            feature_bindings=[binding],
        )

        self.assertEqual(binding, require_feature_binding(receipt, "delivery-status-normalization"))

    def test_require_feature_binding_returns_none_without_feature_bindings(self):
        receipt = freeze_receipt([
            {"reference": "codex://thread/source-feature", "status": "read",
             "content_fingerprint": "a" * 64},
        ])

        self.assertIsNone(require_feature_binding(receipt, "delivery-status-normalization"))

    def test_require_implementer_receipt_rejects_malformed_receipts(self):
        for receipt in ("nope", {"schema_version": 3}, {"schema_version": 1, "references": []}):
            with self.subTest(receipt=receipt), self.assertRaisesRegex(
                ValueError, "implementation reference receipt is invalid",
            ):
                require_implementer_receipt(receipt)

    def test_require_feature_binding_rejects_unknown_targets(self):
        reference = "codex://thread/source-feature"
        receipt = freeze_receipt(
            [{"reference": reference, "status": "read", "content_fingerprint": "a" * 64}],
            feature_bindings=[{
                "target": "delivery-status-normalization", "reference": reference,
                "relation": "mirror", "behaviors": [{
                    "input": "input", "state": "state", "output": "output", "effect": "effect",
                    "caller": "caller", "verifier": "python3 -m unittest",
                }],
            }],
        )

        with self.assertRaisesRegex(ValueError, "target does not match"):
            require_feature_binding(receipt, "another-target")

    def test_implementer_receipt_requires_every_declared_reference_to_be_read(self):
        receipt = freeze_receipt([
            {
                "reference": "codex://thread/example",
                "status": "unavailable",
                "content_fingerprint": None,
            },
        ])

        with self.assertRaisesRegex(ValueError, "unread implementation reference"):
            require_implementer_receipt(receipt)

    def test_implementer_receipt_rejects_a_forged_content_fingerprint(self):
        receipt = freeze_receipt([
            {
                "reference": "codex://thread/example",
                "status": "read",
                "content_fingerprint": hashlib.sha256(b"reference contents").hexdigest(),
            },
        ])
        receipt["references"][0]["content_fingerprint"] = "a" * 64

        with self.assertRaisesRegex(ValueError, "receipt fingerprint"):
            require_implementer_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
