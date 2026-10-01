# MADO Cockpit

**MADO Cockpit** is the production control plane for MADO SYSTEM ONE.

It turns AI agents, workspaces, capabilities, evidence, and human decisions into one observable production team.

## Current spine

### MCC-M0.0 Skeleton

Established the control-plane domain model, local state store, Event Spine, and CLI.

### MCC-M0.1 Worktree Worker

Each worker receives an isolated Git branch and linked worktree.

```text
Mission
├─ builder
│  └─ .mado/worktrees/<mission>-builder
└─ qa
   └─ .mado/worktrees/<mission>-qa
```

### MCC-M0.2 Agent Session Adapter

A worker workspace can now host a durable **Codex CLI conversation**.

The adapter uses `codex exec --json` for the first turn and `codex exec ... resume <THREAD_ID>` for follow-up turns. Every turn runs with:

```text
sandbox_mode = workspace-write
approval_policy = never
```

The Codex process itself is turn-based. MADO Cockpit persists the conversation identity, session state, final message, exit status, and raw JSONL traces between invocations.

```text
Worker
  ↓
Worktree
  ↓
AgentSession
  ↓
Codex turn #1
  ↓ thread_id
Codex resume turn #2
  ↓
...
```

Cockpit rejects a resumed turn when the reported Codex thread ID differs from the stored thread ID. It also prevents two active sessions from owning the same worktree simultaneously.


### MCC-M0.3 Evidence Return

A worker's completion message is now only a claim. A task can move to `ready_for_qa` only when its required evidence kinds are present.

```text
Task Contract
  ↓
Worker / Codex Session
  ↓
Result Contract
  ├─ status = completed
  └─ summary = "done"
  ↓
Evidence Bundle
  ├─ git_diff
  ├─ test_result
  └─ session_trace
  ↓
required evidence complete?
  ├─ yes → ready_for_qa
  └─ no  → evidence_incomplete
```

Every evidence item is copied into the Cockpit evidence store and recorded with SHA-256 and byte size. Workspace files must resolve inside the assigned worker worktree. Session traces must belong to the same worker and workspace as the task.

Task contracts require at least one evidence kind, so evidence-first completion cannot be silently disabled.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"

mado-cockpit init
mado-cockpit mission create MCC-DEMO "Build the first cockpit fixture"

mado-cockpit worker create builder \
  --role builder \
  --mission MCC-DEMO \
  --provider codex

mado-cockpit workspace create builder
```

Make sure the local Codex CLI is already authenticated:

```bash
codex login status
```

Start the first agent turn inside the worker's worktree:

```bash
mado-cockpit session start builder \
  "Inspect this milestone and implement the smallest safe next step."
```

Inspect sessions and copy the returned Cockpit session ID:

```bash
mado-cockpit session list
mado-cockpit session status <SESSION_ID>
```

Continue the same Codex conversation:

```bash
mado-cockpit session send <SESSION_ID> \
  "Run the tests and summarize anything still missing."
```

Close the local Cockpit session between turns:

```bash
mado-cockpit session stop <SESSION_ID>
```

Create an evidence-first task contract:

```bash
mado-cockpit task create MCC-DEMO-BUILD builder \
  "Implement the smallest safe next step." \
  --require git_diff \
  --require test_result \
  --deliverable implementation \
  --deliverable tests \
  --done-when "required evidence is present"
```

After the worker has produced a test log inside its worktree, submit the result:

```bash
mado-cockpit result submit MCC-DEMO-BUILD \
  --status completed \
  --summary "Implementation and tests complete." \
  --evidence test_result=tests.txt \
  --change src/example.py
```

Cockpit automatically snapshots Git workspace changes as `git_diff`. If a session ID is supplied with `--session`, its last completed JSONL turn is bundled as `session_trace`.

Inspect the result:

```bash
mado-cockpit result list --task MCC-DEMO-BUILD
mado-cockpit evidence list --task MCC-DEMO-BUILD
mado-cockpit evidence inspect <BUNDLE_ID>
```

MCC-M0.2 does **not** pretend to interrupt an already-running Codex turn. `stop` closes a turn-based session only when no turn is executing.

## Local state

```text
.mado/
├─ cockpit/
│  ├─ project.json
│  ├─ missions/
│  ├─ workers/
│  ├─ workspaces/
│  ├─ sessions/
│  │  └─ <session-id>/
│  │     ├─ session.json
│  │     └─ traces/
│  │        ├─ turn-0001.jsonl
│  │        └─ turn-0002.jsonl
│  ├─ tasks/
│  ├─ results/
│  ├─ evidence/
│  │  └─ <task-id>/<bundle-id>/
│  │     ├─ manifest.json
│  │     ├─ task.json
│  │     ├─ result.json
│  │     └─ files/
│  └─ events.jsonl
└─ worktrees/
   └─ <mission>-<worker>/
```

Raw session traces remain operational records. MCC-M0.3 can bind the final trace into an Evidence Bundle when the Task Contract explicitly requires `session_trace`.

## MCC-M0.2 golden fixtures

The fixtures verify:

```text
Codex command runs inside the assigned worktree
JSONL thread.started is captured
follow-up uses the same external thread ID
thread drift is rejected
missing durable thread IDs fail closed
one active session owns one worktree
failed sessions can be replaced safely
```

The fixture uses an injected fake command runner, so CI does not consume Codex quota or require authentication.


## MCC-M0.3 golden fixtures

The evidence fixtures verify:

```text
completed + required evidence → ready_for_qa
completed + missing evidence  → incomplete
failed + complete evidence     → not_completed
workspace file escape          → rejected
session trace ownership        → enforced
task without evidence policy   → rejected
task/result snapshots          → frozen in bundle
SHA-256 / size metadata        → recorded
```

## Milestone path

1. **MCC-M0.0 Skeleton** — domain model, state store, CLI ✅
2. **MCC-M0.1 Worktree Worker** — isolated Git worktrees ✅
3. **MCC-M0.2 Agent Session Adapter** — Codex CLI first ✅
4. **MCC-M0.3 Evidence Return** — task/result/evidence contracts ✅
5. **MCC-M0.4 Builder → QA Handoff** — independent validation loop
6. **MCC-M0.5 Operator** — agent-controlled cockpit
7. **MCC-M0.6 Capability Pager Bridge**
8. **MCC-M0.7 Human Question Gate**
9. **MCC-M0.8 Cockpit UI**

See [docs/MADO_COCKPIT_SPEC.md](docs/MADO_COCKPIT_SPEC.md).
