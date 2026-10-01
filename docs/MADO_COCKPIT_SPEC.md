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
- workspace.merged
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
└─ cockpit/
   ├─ project.json
   ├─ missions/
   ├─ workers/
   └─ events.jsonl
```

This layout is intentionally small in MCC-M0.0 and expands as later milestones add evidence, handoffs, workspaces, and gates.

## Milestones

### MCC-M0.0 Skeleton

Deliver:

- Python package
- CLI
- Project model
- Mission model
- Worker model
- Event model
- local state store
- golden-path tests

Done when:

```text
mado-cockpit init
mado-cockpit mission create
mado-cockpit worker create
mado-cockpit status
```

all work against persistent local state.

### MCC-M0.1 Worktree Worker

Add:

- Git worktree creation
- deterministic branch naming
- workspace metadata
- workspace status
- cleanup

Golden fixture:

Two workers, two worktrees, one repository, zero collision.

### MCC-M0.2 Agent Session Adapter

First provider: Codex CLI.

Provider contract:

```python
class AgentProvider:
    def start(self): ...
    def send(self): ...
    def status(self): ...
    def stop(self): ...
```

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
