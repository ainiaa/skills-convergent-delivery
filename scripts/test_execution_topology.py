#!/usr/bin/env python3
"""Regression tests for planned writer topology."""

import copy
import unittest

from execution_topology import validate_topology


def writer(identifier, workspace, paths):
    return {
        "id": identifier,
        "workspace": workspace,
        "allowed_paths": paths,
        "isolation_evidence": ["No shared API, config, dependency, or test infrastructure."],
    }


class ExecutionTopologyTest(unittest.TestCase):
    def test_parallel_writers_require_separate_worktrees_and_an_integrator(self):
        topology = {
            "schema_version": 1,
            "mode": "parallel-isolated",
            "writers": [
                writer("payment-copy", "/tmp/payment-copy", ["payment/messages"]),
                writer("admin-export", "/tmp/admin-export", ["admin/export"]),
            ],
            "integrator": "delivery-owner",
            "joint_verification": ["bash scripts/check.sh --full"],
        }
        validate_topology(topology)

        invalid = copy.deepcopy(topology)
        invalid["writers"][1]["workspace"] = "/tmp/payment-copy"
        with self.assertRaisesRegex(ValueError, "distinct worktrees"):
            validate_topology(invalid)

        invalid = copy.deepcopy(topology)
        invalid["writers"][1]["allowed_paths"] = ["payment"]
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_topology(invalid)

    def test_sequential_work_uses_one_current_writer(self):
        validate_topology({
            "schema_version": 1,
            "mode": "sequential",
            "writers": [writer("current-task", "/repo", ["."])],
            "integrator": None,
            "joint_verification": [],
        })

        with self.assertRaisesRegex(ValueError, "one writer"):
            validate_topology({
                "schema_version": 1,
                "mode": "sequential",
                "writers": [writer("one", "/repo", ["a"]), writer("two", "/repo", ["b"])],
                "integrator": None,
                "joint_verification": [],
            })


if __name__ == "__main__":
    unittest.main()
