# MADO_COCKPIT_SPEC.md

Version: 0.1  
Status: Draft  
Codename: MADO Cockpit

## Summary

MADO Cockpit is the production control plane for MADO SYSTEM ONE.

It coordinates AI workers, isolated workspaces, capabilities, evidence, QA, handoffs, and human decisions as one observable production team.

## Core principle

A worker is not merely a chat session.

A worker has:

- identity
- role
- mission
- workspace
- capabilities
- status
- outputs
- evidence
- handoff state

The cockpit manages workers as a team around a mission.

## v0.1 execution loop

```text
Human Intent
  ↓
Mission
  ↓
Team Formation
  ↓
Worker
  ↓
Workspace
  ↓
Capability Resolution
  ↓
Execution
  ↓
Evidence
  ↓
QA
  ↓
Human Question Gate
  ↓
Merge / Ship / Continue
```

## Design principles

1. Session-centric, not provider-centric.
2. Workspace isolation by default.
3. Evidence over claims.
4. Human attention is scarce.
5. Subscription-first execution.
6. Agents may operate the cockpit.
7. Important operations become events.

## Core domain model

### Project

Top-level production context.

### Mission

A concrete goal that may be decomposed across multiple workers.

### Team

The set of workers executing a mission.

### Worker

A role-bearing execution unit backed by a provider such as Codex CLI.

### Workspace

An isolated execution surface assigned to one worker.

MCC-M0.1 implements the first concrete workspace kind: `git_worktree`.

Workspace metadata includes:

- workspace id
- worker id
- mission id
- repository root
- linked worktree path
- branch
- base ref
- lifecycle status

### Agent Session

A durable conversation binding between a Worker, its Workspace, and an external agent provider.

MCC-M0.2 stores:

- Cockpit session ID
- worker ID
- workspace ID
- provider
- optional model override
- external provider session/thread ID
- lifecycle status
- completed turn count
- last exit code
- last assistant message
- last raw trace path
- last error

The external provider identity is never assumed from a successful exit code alone. For Codex resume turns, Cockpit verifies that the emitted thread ID matches the previously stored thread ID.

### Event

An append-only record of meaningful cockpit state transitions.

## Standard worker roles

- Lead
- Builder
- Researcher
- QA
- Reviewer
- Release

## Worker lifecycle

```text
created
  ↓
provisioning
  ↓
ready
  ↓
running
  ├→ blocked → resolving → running
  ↓
awaiting_gate
  ↓
completed
  ↓
archived
```

## Workspace policy

v0.1 prioritizes Git worktrees for parallel workers.

Future workspace types may include:

- shared
- git_worktree
- temp_directory
- container
- remote_workspace
- readonly

### MCC-M0.1 worktree contract

A workspace branch and directory are deterministic.

Given:

```text
mission = MCC-M0.1
worker = builder
```

Cockpit creates:

```text
branch:
cockpit/mcc-m0.1-builder

path:
.mado/worktrees/mcc-m0.1-builder
```

The worktree is created from `HEAD` by default. A caller may provide another base ref.

Creation fails instead of silently reusing an existing path or branch.

### Worktree lifecycle

```text
worker.created
  ↓
workspace create
  ↓
git worktree add
  ↓
workspace.created
  ↓
ready
  ↓
workspace status
  ↓
workspace remove
  ↓
git worktree prune
  ↓
workspace.removed
```

Branch deletion is explicit. Cleanup can remove only the linked worktree, or remove the branch as well.

## Capability model

Workers receive only the capabilities required by their mission.

```text
Mission
  ↓
Capability Requirements
  ↓
Capability Pager
  ↓
Policy / Cost / Availability
  ↓
Resolved Capability Set
  ↓
Worker
```

## Evidence model

A worker's claim of completion is not sufficient.

Mission-specific evidence may include:

- test results
- git diff
- build result
- screenshot
- fixture result
- benchmark
- generated artifact
- validation report

## Human Question Gate

Human escalation should happen only after automated recovery paths have been attempted.

```text
Retry
  ↓
Alternative Capability
  ↓
Alternative Worker
  ↓
Existing Evidence Search
  ↓
Human Question Gate
```

## Event spine

Initial canonical event types:

- project.opened
- mission.created
- mission.started
- mission.completed
- worker.created
- worker.started
- worker.blocked
- worker.completed
- worker.failed
- workspace.created
- workspace.removed
- workspace.merged
- session.created
- session.started
- session.turn.started
- session.turn.completed
- session.failed
- session.stopped
- capability.requested
- capability.resolved
- task.assigned
- evidence.created
- evidence.validated
- handoff.created
- gate.requested
- gate.resolved

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
│  └─ events.jsonl
└─ worktrees/
   ├─ <mission>-<worker>/
   └─ ...
```

## Milestones

### MCC-M0.0 Skeleton ✅

Delivered:

- Python package
- CLI
- Project model
- Mission model
- Worker model
- Event model
- local state store
- golden-path tests

### MCC-M0.1 Worktree Worker ✅

Delivered:

- Workspace domain model
- Git worktree manager
- deterministic workspace and branch naming
- worktree creation
- workspace metadata persistence
- Git status inspection
- cleanup and optional branch deletion
- workspace lifecycle events
- CLI create/list/status/remove commands
- two-worker isolation fixture

Golden fixture:

```text
2 workers
2 worktrees
1 repository
0 collision
```

The fixture writes independent uncommitted files into Builder and QA worktrees and verifies that neither workspace sees the other's file.

### MCC-M0.2 Agent Session Adapter ✅

First provider: Codex CLI.

Provider contract:

```python
class AgentProvider:
    def start(self): ...
    def send(self): ...
    def status(self): ...
    def stop(self): ...
```

Delivered:

- `AgentSession` domain model
- provider protocol
- injectable command runner
- Codex CLI provider
- turn-based Session Manager
- session persistence
- per-turn JSONL/stderr traces
- session lifecycle events
- CLI start/send/list/status/stop commands
- workspace ownership guard
- retry after failed session
- resume continuity validation

Codex command strategy:

```text
first turn:
codex exec --json
  -c sandbox_mode="workspace-write"
  -c approval_policy="never"
  <PROMPT>

follow-up:
codex exec --json
  -c sandbox_mode="workspace-write"
  -c approval_policy="never"
  resume <THREAD_ID> <PROMPT>
```

The subprocess working directory is always the assigned worker worktree.

MCC-M0.2 treats Codex as a **durable conversation with turn-scoped processes**, not as a persistent PTY. Between turns there is no child process to keep alive.

`stop` therefore closes the Cockpit session locally. It must not claim that it can interrupt an already-running turn.

### Resume continuity contract

A follow-up succeeds only when all of the following hold:

```text
process exit code == 0
thread.started exists
reported thread_id == stored external_session_id
```

If Codex returns a different thread ID, the session enters `failed` rather than silently accepting a fresh conversation.

### Workspace ownership contract

One ready worktree may have at most one session whose state is:

```text
active
running
```

Stopped or failed sessions do not permanently lock the workspace. A replacement session receives a fresh Cockpit session ID.

### M0.2 golden fixture

```text
Worker
  ↓
Worktree
  ↓
Codex start fixture
  ↓ thread-123
Codex resume fixture
  ↓ thread-123
Session active / turn_count=2
```

Additional negative fixtures verify missing thread IDs and thread drift.

CI uses an injected fake command runner. It never calls the real Codex service and consumes no model quota.

### MCC-M0.3 Evidence Return

Add:

- Task Contract
- Result Contract
- Evidence Bundle
- evidence events

### MCC-M0.4 Builder → QA Handoff

Complete the first production loop:

```text
Builder
  ↓
Evidence
  ↓
Handoff
  ↓
QA
  ↓
QA Result
```

First dogfood target: MADO Asset Foundry / MAF-M0.3 Image QA.

### MCC-M0.5 Operator

Allow a lead/operator agent to:

- create workers
- create workspaces
- assign tasks
- inspect workers
- read evidence
- create handoffs
- stop workers

### MCC-M0.6 Capability Pager Bridge

Connect worker needs to MADO SYSTEM ONE capability resolution.

### MCC-M0.7 Human Question Gate

Make human escalation inspectable and structured.

### MCC-M0.8 Cockpit UI

Only after the underlying control plane is stable, expose it in a graphical cockpit.

## Non-goals for v0.1

- fully autonomous company
- visual workflow editor
- unlimited agent spawning
- cloud-distributed execution
- complex provider routing
- production auto-deploy
- sophisticated billing optimization

The target is simpler:

> Run 2–4 workers safely in parallel and preserve enough evidence to understand what happened.

## North star

```text
Human
  ↓
Mission
  ↓
AI Production Team
  ↓
Evidence
  ↓
Product
```

The human should ultimately manage intent and decisions, not terminal windows.
