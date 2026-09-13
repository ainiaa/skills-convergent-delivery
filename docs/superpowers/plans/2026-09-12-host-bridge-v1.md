# Host Bridge v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Converge model evaluation collect bounded, host-observed lifecycle receipts from real Codex Desktop and Claude Code evaluator tasks.

**Architecture:** Add a frozen `host-bridge-v1` contract that owns task identity, lifecycle transitions, and terminal receipts. Codex uses the local app-server JSON-RPC proxy with a schema fingerprint; Claude uses its named background-session CLI surface. The trusted evaluator prepares one disposable Git worktree per sample, launches the host task with a frozen package, then runs the frozen judge only after host-terminal observation.

**Tech Stack:** Python 3 standard library, Git worktrees, Codex app-server proxy JSON-RPC, Claude Code CLI, existing Controller Snapshot and unittest suites.

---

## File map

- Create: `scripts/host_bridge.py` — validates `host-bridge-v1` packages and receipts; performs bounded Codex and Claude lifecycle calls.
- Create: `scripts/test_host_bridge.py` — fake-host contract tests for lifecycle, identity, and failure semantics.
- Modify: `scripts/controller_snapshot.py` and `scripts/test_controller_snapshot.py` — freeze the bridge in a host-eval extension.
- Modify: `skills/converge-eval/scripts/eval_contract.py` and `skills/converge-eval/scripts/test_eval_kernel.py` — prepare packages, drive the bridge, and validate receipts.
- Modify: `skills/converge-eval/SKILL.md`, `skills/converge-eval/references/evaluation-contract.json`, and `CHANGELOG.md` — declare the feature and its unavailable behavior.

### Task 1: Freeze the host-bridge contract

**Files:**
- Create: `scripts/host_bridge.py`
- Create: `scripts/test_host_bridge.py`

- [ ] **Step 1: Write failing package and receipt contract tests**

~~~python
def test_package_binds_one_sample_to_one_host_and_worktree():
    package = host_bridge.package(
        host="codex", sample_id="known_acceptance:roots", workspace="/tmp/worktree",
        prompt="Run the frozen evaluator task.", judge_argv=["python3", "judge.py"],
        launch_fingerprint="a" * 64, host_fingerprint="b" * 64,
    )
    self.assertEqual("host-bridge-v1", package["protocol"])
    self.assertEqual("codex", package["host"])

def test_terminal_receipt_rejects_another_sample_or_missing_host_observation():
    with self.assertRaisesRegex(ValueError, "host observation"):
        host_bridge.finalize(valid_package(), {"status": "completed"}, {"exit_code": 0})
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_host_bridge.py`

Expected: FAIL because `host_bridge` does not exist.

- [ ] **Step 3: Write minimal implementation**

~~~python
PROTOCOL = "host-bridge-v1"
HOSTS = {"codex", "claude"}
TERMINAL = {"completed", "blocked", "interrupted", "failed"}

def package(*, host, sample_id, workspace, prompt, judge_argv, launch_fingerprint, host_fingerprint):
    return {
        "protocol": PROTOCOL, "host": require_host(host), "sample_id": require_text(sample_id),
        "workspace": require_absolute_directory(workspace), "prompt_fingerprint": digest_text(prompt),
        "judge_argv": require_argv(judge_argv), "launch_fingerprint": require_sha256(launch_fingerprint),
        "host_fingerprint": require_sha256(host_fingerprint),
    }

def finalize(package, observation, judge):
    return fingerprinted_receipt(
        validate_package(package), validate_terminal_observation(package, observation),
        validate_judge_result(package, judge),
    )
~~~

Keep the prompt itself out of persisted packages and receipts. Use standard-library JSON, hashing, subprocess, and time helpers only.

- [ ] **Step 4: Run tests to verify green**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_host_bridge.py && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_desktop_task_bridge.py`

Expected: both pass; no raw prompt or transcript appears in a receipt.

- [ ] **Step 5: Commit**

~~~bash
git add scripts/host_bridge.py scripts/test_host_bridge.py
git commit -m "feat: add host bridge contract"
~~~

### Task 2: Add Codex and Claude lifecycle adapters

**Files:**
- Modify: `scripts/host_bridge.py`
- Modify: `scripts/test_host_bridge.py`

- [ ] **Step 1: Write failing adapter tests**

~~~python
def test_codex_rejects_schema_drift_before_starting_a_thread():
    with self.assertRaisesRegex(ValueError, "schema changed"):
        host_bridge.codex_start(valid_package("codex"), schema="b" * 64, expected_schema="a" * 64)

def test_claude_observe_requires_the_exact_named_background_session():
    started = host_bridge.claude_start(valid_package("claude"), "frozen prompt", run=fake_claude_start)
    with self.assertRaisesRegex(ValueError, "exact session"):
        host_bridge.claude_observe(started, list_agents=lambda: [])
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_host_bridge.py`

Expected: FAIL because neither host adapter exists.

- [ ] **Step 3: Implement Codex app-server lifecycle calls**

~~~python
def codex_start(package, prompt, *, codex_bin="codex", request=proxy_request):
    schema = generated_schema_fingerprint(codex_bin)
    ensure_equal(schema, package["host_fingerprint"], "Codex app-server schema changed")
    thread = request(codex_bin, "thread/start", {"cwd": package["workspace"], "ephemeral": True})
    turn = request(codex_bin, "turn/start", {"threadId": thread["threadId"], "input": user_input(prompt)})
    return started_receipt(package, task_id=thread["threadId"], turn_id=turn["turnId"], host_fingerprint=schema)

def codex_observe(started, *, codex_bin="codex", request=proxy_request):
    return codex_terminal_observation(started, request(codex_bin, "thread/read", {"threadId": started["task_id"]}))

def start(package, prompt):
    return codex_start(package, prompt) if package["host"] == "codex" else claude_start(package, prompt)
~~~

`proxy_request` initializes one JSON-RPC connection, matches request IDs, rejects protocol errors and unknown status fields, and closes the process on every path. Only `thread/start`, `turn/start`, and `thread/read` are permitted.

- [ ] **Step 4: Implement Claude background-session lifecycle calls**

~~~python
def claude_start(package, prompt, *, claude_bin="claude", run=subprocess.run, list_agents=claude_agents):
    name = "converge-eval-" + package_fingerprint(package)[:24]
    before = known_session_ids(list_agents(claude_bin, package["workspace"]))
    run([claude_bin, "--background", "--name", name, prompt], cwd=package["workspace"])
    return started_receipt(package, task_id=require_new_exact_session(list_agents, before, name),
                           host_fingerprint=binary_fingerprint(claude_bin))

def claude_observe(started, *, claude_bin="claude", list_agents=claude_agents):
    return claude_terminal_observation(started, require_exact_session(list_agents, started))
~~~

Reuse `capsule_dispatch.claude_agents` only for strict JSON parsing. Do not reuse its dispatch receipt because its retry identity differs.

- [ ] **Step 5: Run tests to verify green**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_host_bridge.py && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_capsule_dispatch.py`

Expected: both pass; binary/schema drift, timeout, vanished task, and ambiguous identity produce `unavailable` or `unknown`, never pass.

- [ ] **Step 6: Commit**

~~~bash
git add scripts/host_bridge.py scripts/test_host_bridge.py
git commit -m "feat: add Codex and Claude host adapters"
~~~

### Task 3: Drive frozen evaluator packages through the trusted evaluator

**Files:**
- Modify: `skills/converge-eval/scripts/eval_contract.py`
- Modify: `skills/converge-eval/scripts/test_eval_kernel.py`
- Modify: `scripts/controller_snapshot.py`
- Modify: `scripts/test_controller_snapshot.py`

- [ ] **Step 1: Write failing evaluator tests**

~~~python
def test_preflight_requires_both_host_adapters_to_be_available(self):
    with patch("eval_contract.host_bridge.preflight", return_value={"codex": "ready", "claude": "unavailable"}):
        report = eval_contract.preflight()
    self.assertFalse(report["eligible"])
    self.assertEqual("unavailable_host_bridge", report["stop_reason"])

def test_evaluate_runs_the_frozen_judge_only_after_a_terminal_host_receipt(self):
    report = eval_contract.evaluate(valid_live_request(), ROOT)
    self.assertEqual("host_observed", report["evidence_level"])
    self.assertEqual("pass", report["sample_receipts"][0]["candidate_result"])
~~~

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-eval/scripts/test_eval_kernel.py`

Expected: FAIL because preflight is unconditional `uncovered` and `evaluate()` never launches a host package.

- [ ] **Step 3: Add frozen package collection**

~~~python
def collect_sample(snapshot, scenario, side, source_tree, request, deadline):
    with disposable_worktree(snapshot, source_tree) as workspace:
        package = host_bridge.package(
            host=request["host"], sample_id=f"{scenario['class']}:{scenario['id']}:{side}",
            workspace=workspace, prompt=render_frozen_prompt(snapshot, scenario, side),
            judge_argv=frozen_judge_argv(snapshot, scenario), launch_fingerprint=scenario["launch_fingerprint"],
            host_fingerprint=request["host_fingerprints"][request["host"]],
        )
        observation = host_bridge.wait_terminal(host_bridge.start(package, render_frozen_prompt(snapshot, scenario, side)), deadline)
        judge = run_frozen_judge(snapshot, workspace, package["judge_argv"], deadline)
        return host_bridge.finalize(package, observation, judge)
~~~

Use suite, judge, and prompt bytes only from `control_source` and the pre-candidate snapshot. Never run a candidate-supplied judge, reuse a host task, or retry an unknown task.

- [ ] **Step 4: Freeze the bridge in Controller Snapshot**

~~~python
HOST_EVALUATION_FILES = ("scripts/host_bridge.py", "scripts/test_host_bridge.py")
EXTENSION_ORDER = ("multimodel", "autonomy", "autonomy-eval", "host-eval")
EXTENSIONS["host-eval"] = (HOST_EVALUATION_FILES, ())
EXTENSION_DEPENDENCIES["host-eval"] = ("multimodel",)
~~~

Add snapshot assertions that `host-eval` includes the bridge and inherits `multimodel`, while the core snapshot remains unchanged.

- [ ] **Step 5: Run tests to verify green**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-eval/scripts/test_eval_kernel.py && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_controller_snapshot.py`

Expected: both pass; only a pre-candidate snapshot with `host-eval` may execute live collection.

- [ ] **Step 6: Commit**

~~~bash
git add skills/converge-eval/scripts/eval_contract.py skills/converge-eval/scripts/test_eval_kernel.py scripts/controller_snapshot.py scripts/test_controller_snapshot.py
git commit -m "feat: collect host-observed evaluator receipts"
~~~

### Task 4: Document availability and run bounded verification

**Files:**
- Modify: `skills/converge-eval/SKILL.md`
- Modify: `skills/converge-eval/references/evaluation-contract.json`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update frozen availability semantics**

Add `host`, `evaluator_package`, and `host_receipt` as live-evaluation inputs. State that both adapters must be capability-ready, Codex app-server is version-bound, and unsupported hosts remain `uncovered`.

- [ ] **Step 2: Add a documentation assertion**

~~~python
def test_eval_contract_documents_both_host_adapters(self):
    contract = json.loads((ROOT / "skills/converge-eval/references/evaluation-contract.json").read_text())
    self.assertEqual(["codex", "claude"], contract["host_bridge"]["supported_hosts"])
~~~

- [ ] **Step 3: Run complete deterministic verification**

Run: `PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_host_bridge.py && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_desktop_task_bridge.py && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_capsule_dispatch.py && PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_controller_snapshot.py && PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-eval/scripts/test_eval_kernel.py && PYTHONDONTWRITEBYTECODE=1 python3 skills/converge-eval/scripts/eval_contract.py --preflight && git diff --check`

Expected: all deterministic tests pass. Preflight is eligible only if both real host capabilities are present; otherwise it names the unavailable adapter and never claims readiness.

- [ ] **Step 4: Run explicit real-host smoke checks**

Run one frozen read-only evaluator package through each adapter in a disposable Git worktree. Verify distinct host task IDs, terminal host observations, frozen judge fingerprints, no prompt/transcript fields, and `evidence_level: host_observed`.

Expected: a host that cannot create or observe its task reports `uncovered`; no automatic retry occurs.

- [ ] **Step 5: Commit**

~~~bash
git add skills/converge-eval/SKILL.md skills/converge-eval/references/evaluation-contract.json CHANGELOG.md
git commit -m "docs: describe host-observed evaluation"
~~~
