#!/usr/bin/env python3
"""Validate the frozen user-visible Converge interaction catalog."""

import copy
import json
import unittest
from pathlib import Path

from interaction_smoke import validate_catalog


ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "evals" / "converge-interaction-v1.json"


class InteractionContractTest(unittest.TestCase):
    def test_catalog_defines_replayable_user_visible_scenarios(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

        validate_catalog(catalog, ROOT)
        self.assertEqual(2, catalog["schema_version"])
        self.assertEqual("same_conversation", catalog["scope"])
        self.assertEqual(8, len(catalog["scenarios"]))
        self.assertEqual(3, catalog["smoke"]["minimum_fresh_runs"])

    def test_catalog_rejects_duplicate_or_replaced_critical_scenarios(self):
        catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
        invalid = copy.deepcopy(catalog)
        invalid["smoke"]["critical_ids"] = ["local-fix", "local-fix", "complex-plan"]

        with self.assertRaisesRegex(ValueError, "critical_ids"):
            validate_catalog(invalid, ROOT)


if __name__ == "__main__":
    unittest.main()
