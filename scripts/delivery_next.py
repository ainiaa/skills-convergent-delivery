#!/usr/bin/env python3
"""Validate a converge state and emit exactly one next-stage token."""

import argparse
import copy
import json
import sys
from pathlib import Path

from delivery_engine import (
    TASK_KINDS,
    compatible_root,
    compatible_tdd_provider,
    controller_identity,
    file_fingerprint,
    legacy_pdlc_fingerprint,
    load_provider_registry,
    pdlc_fingerprint,
    pdlc_metadata,
    provider_reference,
    validate_provider_manifest,
)
from delivery_lease import is_expired, lease_paths, read_record, same_owner
from controller_snapshot import validate_snapshot
from provider_contract import validate_reference as validate_complete_provider_reference
from provider_contract import canonical_fingerprint
from run_contract import action, delivery_action, legacy_action
from runtime_adapter import (
    validate_binding as validate_runtime_binding,
    validate_cleanup_barrier,
)
from delivery_progress import plan_projection_fingerprint
from evidence_contract import (
    valid_evidence_receipts, validate_source_receipt, workspace_source,
)
from task_profile import freeze_routing, infer_path_risks


NATIVE_ACTIVE_STAGES = {
    "scope",
    "round-1-build",
    "round-1-semantic-review",
    "verify-round-1",
    "round-2-risk-review",
    "verify-final",
}
PDLC_ACTIVE_STAGES = {"pdlc-run"}
ENGINE_SELECTIONS = {"auto", "explicit"}
CHECK_RESULTS = {"pass", "fail", "unknown"}
FRESHNESS = {"fresh", "stale", "unavailable"}
NO_OPEN_ISSUES = {
    "", "0", "none", "no", "n/a", "无", "没有", "无需处理",
    "no remaining scoped findings",
}

BLOCKED_CODES = {
    "decision",
    "environment",
    "no_progress",
    "budget_exhausted",
}
DEFAULT_LEASE_ROOT = Path.home() / ".convergent-delivery" / "leases"
WORKER_STATUSES = {"working", "completed", "interrupted", "blocked"}
WORKER_TERMINAL_STATUSES = WORKER_STATUSES - {"working"}
ROUTES = {"inline", "planned", "delegated", "batch"}
REVIEW_TIERS = {"low", "normal", "high"}
PROGRESS_EVENTS = {"heartbeat", "milestone"}
PROGRESS_PHASES = {
    "understanding", "planning", "reproducing", "testing", "implementing",
    "verifying", "reviewing", "closing",
}
LEGACY_V6_CONTROLLERS = {
    ("0.10.0", "843047313fb0c0c7b068e4a7033fe51a7ffec62aaf4234aaf86893c48144a485"),
}


def require_string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def normalize_open_issues(value):
    if isinstance(value, str):
        issue = value.strip()
        return [] if issue.lower() in NO_OPEN_ISSUES else [issue]
    if isinstance(value, list) and all(
        isinstance(issue, str) and issue.strip() for issue in value
    ):
        return [issue.strip() for issue in value]
    raise ValueError("handoff.open_issues must be a string or a list of strings")


def legacy_execution_control():
    return {
        "routing": {
            "schema_version": 1,
            "status": "legacy_unavailable",
            "assessment_count": 0,
            "route": None,
            "review_tier": None,
            "profile_fingerprint": None,
        },
        "review": {
            "protocol_version": 3,
            "repair_budget_remaining": 1,
            "re_review_budget_remaining": 1,
            "integration_budget_remaining": 0,
            "rounds": [],
        },
    }


def upgrade_review(review):
    if not isinstance(review, dict) or review.get("protocol_version") != 2:
        return review
    source = review.get("source_fingerprint")
    requests = []
    for request in review.get("requests", []):
        requests.append({
            **request,
            "reviewer_ref": "legacy-reviewer",
            "mode": "shared",
            "independent": False,
            "finding_fingerprints": [],
        })
    return {
        "protocol_version": 3,
        "repair_budget_remaining": review.get("repair_budget_remaining"),
        "re_review_budget_remaining": review.get("re_review_budget_remaining"),
        "integration_budget_remaining": review.get("integration_budget_remaining"),
        "rounds": ([{"source_fingerprint": source, "requests": requests}] if source else []),
    }


def upgrade_execution_control(state):
    control = state.get("execution_control")
    if isinstance(control, dict) and "review" in control:
        control["review"] = upgrade_review(control["review"])


def upgrade_evidence_levels(state):
    host_sync = state.get("host_sync")
    if isinstance(host_sync, dict):
        host_sync.setdefault("evidence_level", "controller_attested")
    for worker in state.get("workers", []):
        progress = worker.get("progress") if isinstance(worker, dict) else None
        if isinstance(progress, dict):
            progress.setdefault(
                "evidence_level",
                "host_observed" if progress.get("event") == "heartbeat"
                else "controller_attested",
            )
    receipt = state.get("worker_tree_receipt")
    if isinstance(receipt, dict) and receipt.get("schema_version") == 1:
        receipt["schema_version"] = 2
        receipt["evidence_level"] = (
            "host_observed" if receipt.get("mode") == "tree_query"
            else "controller_attested"
        )
    if isinstance(receipt, dict) and receipt.get("schema_version") == 2:
        receipt.setdefault("observation_fingerprint", None)


def upgrade_state(value):
    if not isinstance(value, dict):
        raise ValueError("state must be an object")
    if value.get("schema_version") == 10:
        state = copy.deepcopy(value)
        upgrade_evidence_levels(state)
        handoff = state.get("handoff")
        if isinstance(handoff, dict) and "open_issues" in handoff:
            handoff["open_issues"] = normalize_open_issues(handoff["open_issues"])
        return state
    if value.get("schema_version") == 9:
        if value.get("workers"):
            raise ValueError("legacy worker state requires manual recovery")
        state = copy.deepcopy(value)
        state["schema_version"] = 10
        upgrade_execution_control(state)
        for worker in state.get("workers", []):
            worker.setdefault("parent_ref", None)
            worker.setdefault("task_id", state.get("task_id", state.get("task_key")))
            worker.setdefault("depth", 1)
            worker.setdefault("may_dispatch", False)
        state.setdefault("worker_tree_receipt", None)
        state.setdefault("runtime_binding", None)
        state.setdefault("host_sync", {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None
        })
        state.setdefault("source_receipt", None)
        upgrade_evidence_levels(state)
        handoff = state.get("handoff")
        if isinstance(handoff, dict) and "open_issues" in handoff:
            handoff["open_issues"] = normalize_open_issues(handoff["open_issues"])
        return state
    if value.get("schema_version") in {7, 8}:
        if value.get("workers"):
            raise ValueError("legacy worker state requires manual recovery")
        state = copy.deepcopy(value)
        state["schema_version"] = 10
        state.setdefault("workers", [])
        state.setdefault("worker_tree_receipt", None)
        state.setdefault("runtime_binding", None)
        state.setdefault("host_sync", {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None
        })
        state.setdefault("source_receipt", None)
        state.setdefault("source_fingerprint", None)
        state.setdefault("execution_control", legacy_execution_control())
        upgrade_execution_control(state)
        upgrade_evidence_levels(state)
        handoff = state.get("handoff")
        if isinstance(handoff, dict) and "open_issues" in handoff:
            handoff["open_issues"] = normalize_open_issues(handoff["open_issues"])
        return state
    if value.get("schema_version") not in {5, 6}:
        raise ValueError("unsupported schema_version")
    state = copy.deepcopy(value)
    source_schema = state["schema_version"]
    if source_schema == 6:
        controller = state.get("controller")
        identity = (
            controller.get("version"), controller.get("fingerprint")
        ) if isinstance(controller, dict) and set(controller) == {"version", "fingerprint"} else None
        if identity not in LEGACY_V6_CONTROLLERS:
            raise ValueError("legacy controller is unavailable or incompatible")
    engine = state.pop("engine", None)
    if not isinstance(engine, dict):
        raise ValueError("legacy engine is invalid")
    if isinstance(engine, dict) and engine.get("name") == "pdlc-v1":
        root = engine.get("pdlc_root")
        task_kind = engine.get("task_kind")
        if source_schema == 5 and engine.get("pdlc_fingerprint") != legacy_pdlc_fingerprint(root, task_kind):
            raise ValueError("legacy frozen PDLC capability is unavailable or changed")
        if source_schema == 5:
            engine.update(pdlc_metadata(root, task_kind, engine.get("provider_manifest")))
    state.update(
        schema_version=10,
        controller=controller_identity(),
        provider_binding=legacy_provider_binding(engine),
        workers=state.get("workers", []),
        worker_tree_receipt=None,
        runtime_binding=state.get("runtime_binding"),
        host_sync=state.get("host_sync", {
            "mode": "legacy_unavailable", "acknowledged_fingerprint": None
        }),
        source_fingerprint=state.get("source_fingerprint"),
        source_receipt=state.get("source_receipt"),
        execution_control=state.get("execution_control", legacy_execution_control()),
    )
    upgrade_execution_control(state)
    for worker in state["workers"]:
        worker.setdefault("progress", None)
        worker.setdefault("parent_ref", None)
        worker.setdefault("task_id", state.get("task_id", state.get("task_key")))
        worker.setdefault("depth", 1)
        worker.setdefault("may_dispatch", False)
    if state["workers"]:
        raise ValueError("legacy worker state requires manual recovery")
    upgrade_evidence_levels(state)
    handoff = state.get("handoff")
    if isinstance(handoff, dict) and "open_issues" in handoff:
        handoff["open_issues"] = normalize_open_issues(handoff["open_issues"])
    return state


def legacy_provider_binding(engine):
    name = validate_engine(engine)
    task_kind = engine.get("task_kind", "feature")
    if name == "pdlc-v1":
        root = require_string(engine.get("pdlc_root"), "engine.pdlc_root")
        task_kind = engine.get("task_kind")
        metadata = pdlc_metadata(root, task_kind, engine.get("provider_manifest"))
        workflow = provider_reference(
            "pdlc-v1",
            task_kind,
            version=metadata["provider_version"],
            manifest=metadata["provider_manifest"],
            manifest_fingerprint=metadata["provider_fingerprint"],
            root=str(Path(root).expanduser().resolve()),
            source_fingerprint=metadata["provider_source_fingerprint"],
        )
        stages = {}
    else:
        workflow = provider_reference("native-v1", task_kind)
        stages = {}
        if name != "native-v1":
            path = require_string(engine.get("tdd_skill_path"), "engine.tdd_skill_path")
            stages["tdd"] = provider_reference(
                name,
                task_kind,
                source_path=str(Path(path).expanduser().resolve()),
                source_fingerprint=engine.get("tdd_skill_fingerprint"),
            )
    binding = {
        "controller": "converge",
        "workflow_provider": workflow,
        "stage_providers": stages,
    }
    return {
        "selection": engine.get("selection"),
        "reason": engine.get("reason"),
        "task_kind": task_kind,
        "binding": binding,
        "binding_fingerprint": canonical_fingerprint(binding),
    }


def validate_engine(value):
    engine = require_mapping(value, "engine")
    name = engine.get("name")
    if name not in load_provider_registry():
        raise ValueError("engine.name is invalid")
    if engine.get("selection") not in ENGINE_SELECTIONS:
        raise ValueError("engine.selection must be auto or explicit")
    require_string(engine.get("reason"), "engine.reason")
    if name == "pdlc-v1":
        root = require_string(engine.get("pdlc_root"), "engine.pdlc_root")
        if not Path(root).is_absolute():
            raise ValueError("engine.pdlc_root must be absolute")
        require_string(engine.get("feature_id"), "engine.feature_id")
        task_kind = engine.get("task_kind")
        if task_kind not in TASK_KINDS:
            raise ValueError("engine.task_kind must be feature, fix, or refactor")
        fingerprint = require_string(engine.get("pdlc_fingerprint"), "engine.pdlc_fingerprint")
        compatible, problem = compatible_root(root, task_kind, engine.get("provider_manifest"))
        if not compatible:
            raise ValueError(f"frozen PDLC capability is unavailable or changed: {problem or root}")
        metadata = pdlc_metadata(compatible, task_kind, engine.get("provider_manifest"))
        for field, expected in metadata.items():
            if engine.get(field) != expected:
                raise ValueError(f"frozen PDLC provider {field} is unavailable or changed")
        if fingerprint not in {
            pdlc_fingerprint(compatible, task_kind, engine.get("provider_manifest")),
            legacy_pdlc_fingerprint(compatible, task_kind),
        }:
            raise ValueError("frozen PDLC capability is unavailable or changed")
    else:
        if any(
            field in engine
            for field in ("pdlc_root", "feature_id", "task_kind", "pdlc_fingerprint")
        ):
            raise ValueError("TDD engine must not carry PDLC state")
        if name == "native-v1":
            if "tdd_skill_path" in engine or "tdd_skill_fingerprint" in engine:
                raise ValueError("native engine must not carry a third-party TDD skill")
        else:
            path = require_string(engine.get("tdd_skill_path"), "engine.tdd_skill_path")
            if not Path(path).is_absolute():
                raise ValueError("engine.tdd_skill_path must be absolute")
            fingerprint = require_string(
                engine.get("tdd_skill_fingerprint"), "engine.tdd_skill_fingerprint"
            )
            if not compatible_tdd_provider(name, path, fingerprint):
                raise ValueError("frozen third-party TDD skill is unavailable or changed")
    return name


def validate_provider_reference(reference, expected_role, task_kind):
    reference = require_mapping(reference, "provider reference")
    if "contract_fingerprint" in reference:
        provider_id = validate_complete_provider_reference(reference, task_kind, expected_role)
        manifest_path = Path(reference["manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_provider_manifest(manifest, manifest_path)
        if task_kind not in manifest["capabilities"]["task_kinds"]:
            raise ValueError("provider does not support the frozen task kind")
        return provider_id
    allowed = {
        "id", "version", "role", "manifest", "manifest_fingerprint",
        "source_path", "source_fingerprint", "root",
    }
    if set(reference) - allowed:
        raise ValueError("provider reference contains unsupported fields")
    provider_id = require_string(reference.get("id"), "provider reference.id")
    if provider_id not in load_provider_registry():
        raise ValueError("provider reference.id is unknown")
    if reference.get("role") != expected_role:
        raise ValueError("provider reference.role is invalid")
    require_string(reference.get("version"), "provider reference.version")
    manifest_path = Path(require_string(reference.get("manifest"), "provider reference.manifest"))
    if not manifest_path.is_absolute() or file_fingerprint(manifest_path) != reference.get(
        "manifest_fingerprint"
    ):
        raise ValueError("frozen provider manifest is unavailable or changed")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("frozen provider manifest is unavailable or changed") from error
    validate_provider_manifest(manifest, manifest_path)
    if (
        manifest["provider"]["id"] != provider_id
        or manifest["provider"]["version"] != reference["version"]
        or manifest["provider"]["role"] != reference["role"]
    ):
        raise ValueError("frozen provider identity changed")
    if task_kind not in manifest["capabilities"]["task_kinds"]:
        raise ValueError("provider does not support the frozen task kind")
    source_path = reference.get("source_path")
    if source_path is not None:
        path = Path(require_string(source_path, "provider reference.source_path"))
        if not path.is_absolute() or file_fingerprint(path) != reference.get("source_fingerprint"):
            raise ValueError("frozen provider source is unavailable or changed")
    if expected_role == "workflow" and provider_id != "native-v1":
        root = require_string(reference.get("root"), "provider reference.root")
        metadata = pdlc_metadata(root, task_kind, str(manifest_path))
        if metadata["provider_source_fingerprint"] != reference.get("source_fingerprint"):
            raise ValueError("frozen provider source is unavailable or changed")
    return provider_id


def validate_provider_binding(value):
    value = require_mapping(value, "provider_binding")
    if set(value) != {"selection", "reason", "task_kind", "binding", "binding_fingerprint"}:
        raise ValueError("provider_binding fields are invalid")
    if value.get("selection") not in ENGINE_SELECTIONS:
        raise ValueError("provider_binding.selection must be auto or explicit")
    require_string(value.get("reason"), "provider_binding.reason")
    task_kind = value.get("task_kind")
    if task_kind not in TASK_KINDS:
        raise ValueError("provider_binding.task_kind is invalid")
    binding = require_mapping(value.get("binding"), "provider_binding.binding")
    if set(binding) != {"controller", "workflow_provider", "stage_providers"}:
        raise ValueError("provider_binding.binding fields are invalid")
    if binding.get("controller") != "converge":
        raise ValueError("provider binding controller must be converge")
    workflow = validate_provider_reference(binding.get("workflow_provider"), "workflow", task_kind)
    stages = require_mapping(binding.get("stage_providers"), "provider_binding.stage_providers")
    if set(stages) - {"tdd"}:
        raise ValueError("provider stage is invalid")
    for stage, reference in stages.items():
        provider_id = validate_provider_reference(reference, "stage", task_kind)
        if stage not in load_provider_registry()[provider_id]["capabilities"]["stages"]:
            raise ValueError("provider stage capability is invalid")
    if workflow != "native-v1" and stages:
        raise ValueError("external workflow cannot mix stage providers")
    if value.get("binding_fingerprint") != canonical_fingerprint(binding):
        raise ValueError("provider binding fingerprint changed")
    return workflow


def require_sha256(value, name, *, optional=False):
    if optional and value is None:
        return None
    value = require_string(value, name)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{name} must be a lowercase sha256")
    return value


def _path_contains(owner, changed):
    return owner == "." or changed == owner or changed.startswith(owner + "/")


def validate_execution_control(value, source_fingerprint, task_key=None):
    value = require_mapping(value, "execution_control")
    if set(value) != {"routing", "review"}:
        raise ValueError("execution_control fields are invalid")
    routing = require_mapping(value["routing"], "execution_control.routing")
    legacy_routing_fields = {
        "schema_version", "status", "assessment_count", "route", "review_tier",
        "profile_fingerprint",
    }
    frozen_routing_fields = {
        *legacy_routing_fields, "profile", "allowed_paths", "integration_required",
    }
    if set(routing) not in {frozenset(legacy_routing_fields), frozenset(frozen_routing_fields)}:
        raise ValueError("execution_control.routing fields are invalid")
    count = routing["assessment_count"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > 2:
        raise ValueError("routing assessment_count must be from 0 to 2")
    if routing["schema_version"] == 2:
        if routing["status"] != "frozen" or set(routing) != frozen_routing_fields:
            raise ValueError("routing v2 must contain one frozen decision")
        expected = freeze_routing(
            routing.get("profile"), routing.get("allowed_paths"), count
        )
        if routing != expected:
            raise ValueError("routing does not match the canonical task profile")
    elif routing["schema_version"] != 1:
        raise ValueError("execution_control.routing schema_version is invalid")
    elif routing["status"] == "frozen":
        if count not in {1, 2} or routing["route"] not in ROUTES \
                or routing["review_tier"] not in REVIEW_TIERS:
            raise ValueError("routing must contain one frozen decision")
        require_sha256(routing["profile_fingerprint"], "routing.profile_fingerprint")
    elif routing != legacy_execution_control()["routing"]:
        raise ValueError("routing status is invalid")

    review = require_mapping(value["review"], "execution_control.review")
    if set(review) != {
        "protocol_version", "repair_budget_remaining", "re_review_budget_remaining",
        "integration_budget_remaining", "rounds",
    } or review["protocol_version"] != 3:
        raise ValueError("execution_control.review fields are invalid")
    for field in (
        "repair_budget_remaining", "re_review_budget_remaining", "integration_budget_remaining"
    ):
        if review[field] not in {0, 1}:
            raise ValueError(f"review {field} must be 0 or 1")
    rounds = review["rounds"]
    if not isinstance(rounds, list):
        raise ValueError("review rounds must be a list")
    for round_value in rounds:
        if not isinstance(round_value, dict) or set(round_value) != {
            "source_fingerprint", "requests"
        }:
            raise ValueError("review round fields are invalid")
        round_source = require_sha256(round_value["source_fingerprint"], "review round source")
        if not isinstance(round_value["requests"], list):
            raise ValueError("review requests must be a list")
        for request in round_value["requests"]:
            legacy_request_fields = {
                "axis", "phase", "source_fingerprint", "status", "reviewer_ref",
                "mode", "independent", "finding_fingerprints",
            }
            bound_request_fields = {*legacy_request_fields, "task_id", "request_fingerprint"}
            if not isinstance(request, dict) or set(request) not in {
                frozenset(legacy_request_fields), frozenset(bound_request_fields)
            }:
                raise ValueError("review request fields are invalid")
            if "request_fingerprint" in request:
                require_sha256(request["request_fingerprint"], "review request fingerprint")
                require_string(request["task_id"], "review request task_id")
                if task_key is not None and request["task_id"] != task_key:
                    raise ValueError("review request task_id must match the current task")
            if request["axis"] not in {"spec", "quality", "integration"} \
                    or request["phase"] not in {"initial", "re_review", "closure"} \
                    or request["status"] not in {"pass", "findings", "blocked"} \
                    or request["mode"] not in {"shared", "blind"} \
                    or not isinstance(request["independent"], bool):
                raise ValueError("review request value is invalid")
            if round_source == source_fingerprint \
                    and request["phase"] == "initial" \
                    and request["axis"] in {"quality", "integration"} \
                    and (request["mode"] != "blind" or not request["independent"]):
                raise ValueError(
                    f"initial {request['axis']} review must be independent blind"
                )
            require_string(request["reviewer_ref"], "review request reviewer_ref")
            findings = request["finding_fingerprints"]
            if not isinstance(findings, list) or len(findings) != len(set(findings)) or any(
                require_sha256(item, "review finding") is None for item in findings
            ):
                raise ValueError("review finding_fingerprints are invalid")
            if request["status"] == "findings" and not findings:
                raise ValueError("review findings require finding fingerprints")
            if require_sha256(request["source_fingerprint"], "review request source") != round_source:
                raise ValueError("review request source must match its round")
    if rounds and rounds[-1]["source_fingerprint"] != source_fingerprint:
        raise ValueError("current review round must match the current source")
    integration_requests = [
        request for round_value in rounds for request in round_value["requests"]
        if request["axis"] == "integration"
    ]
    if routing["schema_version"] == 2:
        if routing["integration_required"]:
            expected_budget = 0 if integration_requests else 1
            if review["integration_budget_remaining"] != expected_budget:
                raise ValueError("integration review budget does not match the frozen task profile")
        elif review["integration_budget_remaining"] or integration_requests:
            raise ValueError("integration review is not allowed by the frozen task profile")
    return routing, review


def validate_review_gate(routing, review, workers, task_key):
    tier = routing["review_tier"]
    requests = review["rounds"][-1]["requests"] if review["rounds"] else []
    latest = {}
    positions = {}
    for position, request in enumerate(requests):
        latest[request["axis"]] = request
        positions[request["axis"]] = position
    required_axes = []
    if tier != "low":
        required_axes.extend(("spec", "quality"))
        if not {"spec", "quality"} <= set(latest) \
                or any(latest[axis]["status"] != "pass" for axis in ("spec", "quality")):
            raise ValueError(f"{tier} review requires current spec and quality passes")
        if positions["spec"] >= positions["quality"]:
            raise ValueError("review must pass spec before quality")
        if latest["quality"]["mode"] != "blind" or not latest["quality"]["independent"]:
            raise ValueError("quality review requires an independent blind pass")
        if tier == "high" and (
            latest["spec"]["mode"] != "blind" or not latest["spec"]["independent"]
        ):
            raise ValueError("high review requires independent blind spec and quality passes")
    if review["integration_budget_remaining"]:
        raise ValueError("integration review is still required")
    if "integration" in latest:
        required_axes.append("integration")
        if latest["integration"]["status"] != "pass":
            raise ValueError("integration review requires a current pass")
    if required_axes:
        if any(
            request.get("task_id") != task_key or not request.get("request_fingerprint")
            for request in (latest[axis] for axis in required_axes)
        ):
            raise ValueError("review pass must be bound to the frozen review request")
        if tier != "low" and latest["spec"]["reviewer_ref"] != latest["quality"]["reviewer_ref"]:
            raise ValueError("current spec and quality axes must use one reviewer")
        reviewer_refs = {latest[axis]["reviewer_ref"] for axis in required_axes}
        completed_reviewers = {
            worker["ref"] for worker in workers
            if worker["role"] == "reviewer" and worker["status"] == "completed"
        }
        if not reviewer_refs <= completed_reviewers:
            raise ValueError("review pass requires a registered completed reviewer")


def validate_state(state, arguments):
    source_schema = state.get("schema_version") if isinstance(state, dict) else None
    strict_evidence = getattr(arguments, "strict_evidence", source_schema == 10)
    state = upgrade_state(state)

    controller = require_mapping(state.get("controller"), "controller")
    allowed_controller = {"package_version", "protocol_version", "protocol_fingerprint"}
    if frozenset(controller) not in {
        frozenset(allowed_controller), frozenset((*allowed_controller, "snapshot"))
    }:
        raise ValueError("controller fields are invalid")
    require_string(controller.get("package_version"), "controller.package_version")
    if "snapshot" in controller:
        frozen = validate_snapshot(controller["snapshot"])
        if any(
            controller.get(field) != frozen[field]
            for field in ("package_version", "protocol_version", "protocol_fingerprint")
        ):
            raise ValueError("frozen Converge controller snapshot changed")
    else:
        current_controller = controller_identity()
        if any(
            controller.get(field) != current_controller[field]
            for field in ("protocol_version", "protocol_fingerprint")
        ):
            raise ValueError("frozen Converge controller protocol changed")

    run_id = require_string(state.get("run_id"), "run_id")
    repo_id = require_string(state.get("repo_id"), "repo_id")
    if not Path(repo_id).is_absolute():
        raise ValueError("repo_id must be absolute")
    task_key = require_string(state.get("task_key"), "task_key")
    writer_id = require_string(state.get("writer_id"), "writer_id")
    revision = state.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise ValueError("revision must be a non-negative integer")
    workspace = require_string(state.get("workspace"), "workspace")
    if not Path(workspace).is_absolute():
        raise ValueError("workspace must be absolute")
    baseline = require_mapping(state.get("baseline"), "baseline")
    require_string(baseline.get("commit"), "baseline.commit")
    require_string(baseline.get("diff_fingerprint"), "baseline.diff_fingerprint")
    scope_fingerprint = require_string(state.get("scope_fingerprint"), "scope_fingerprint")
    source_fingerprint = require_sha256(
        state.get("source_fingerprint"), "source_fingerprint", optional=True
    )
    source_receipt = state.get("source_receipt")
    if source_receipt is not None:
        validate_source_receipt(source_receipt)
        if source_receipt["source_fingerprint"] != source_fingerprint \
                or source_receipt["baseline_commit"] != baseline["commit"]:
            raise ValueError("source_receipt does not match state source and baseline")
        if workspace_source(workspace, baseline["commit"]) != source_receipt:
            raise ValueError("source_receipt does not match the current workspace")
    routing, review_control = validate_execution_control(
        state.get("execution_control"), source_fingerprint, task_key
    )
    if source_receipt is not None and routing["schema_version"] == 2:
        allowed_paths = routing["allowed_paths"]
        drift = [
            path for path in source_receipt["changed_paths"]
            if not any(_path_contains(owner, path) for owner in allowed_paths)
        ]
        if drift:
            raise ValueError(f"source scope drift: {drift[0]}")
        undeclared_risks = infer_path_risks(source_receipt["changed_paths"]) - set(
            routing["profile"]["risk_flags"]
        )
        if undeclared_risks:
            raise ValueError(
                f"source risk exceeds the frozen task profile: {sorted(undeclared_risks)[0]}"
            )
    workflow_provider = validate_provider_binding(state.get("provider_binding"))
    runtime_binding = state.get("runtime_binding")
    if runtime_binding is not None:
        validate_runtime_binding(runtime_binding)
    host_sync = require_mapping(state.get("host_sync"), "host_sync")
    if set(host_sync) != {"mode", "acknowledged_fingerprint", "evidence_level"} \
            or host_sync["mode"] not in {"native", "text", "legacy_unavailable"}:
        raise ValueError("host_sync fields are invalid")
    if host_sync["evidence_level"] not in {"host_observed", "controller_attested"}:
        raise ValueError("host_sync evidence_level is invalid")
    acknowledged = host_sync["acknowledged_fingerprint"]
    if acknowledged is not None:
        require_sha256(acknowledged, "host_sync.acknowledged_fingerprint")
    if host_sync["mode"] != "native" and acknowledged is not None:
        raise ValueError("non-native host_sync cannot acknowledge a native projection")
    if acknowledged is not None and host_sync["evidence_level"] != "host_observed":
        raise ValueError("native plan acknowledgement must be host-observed")
    workers = state.get("workers")
    if not isinstance(workers, list):
        raise ValueError("workers must be a list")
    worker_refs = set()
    for worker in workers:
        if not isinstance(worker, dict) or set(worker) != {
            "ref", "parent_ref", "task_id", "depth", "may_dispatch",
            "role", "owner_run_id", "status", "progress"
        }:
            raise ValueError("workers[] fields are invalid")
        ref = require_string(worker.get("ref"), "workers[].ref")
        require_string(worker.get("role"), "workers[].role")
        require_string(worker.get("task_id"), "workers[].task_id")
        if worker["task_id"] != task_key:
            raise ValueError("workers[].task_id must match task_key")
        if worker.get("parent_ref") is not None:
            raise ValueError("workers must be controller-owned leaves")
        if worker.get("depth") != 1 or worker.get("may_dispatch") is not False:
            raise ValueError("workers must be non-dispatching leaves")
        if ref in worker_refs:
            raise ValueError("workers[].ref must be unique")
        worker_refs.add(ref)
        if worker.get("owner_run_id") != run_id:
            raise ValueError("workers[] may only belong to the current run")
        if worker.get("status") not in WORKER_STATUSES:
            raise ValueError("workers[].status is invalid")
        progress = worker.get("progress")
        if progress is not None:
            if not isinstance(progress, dict) or set(progress) != {
                "sequence", "objective_revision", "event", "phase", "milestone",
                "activity", "evidence", "evidence_level", "next_action", "observed_at",
            }:
                raise ValueError("workers[].progress fields are invalid")
            if (
                not isinstance(progress["sequence"], int)
                or isinstance(progress["sequence"], bool)
                or progress["sequence"] < 1
            ):
                raise ValueError("workers[].progress.sequence is invalid")
            if (
                not isinstance(progress["objective_revision"], int)
                or isinstance(progress["objective_revision"], bool)
                or progress["objective_revision"] < 0
            ):
                raise ValueError("workers[].progress.objective_revision is invalid")
            if progress["objective_revision"] > progress["sequence"]:
                raise ValueError("workers[].progress objective revision is invalid")
            if progress["event"] not in PROGRESS_EVENTS or progress["phase"] not in PROGRESS_PHASES:
                raise ValueError("workers[].progress event or phase is invalid")
            expected_level = (
                "host_observed" if progress["event"] == "heartbeat"
                else "controller_attested"
            )
            if progress["evidence_level"] != expected_level:
                raise ValueError("workers[].progress evidence_level is invalid")
            for field in ("milestone", "activity", "evidence", "next_action", "observed_at"):
                require_string(progress.get(field), f"workers[].progress.{field}")
    tree_receipt = state.get("worker_tree_receipt")
    if workers and runtime_binding is None:
        raise ValueError("workers require a frozen runtime binding")
    if workers and state.get("status") != "blocked" \
            and runtime_binding["evidence_level"] != "host_observed":
        raise ValueError("active workers require a host-observed runtime binding")
    if tree_receipt is not None:
        if not isinstance(tree_receipt, dict) or set(tree_receipt) != {
            "schema_version", "observed_revision", "observed_at", "runtime_fingerprint", "mode",
            "evidence_level", "observation_fingerprint", "registered_refs", "active_refs",
            "unexpected_refs",
        }:
            raise ValueError("worker tree receipt fields are invalid")
        if tree_receipt["schema_version"] != 2:
            raise ValueError("worker tree receipt schema_version must be 2")
        observed_revision = tree_receipt["observed_revision"]
        if (
            not isinstance(observed_revision, int)
            or isinstance(observed_revision, bool)
            or observed_revision < 0
            or observed_revision > revision
        ):
            raise ValueError("worker tree receipt observed_revision is invalid")
        if tree_receipt["mode"] not in {"tree_query", "restrict_dispatch"}:
            raise ValueError("worker tree receipt mode is invalid")
        require_string(tree_receipt.get("observed_at"), "worker tree receipt observed_at")
        if runtime_binding is None or tree_receipt["runtime_fingerprint"] != runtime_binding["binding_fingerprint"]:
            raise ValueError("worker tree receipt runtime fingerprint is invalid")
        expected_mode = (
            "tree_query" if "tree_query" in runtime_binding["capabilities"]
            else "restrict_dispatch"
        )
        if tree_receipt["mode"] != expected_mode:
            raise ValueError("worker tree receipt mode does not match the frozen runtime")
        observation_fingerprint = tree_receipt["observation_fingerprint"]
        if observation_fingerprint is not None:
            require_sha256(observation_fingerprint, "worker tree observation fingerprint")
        expected_level = "host_observed" if observation_fingerprint else "controller_attested"
        if observation_fingerprint is not None and expected_mode != "tree_query":
            raise ValueError("only a tree query can carry a host observation")
        if tree_receipt["evidence_level"] != expected_level:
            raise ValueError("worker tree receipt evidence_level is invalid")
        for field in ("registered_refs", "active_refs", "unexpected_refs"):
            refs = tree_receipt[field]
            if not isinstance(refs, list) or any(
                not isinstance(ref, str) or not ref.strip() for ref in refs
            ) or len(refs) != len(set(refs)):
                raise ValueError(f"worker tree receipt {field} is invalid")
        if set(tree_receipt["registered_refs"]) != worker_refs:
            raise ValueError("worker tree receipt does not match the registry")
        if not set(tree_receipt["active_refs"]) <= worker_refs:
            raise ValueError("worker tree receipt active_refs are invalid")
    ledger = require_mapping(state.get("ledger"), "ledger")
    completed_rounds = ledger.get("completed_rounds")
    if (
        not isinstance(completed_rounds, int)
        or isinstance(completed_rounds, bool)
        or completed_rounds < 0
        or completed_rounds > 2
    ):
        raise ValueError("ledger.completed_rounds must be an integer from 0 to 2")
    repair_fingerprints = ledger.get("repair_fingerprints")
    if not isinstance(repair_fingerprints, list) or not all(
        isinstance(item, str) and item.strip() for item in repair_fingerprints
    ):
        raise ValueError("ledger.repair_fingerprints must be a list of strings")
    if len(set(repair_fingerprints)) != len(repair_fingerprints):
        raise ValueError("ledger.repair_fingerprints must not contain duplicates")
    key_changes = ledger.get("key_changes", [])
    if not isinstance(key_changes, list) or len(key_changes) > 5 or not all(
        isinstance(item, str) and item.strip() and len(item) <= 120 for item in key_changes
    ):
        raise ValueError("ledger.key_changes must contain at most five short strings")
    checks = ledger.get("checks")
    if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
        raise ValueError("ledger.checks must be a list of objects")
    for item in checks:
        require_string(item.get("stage"), "ledger.checks[].stage")
        require_string(item.get("command"), "ledger.checks[].command")
        if item.get("result") not in CHECK_RESULTS:
            raise ValueError("ledger.checks[].result must be pass, fail, or unknown")
    acceptance = ledger.get("acceptance")
    if not isinstance(acceptance, list) or not all(isinstance(item, dict) for item in acceptance):
        raise ValueError("ledger.acceptance must be a list of objects")
    for item in acceptance:
        require_string(item.get("criterion"), "ledger.acceptance[].criterion")
        require_string(item.get("evidence"), "ledger.acceptance[].evidence")
        if item.get("result") not in CHECK_RESULTS:
            raise ValueError("ledger.acceptance[].result must be pass, fail, or unknown")
        if item.get("freshness") not in FRESHNESS:
            raise ValueError("ledger.acceptance[].freshness is invalid")
        require_sha256(
            item.get("source_fingerprint"),
            "ledger.acceptance[].source_fingerprint",
            optional=True,
        )
    acceptance_history = ledger.get("acceptance_history", [])
    if not isinstance(acceptance_history, list):
        raise ValueError("ledger.acceptance_history must be a list")
    for item in acceptance_history:
        if not isinstance(item, dict):
            raise ValueError("ledger.acceptance_history[] must be an object")
        history_revision = item.get("revision")
        if (
            not isinstance(history_revision, int)
            or isinstance(history_revision, bool)
            or history_revision < 0
        ):
            raise ValueError("ledger.acceptance_history[].revision must be non-negative")
        snapshot = require_mapping(item.get("acceptance"), "ledger.acceptance_history[].acceptance")
        require_string(snapshot.get("criterion"), "ledger.acceptance_history[].criterion")
        require_string(snapshot.get("evidence"), "ledger.acceptance_history[].evidence")
        if snapshot.get("result") not in CHECK_RESULTS:
            raise ValueError("ledger.acceptance_history[].result is invalid")
        if snapshot.get("freshness") not in FRESHNESS:
            raise ValueError("ledger.acceptance_history[].freshness is invalid")
        require_sha256(
            snapshot.get("source_fingerprint"),
            "ledger.acceptance_history[].source_fingerprint",
            optional=True,
        )
    report_history = ledger.get("report_history")
    if report_history is not None:
        if not isinstance(report_history, dict) or set(report_history) != {
            "last_outcome", "reported_fingerprints", "summary_fingerprint"
        }:
            raise ValueError("ledger.report_history fields are invalid")
        if report_history["last_outcome"] not in {
            "ready", "attention", "decision", "blocked"
        }:
            raise ValueError("ledger.report_history.last_outcome is invalid")
        fingerprints = report_history["reported_fingerprints"]
        if not isinstance(fingerprints, list) or any(
            not isinstance(item, str) or not item.strip() for item in fingerprints
        ) or len(fingerprints) != len(set(fingerprints)):
            raise ValueError("ledger.report_history.reported_fingerprints is invalid")
        summary = report_history["summary_fingerprint"]
        if summary != "none":
            require_sha256(summary, "ledger.report_history.summary_fingerprint")
    handoff = require_mapping(state.get("handoff"), "handoff")
    for field in ("goal", "last_verification", "next_action"):
        value = require_string(handoff.get(field), f"handoff.{field}")
        if len(value) > 500:
            raise ValueError(f"handoff.{field} must be at most 500 characters")
    open_issues = handoff.get("open_issues")
    if not isinstance(open_issues, list) or not all(
        isinstance(issue, str) and issue.strip() and len(issue) <= 500
        for issue in open_issues
    ) or len(open_issues) > 20:
        raise ValueError("handoff.open_issues must be a list of strings")

    if not isinstance(state.get("requires_stability_round"), bool):
        raise ValueError("requires_stability_round must be boolean")
    stage = state.get("current_stage")
    active_stages = NATIVE_ACTIVE_STAGES if workflow_provider == "native-v1" else PDLC_ACTIVE_STAGES
    if stage not in active_stages:
        raise ValueError("invalid current_stage")

    if getattr(arguments, "run_id", None) and arguments.run_id != run_id:
        raise ValueError("run_id does not match")
    if getattr(arguments, "repo_id", None) and arguments.repo_id != repo_id:
        raise ValueError("repo_id does not match")
    if getattr(arguments, "task_key", None) and arguments.task_key != task_key:
        raise ValueError("task_key does not match")
    if getattr(arguments, "writer_id", None) and arguments.writer_id != writer_id:
        raise ValueError("writer_id does not match")
    if getattr(arguments, "revision", None) is not None and arguments.revision != revision:
        raise ValueError("revision does not match")
    if getattr(arguments, "workspace", None) and arguments.workspace != workspace:
        raise ValueError("workspace does not match")
    if getattr(arguments, "baseline", None) and arguments.baseline != baseline["commit"]:
        raise ValueError("baseline does not match")
    if getattr(arguments, "scope_fingerprint", None) and arguments.scope_fingerprint != scope_fingerprint:
        raise ValueError("scope_fingerprint does not match")

    status = state.get("status")
    if status != "blocked" and (
        state.get("blocked_code") is not None or state.get("blocked_reason") is not None
    ):
        raise ValueError("blocked metadata is only valid for blocked state")
    if status == "complete":
        if routing["status"] != "frozen":
            raise ValueError("complete state requires a frozen route")
        if routing["schema_version"] != 2:
            raise ValueError("complete state requires canonical routing and scope")
        if source_fingerprint is None:
            raise ValueError("complete state requires a source_fingerprint")
        if strict_evidence and source_receipt is None:
            raise ValueError("complete state requires a source_receipt")
        if any(worker["status"] not in WORKER_TERMINAL_STATUSES for worker in workers):
            raise ValueError("complete state requires every current-run worker to reach host terminal status")
        validate_review_gate(routing, review_control, workers, task_key)
        if workers and tree_receipt is None:
            raise ValueError("complete state requires a fresh worker tree receipt")
        if tree_receipt is not None:
            validate_cleanup_barrier(tree_receipt, revision, worker_refs)
            if tree_receipt["evidence_level"] != "host_observed":
                raise ValueError("complete worker cleanup must be host-observed")
        if not acceptance or not all(
            item["result"] == "pass"
            and item["freshness"] == "fresh"
            and item.get("source_fingerprint") == source_fingerprint
            for item in acceptance
        ):
            raise ValueError("complete state requires fresh source-bound passing acceptance evidence")
        if strict_evidence and not all(
            valid_evidence_receipts(item.get("evidence_receipts"), source_receipt)
            for item in acceptance
        ):
            raise ValueError("complete state requires a passing Evidence Receipt for every acceptance")
        expected_final = "verify-final" if workflow_provider == "native-v1" else "pdlc-run"
        if stage != expected_final:
            raise ValueError("complete state must follow final verification")
        return "complete"
    if status == "blocked":
        if state.get("blocked_code") not in BLOCKED_CODES:
            raise ValueError("invalid blocked_code")
        require_string(state.get("blocked_reason"), "blocked_reason")
        if workers or tree_receipt is not None:
            if tree_receipt is None or tree_receipt["observed_revision"] != revision:
                raise ValueError("blocked state with workers requires a fresh cleanup receipt")
            working_refs = {worker["ref"] for worker in workers if worker["status"] == "working"}
            if set(tree_receipt["active_refs"]) != working_refs:
                raise ValueError("blocked cleanup receipt must list every active worker")
        return "blocked"
    if status != "active":
        raise ValueError("status must be active, complete, or blocked")

    if workflow_provider != "native-v1":
        return "pdlc-run"
    if stage == "scope":
        return "round-1-build"
    if stage == "round-1-build":
        return "round-1-semantic-review"
    if stage == "round-1-semantic-review":
        return "verify-round-1" if state["requires_stability_round"] else "verify-final"
    if stage == "verify-round-1":
        return "round-2-risk-review"
    if stage == "round-2-risk-review":
        return "verify-final"
    raise ValueError("verify-final must transition to complete or blocked before resume")


def validate_active_lease(state, arguments):
    paths = lease_paths(
        arguments.lease_root, state["repo_id"], state["workspace"], state["task_key"]
    )
    for path in paths.values():
        record = read_record(path)
        if not same_owner(record, arguments.run_id, arguments.writer_id) or is_expired(record):
            raise ValueError("active lease is not owned by this writer")


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--task-key")
    parser.add_argument("--writer-id")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--lease-root", default=str(DEFAULT_LEASE_ROOT))
    parser.add_argument("--workspace")
    parser.add_argument("--baseline")
    parser.add_argument("--scope-fingerprint")
    parser.add_argument("--format", choices=("json", "legacy"), default="json")
    arguments = parser.parse_args()

    state = None
    try:
        if not arguments.run_id or not arguments.writer_id or arguments.revision is None:
            raise ValueError("--run-id, --writer-id, and --revision are required")
        raw_state = json.loads(Path(arguments.state).read_text(encoding="utf-8"))
        arguments.strict_evidence = raw_state.get("schema_version") == 10
        state = raw_state
        state = upgrade_state(raw_state)
        next_stage = validate_state(state, arguments)
        validate_active_lease(state, arguments)
        projection_fingerprint = plan_projection_fingerprint(state)
        if state["host_sync"]["mode"] == "native" \
                and state["host_sync"]["acknowledged_fingerprint"] != projection_fingerprint:
            result = action(
                "sync-plan", task_id=state["task_key"],
                projection_fingerprint=projection_fingerprint,
            )
        else:
            result = delivery_action(next_stage, state["task_key"], state.get("blocked_reason"))
        print(legacy_action(result) if arguments.format == "legacy" else json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        task_id = (
            state.get("task_key") if isinstance(state, dict) else arguments.task_key
        ) or "unknown-task"
        result = action("block", task_id=task_id, reason=str(error))
        print("blocked" if arguments.format == "legacy" else json.dumps(result, sort_keys=True))
        print(f"delivery state blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
