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

    def test_topology_rejects_unsafe_paths_and_incomplete_parallel_handoffs(self):
        sequential = {
            "schema_version": 1,
            "mode": "sequential",
            "writers": [writer("current-task", "/repo", ["src"])],
            "integrator": None,
            "joint_verification": [],
        }
        for paths in ([], ["../outside"], ["/absolute"], ["src", "src"]):
            invalid = copy.deepcopy(sequential)
            invalid["writers"][0]["allowed_paths"] = paths
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, "allowed_paths"):
                validate_topology(invalid)

        parallel = {
            "schema_version": 1,
            "mode": "parallel-isolated",
            "writers": [writer("one", "/repo/one", ["one"]), writer("two", "/repo/two", ["two"])],
            "integrator": "owner",
            "joint_verification": ["bash scripts/check.sh"],
        }
        for field, value, message in (
            ("integrator", "", "integrator"),
            ("joint_verification", [], "joint_verification"),
        ):
            invalid = copy.deepcopy(parallel)
            invalid[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, message):
                validate_topology(invalid)

        invalid = copy.deepcopy(parallel)
        invalid["writers"][1]["id"] = "one"
        with self.assertRaisesRegex(ValueError, "IDs"):
            validate_topology(invalid)

    def test_topology_rejects_malformed_shape_and_cli_reports_it(self):
        valid = {
            "schema_version": 1, "mode": "sequential",
            "writers": [writer("one", "/repo", ["src"])],
            "integrator": None, "joint_verification": [],
        }
        cases = (
            ({}, "fields"),
            ({**valid, "schema_version": 2}, "identity"),
            ({**valid, "writers": []}, "writers"),
            ({**valid, "writers": [{"id": "one"}]}, "writer fields"),
            ({**valid, "writers": [{**valid["writers"][0], "isolation_evidence": []}]}, "isolation"),
            ({**valid, "integrator": "owner"}, "integration handoff"),
            ({**valid, "mode": "parallel-isolated"}, "at least two"),
        )
        for topology, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                validate_topology(topology)


if __name__ == "__main__":
    unittest.main()
