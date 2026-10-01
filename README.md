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
│  └─ events.jsonl
└─ worktrees/
   └─ <mission>-<worker>/
```

Raw session traces are operational records. MCC-M0.3 will add the formal Task / Result / Evidence contracts above them.

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

## Milestone path

1. **MCC-M0.0 Skeleton** — domain model, state store, CLI ✅
2. **MCC-M0.1 Worktree Worker** — isolated Git worktrees ✅
3. **MCC-M0.2 Agent Session Adapter** — Codex CLI first ✅
4. **MCC-M0.3 Evidence Return** — task/result/evidence contracts
5. **MCC-M0.4 Builder → QA Handoff** — independent validation loop
6. **MCC-M0.5 Operator** — agent-controlled cockpit
7. **MCC-M0.6 Capability Pager Bridge**
8. **MCC-M0.7 Human Question Gate**
9. **MCC-M0.8 Cockpit UI**

See [docs/MADO_COCKPIT_SPEC.md](docs/MADO_COCKPIT_SPEC.md).
