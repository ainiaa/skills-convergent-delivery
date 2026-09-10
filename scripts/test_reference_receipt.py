#!/usr/bin/env python3
"""Regression tests for implementation-reference launch receipts."""

import hashlib
import unittest

from reference_receipt import freeze_receipt, require_implementer_receipt


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

        self.assertEqual(receipt["receipt_fingerprint"], require_implementer_receipt(receipt))

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
