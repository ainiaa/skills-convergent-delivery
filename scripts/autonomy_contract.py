"""Validate the optional autonomous-delivery state extension."""

from evidence_contract import valid_evidence_receipts
from delivery_next import require_mapping, require_sha256, require_string
from run_contract import action


AUTONOMY_ITEM_KINDS = {"requirement", "scope", "acceptance"}
AUTONOMY_BATCH_PHASES = {"initial", "re_audit"}
AUTONOMY_BATCH_STATUSES = {"pass", "findings", "blocked"}

def validate_action_attempts(value):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("autonomy action attempts are invalid")
    identifiers = set()
    for attempt in value:
        if not isinstance(attempt, dict) or set(attempt) != {
            "attempt_id", "action", "status", "owner", "time_policy", "events", "observation", "commit",
        }:
            raise ValueError("autonomy action attempt fields are invalid")
        identifier = require_string(attempt["attempt_id"], "autonomy action attempt id")
        if identifier in identifiers:
            raise ValueError("autonomy action attempt ids are duplicated")
        identifiers.add(identifier)
        action_value = attempt["action"]
        if not isinstance(action_value, dict) or not isinstance(action_value.get("action"), str):
            raise ValueError("autonomy action attempt action is invalid")
        try:
            if action(action_value["action"], **{
                key: item for key, item in action_value.items() if key != "action"
            }) != action_value:
                raise ValueError("autonomy action attempt action is invalid")
        except ValueError as error:
            raise ValueError("autonomy action attempt action is invalid") from error
        require_string(attempt["owner"], "autonomy action attempt owner")
        policy = require_mapping(attempt["time_policy"], "autonomy action attempt time policy")
        if set(policy) != {"startup_seconds", "idle_seconds", "absolute_seconds", "max_extensions"}:
            raise ValueError("autonomy action attempt time policy fields are invalid")
        for field in ("startup_seconds", "idle_seconds", "absolute_seconds", "max_extensions"):
            item = policy[field]
            if not isinstance(item, int) or isinstance(item, bool) or item < 0:
                raise ValueError("autonomy action attempt time policy is invalid")
        if not 1 <= policy["startup_seconds"] <= policy["idle_seconds"] <= policy["absolute_seconds"] <= 3600 \
                or policy["max_extensions"] > 3:
            raise ValueError("autonomy action attempt time policy is invalid")
        events = attempt["events"]
        if not isinstance(events, list) or len(events) > 32:
            raise ValueError("autonomy action attempt events are invalid")
        for event in events:
            if not isinstance(event, dict) or set(event) != {"kind", "at", "evidence_fingerprint"} \
                    or event["kind"] not in {"started", "progress", "terminated"}:
                raise ValueError("autonomy action attempt event is invalid")
            require_string(event["at"], "autonomy action attempt event time")
            require_sha256(event["evidence_fingerprint"], "autonomy action attempt event evidence")
        observation = attempt["observation"]
        commit = attempt["commit"]
        if observation is not None:
            if not isinstance(observation, dict) or set(observation) != {"outcome", "receipt_fingerprint"} \
                    or observation["outcome"] not in {"completed", "interrupted", "failed", "unknown"}:
                raise ValueError("autonomy action attempt observation is invalid")
            require_sha256(observation["receipt_fingerprint"], "autonomy action attempt receipt")
        if commit is not None:
            if not isinstance(commit, dict) or set(commit) != {
                "source_fingerprint", "verification_fingerprint"
            }:
                raise ValueError("autonomy action attempt commit is invalid")
            require_sha256(commit["source_fingerprint"], "autonomy action attempt commit source")
            require_sha256(commit["verification_fingerprint"], "autonomy action attempt verification")
        if attempt["status"] == "intent":
            valid = not events and observation is None and commit is None
        elif attempt["status"] == "running":
            valid = bool(events) and events[0]["kind"] == "started" and observation is None and commit is None
        elif attempt["status"] == "observed":
            valid = bool(events) and events[0]["kind"] == "started" and observation is not None and commit is None
        elif attempt["status"] == "committed":
            valid = bool(events) and events[0]["kind"] == "started" and observation is not None and commit is not None
        else:
            valid = False
        if not valid:
            raise ValueError("autonomy action attempt status is invalid")
    return value


def validate_autonomy(value, source_fingerprint, routing):
    value = require_mapping(value, "execution_control.autonomy")
    if set(value) != {
        "schema_version", "enabled", "manifest", "audit_batches",
        "repair_budget_remaining", "re_audit_budget_remaining", "runtime", "action_attempts",
    } or value["schema_version"] != 1 or value["enabled"] is not True:
        raise ValueError("autonomy fields are invalid")
    runtime = require_mapping(value["runtime"], "autonomy runtime")
    if runtime == {"mode": "hook"}:
        pass
    elif set(runtime) in ({"mode", "runner_profile", "max_cycles", "verification_argv", "audit_argv"},
                          {"mode", "runner_profile", "max_cycles", "verification_argv", "audit_argv", "audit_findings_exit_code"}) \
            and runtime["mode"] == "service":
        from worker_profile import validate_worker_profile
        profile = validate_worker_profile(runtime["runner_profile"])
        if profile["role"] != "implementer" or profile["permissions"] != {
            "workspace": "write", "shell": True, "network": "egress",
        } or not isinstance(runtime["max_cycles"], int) or not 1 <= runtime["max_cycles"] <= 8:
            raise ValueError("autonomy service runtime is invalid")
        verifier = runtime["verification_argv"]
        audit = runtime["audit_argv"]
        if not isinstance(verifier, list) or not verifier or any(
                not isinstance(item, str) or not item.strip() for item in verifier
        ) or not isinstance(audit, list) or not audit or any(
                not isinstance(item, str) or not item.strip() for item in audit
        ) or audit == verifier:
            raise ValueError("autonomy service verifier argv is invalid")
        findings_code = runtime.get("audit_findings_exit_code")
        if findings_code is not None and (
                not isinstance(findings_code, int) or isinstance(findings_code, bool)
                or not 1 <= findings_code <= 255
        ):
            raise ValueError("autonomy service audit findings exit code is invalid")
        if routing["review_tier"] != "low":
            raise ValueError("autonomy service requires a low-risk route")
    else:
        raise ValueError("autonomy runtime is invalid")
    validate_action_attempts(value["action_attempts"])
    manifest = require_mapping(value["manifest"], "autonomy manifest")
    if set(manifest) != {"source_fingerprint", "items"}:
        raise ValueError("autonomy manifest fields are invalid")
    require_sha256(manifest["source_fingerprint"], "autonomy manifest source")
    items = manifest["items"]
    if not isinstance(items, list) or not items or len(items) > 40:
        raise ValueError("autonomy manifest items are invalid")
    identifiers = []
    scope_values = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "kind", "value"}:
            raise ValueError("autonomy manifest item fields are invalid")
        identifier = require_string(item["id"], "autonomy manifest item id")
        kind = item["kind"]
        value_text = require_string(item["value"], "autonomy manifest item value")
        if len(identifier) > 80 or len(value_text) > 500 or kind not in AUTONOMY_ITEM_KINDS:
            raise ValueError("autonomy manifest item is invalid")
        identifiers.append(identifier)
        if kind == "scope":
            scope_values.add(value_text)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("autonomy manifest item ids are invalid")
    if not {"requirement", "scope", "acceptance"} <= {item["kind"] for item in items}:
        raise ValueError("autonomy manifest must cover requirement, scope, and acceptance")
    if scope_values != set(routing["allowed_paths"]):
        raise ValueError("autonomy manifest scope does not match frozen routing")
    for field in ("repair_budget_remaining", "re_audit_budget_remaining"):
        if value[field] not in {0, 1}:
            raise ValueError(f"autonomy {field} must be 0 or 1")
    batches = value["audit_batches"]
    if not isinstance(batches, list) or len(batches) > 2:
        raise ValueError("autonomy audit batches are invalid")
    previous = None
    required_ids = set(identifiers)
    for batch in batches:
        if not isinstance(batch, dict) or set(batch) != {
            "source_fingerprint", "phase", "status", "covered_manifest_ids", "finding_fingerprints",
            "evidence_receipt_fingerprint",
        }:
            raise ValueError("autonomy audit batch fields are invalid")
        batch_source = require_sha256(batch["source_fingerprint"], "autonomy audit source")
        require_sha256(batch["evidence_receipt_fingerprint"], "autonomy audit evidence receipt")
        if batch["phase"] not in AUTONOMY_BATCH_PHASES or batch["status"] not in AUTONOMY_BATCH_STATUSES:
            raise ValueError("autonomy audit batch is invalid")
        covered = batch["covered_manifest_ids"]
        findings = batch["finding_fingerprints"]
        if not isinstance(covered, list) or len(covered) != len(set(covered)) or not set(covered) <= required_ids:
            raise ValueError("autonomy audit coverage is invalid")
        if not isinstance(findings, list) or len(findings) != len(set(findings)) \
                or any(require_sha256(item, "autonomy finding") is None for item in findings):
            raise ValueError("autonomy audit findings are invalid")
        if batch["status"] == "pass" and (set(covered) != required_ids or findings):
            raise ValueError("autonomy audit pass requires full coverage")
        if batch["status"] == "findings" and not findings:
            raise ValueError("autonomy audit findings require fingerprints")
        if previous is None and batch["phase"] != "initial":
            raise ValueError("autonomy audit must start with initial")
        if previous is not None:
            if batch["phase"] != "re_audit" or previous["status"] != "findings" \
                    or batch_source == previous["source_fingerprint"]:
                raise ValueError("autonomy re_audit requires repaired findings and new source")
        previous = batch
    if len(batches) == 2 and (
        value["repair_budget_remaining"] != 0 or value["re_audit_budget_remaining"] != 0
    ):
        raise ValueError("autonomy re_audit must consume both budgets")
    return value


def validate_autonomy_completion(autonomy, source_fingerprint, source_receipt, checks):
    batches = autonomy["audit_batches"]
    if not batches or batches[-1]["source_fingerprint"] != source_fingerprint \
            or batches[-1]["status"] != "pass":
        raise ValueError("autonomy requires a current passing audit")
    if not autonomy["action_attempts"] or autonomy["action_attempts"][-1]["status"] != "committed":
        raise ValueError("autonomy requires a committed action")
    if source_receipt is None or not any(
            item.get("stage") == "autonomy-audit" and item.get("result") == "pass"
            and valid_evidence_receipts(item.get("evidence_receipts"), source_receipt)
            and any(
                receipt["receipt_fingerprint"] == batches[-1]["evidence_receipt_fingerprint"]
                and (
                    autonomy["runtime"]["mode"] != "service"
                    or receipt["argv"] == autonomy["runtime"]["audit_argv"]
                )
                for receipt in item["evidence_receipts"]
            )
            for item in checks
    ):
        raise ValueError("autonomy requires a current bound audit Evidence Receipt")
