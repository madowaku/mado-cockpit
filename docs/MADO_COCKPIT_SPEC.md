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

### Task Contract

A structured assignment that binds a worker to a workspace and declares the evidence required before completion can advance.

A Task Contract includes:

- task ID
- worker ID
- workspace ID
- objective
- required evidence kinds
- constraints
- deliverables
- done-when conditions
- lifecycle status

MCC-M0.3 requires at least one `required_evidence` kind. A task without an evidence policy is rejected.

### Result Contract

The worker's structured statement about the attempt.

A Result Contract includes:

- result ID
- task ID
- worker/workspace IDs
- result status: `completed | blocked | failed`
- summary
- changes
- risks
- optional session ID
- evidence bundle ID
- evidence status
- readiness

The result status is a claim about work outcome. It does not prove completion.

### Evidence Bundle

A frozen package containing:

- Task Contract snapshot
- Result Contract snapshot
- evidence manifest
- copied evidence files
- SHA-256 and byte size for every evidence item

Evidence validation asks only whether the Task Contract's required evidence kinds are present. Work outcome and evidence completeness remain separate axes.

### Handoff Contract

An immutable transfer record from a source Builder task/result/evidence bundle to a separate QA worker and workspace.

It records:

- source task/result/bundle IDs
- source worker/workspace IDs
- QA worker/workspace IDs
- auto-created QA task ID
- materialized snapshot path
- snapshot SHA-256

The immutable contract is stored separately from mutable handoff status.

### QA Verdict

A final QA decision backed by a QA Result Contract with validated `qa_report` evidence.

Supported verdicts:

- `pass`
- `needs_fix`
- `blocked`

The verdict records the source snapshot digest that QA actually reviewed.

### Capability Descriptor

MCC-M0.6 mirrors the public MADO SYSTEM ONE capability descriptor contract.

A capability records:

- id
- kind
- name
- short/full description
- instructions reference
- availability
- prerequisites
- risk tags
- cost class
- metadata

Supported kinds match System One:

```text
skill
native_tool
plugin
mcp
cli
harness
adapter
browser
computer_use
```

### Capability Request

A Worker-scoped request describing the ability needed for a concrete task.

It records:

- request ID
- worker ID
- natural-language need
- trace ID
- metadata such as Operator, role, task, and mission

### Capability Suggestion

The advisory result returned by the Pager.

It mirrors System One:

- suggested capability
- confidence
- alternatives
- reason codes
- `advisoryOnly = true`
- wide trace ID
- optional deep trace ID

### Capability Resolution

Cockpit's policy result after reviewing the advisory suggestion.

It records:

- request ID
- worker ID
- resolved/unresolved/pager-error status
- selected capability
- original suggestion
- policy reasons

### Capability Binding

A durable Worker-to-capability binding created only after Cockpit policy permits the candidate.

Bindings are the execution boundary consumed by Operator launch.

### Recovery Attempt

A structured record of an automated recovery path tried before human escalation.

MCC-M0.7 standard strategies:

- `retry`
- `alternative_capability`
- `alternative_worker`
- `evidence_search`

Statuses are:

- `attempted`
- `succeeded`
- `failed`
- `unavailable`
- `no_match`
- `exhausted`

### Human Question Gate

An immutable, human-answerable decision request created only when the decision actually belongs to a human.

It records:

- gate ID
- mission / Operator / Worker / Task context
- question
- reason
- materiality
- choices
- per-choice impact
- optional recommendation
- optional safe default
- choose-for-me permission
- consent-required flag
- recovery attempts
- creation timestamp

### Gate Resolution

A separate record containing:

- resolution ID
- gate ID
- selected choice
- resolution method: `human | safe_default`
- optional note
- resolved timestamp

The original `gate.json` is never rewritten when a decision is resolved.

### Cockpit Dashboard Snapshot

MCC-M0.8 adds a derived, non-persistent read model for the local UI.

A Dashboard snapshot combines:

- Project / Missions
- Workers / Workspaces / Sessions
- Operators
- Tasks / Results / Evidence Bundles
- Handoffs
- Capability registry and Worker bindings
- Human Question Gates
- recent Event Spine entries

The UI does not introduce a second source of truth. It reads the existing control-plane state and calls the existing domain managers for writes.

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

Workers receive only capabilities explicitly resolved and bound for their task.

```text
Mission / Task / Worker
  ↓
Capability Request
  ↓
MADO SYSTEM ONE Capability Pager
  ↓
advisory suggestion
  ↓
Cockpit Policy Gate
  ├─ availability
  ├─ confidence
  ├─ cost class
  ├─ risk tags
  └─ prerequisites
  ↓
Capability Resolution
  ↓
Capability Binding
  ↓
Worker
```

MADO SYSTEM ONE recommends. MADO Cockpit authorizes.

The recommendation layer and the execution-permission layer intentionally remain separate.

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

The Gate protects against two opposite failure modes:

1. **question spam**: forwarding implementation details and system facts to the human;
2. **silent overreach**: deciding privacy, spend, destructive behavior, external actions, or core product meaning without the human.

Decision order:

```text
candidate decision
      ↓
implementation detail?
      ├─ yes, user did not request technical control
      │    → suppress
      ↓
consent required?
      ├─ yes
      │    → ask
      ↓
material to outcome?
      ├─ no
      │    → safe default / continue
      ↓
safe + reversible inference?
      ├─ yes
      │    → record default / continue
      ↓
does the human have context to answer?
      ├─ no
      │    → system investigates first
      ↓
operational "other" decision?
      ├─ yes
      │    → require exhausted recovery sequence
      ↓
Human Question Gate
```

### Human-owned materialities

MCC-M0.7 recognizes:

- `privacy`
- `cost`
- `destructive`
- `external_action`
- `core_meaning`
- `other`

The first five are intrinsically human-owned when unresolved and material.

`other` is reserved for operational ambiguity. It may surface only after the standard recovery sequence is exhausted.

### Operational recovery contract

Before an `other` Gate may open, Cockpit requires evidence that all four strategies are exhausted:

```text
retry
  ↓
alternative_capability
  ↓
alternative_worker
  ↓
evidence_search
  ↓
Human Question Gate
```

Exhausted statuses are:

```text
failed
unavailable
no_match
exhausted
```

If any recovery attempt reports `succeeded`, human escalation is suppressed.

### Human-language contract

User-facing questions should be phrased in outcome language, not avoidable implementation jargon.

Suppressed by default:

```text
"PostgreSQL or SQLite?"
"Which ORM?"
"SSR or CSR?"
```

Allowed examples:

```text
"Should anyone with the link be able to open this, or only people you invite?"
"This can start a paid service. Do you want to enable it, or stay on the free path?"
"Should deleted items disappear permanently, or stay recoverable?"
```

Implementation detail may surface only when the user explicitly requested technical control.

### Choose-for-me contract

A Gate exposes choose-for-me only when `safe_default` is declared.

```text
choose_for_me
  → select safe_default
  → record method=safe_default
```

It does not grant arbitrary decision authority.

For consent-sensitive questions, the safe default should be the non-escalating option such as `stay_free`, `do_not_send`, or `keep_recoverable`.

Resolving a Gate records a decision only. It does not itself execute billing, publication, deletion, messaging, deployment, or another external action.

### Immutable Gate storage

```text
gates/<gate-id>/
├─ gate.json        immutable question/context
├─ status.json      open | resolved
└─ resolution.json  final human/default decision
```

### Operator integration

Opening an Operator Gate stores the current Operator status as `gate_resume_status`, then moves to:

```text
awaiting_human
```

While the Gate remains open:

- `operator advance` makes no progress;
- `operator launch` is rejected;
- Operator inspection exposes the current Gate;
- `next_action = resolve_human_question_gate`.

After resolution:

```text
awaiting_human
  ↓ gate resolved
restore gate_resume_status
  ↓
deterministic operator advance
```

The Gate is attached to the active Builder Task by default, or the current QA Task when the Operator is in a QA phase.

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
- capability.rejected
- capability.bound
- task.assigned
- result.submitted
- evidence.created
- evidence.validated
- evidence.incomplete
- handoff.created
- handoff.materialized
- qa.verdict
- handoff.resolved
- operator.created
- operator.ready
- operator.advanced
- operator.session.started
- operator.session.resumed
- operator.session.stopped
- operator.result.submitted
- operator.verdict.submitted
- operator.completed
- operator.blocked
- operator.failed
- operator.capability.resolved
- operator.gate.requested
- operator.gate.resolved
- gate.requested
- gate.suppressed
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
│  ├─ tasks/
│  ├─ results/
│  ├─ evidence/
│  │  └─ <task-id>/<bundle-id>/
│  │     ├─ manifest.json
│  │     ├─ task.json
│  │     ├─ result.json
│  │     └─ files/
│  ├─ handoffs/
│  │  └─ <handoff-id>/
│  │     ├─ handoff.json
│  │     ├─ status.json
│  │     └─ verdict.json
│  ├─ operators/
│  │  └─ <operator-id>/
│  │     ├─ plan.json
│  │     └─ state.json
│  ├─ capabilities/
│  │  ├─ registry.json
│  │  ├─ requests/
│  │  ├─ resolutions/
│  │  └─ bindings/
│  ├─ gates/
│  │  └─ <gate-id>/
│  │     ├─ gate.json
│  │     ├─ status.json
│  │     └─ resolution.json
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

### MCC-M0.3 Evidence Return ✅

Delivered:

- `TaskContract` domain model
- `ResultContract` domain model
- `EvidenceItem` domain model
- `EvidenceBundle` domain model
- evidence-first Task Contract validation
- automatic workspace Git snapshot
- workspace-file evidence capture
- optional session-trace capture
- SHA-256 and byte-size recording
- frozen task/result snapshots per bundle
- result/evidence lifecycle events
- CLI task/result/evidence commands
- fail-closed workspace boundary checks

### Completion contract

A worker may submit:

```text
status = completed
summary = "Done."
```

but Cockpit does not move the task forward from that claim alone.

```text
Result status        Evidence status      Readiness
----------------------------------------------------
completed            validated            ready_for_qa
completed            incomplete           incomplete
blocked              validated/incomplete not_completed
failed               validated/incomplete not_completed
```

Only `completed + validated` becomes `ready_for_qa`.

### Required evidence contract

Every task must declare at least one required evidence kind.

Example:

```yaml
task:
  id: MCC-M0.3-BUILD
  worker_id: builder
  objective: Implement evidence return.
  required_evidence:
    - git_diff
    - test_result
```

If `test_result` is absent, a completed Result Contract remains incomplete.

### Git evidence

When a result is submitted, Cockpit inspects the assigned worktree using:

```text
git status --porcelain=v1
git diff --no-ext-diff HEAD --
```

If workspace changes exist, Cockpit creates a `git_diff` evidence item containing the status and tracked diff snapshot.

This also records untracked filenames through Git status, while the formal bundle remains a snapshot rather than a replacement for Git itself.

### Workspace-file evidence

Explicit evidence files are supplied as:

```text
KIND=PATH
```

The path must resolve inside the task's assigned worktree. Symlinks or relative paths that escape the workspace are rejected.

The file is copied into the bundle and recorded with:

```text
kind
source
bundle path
SHA-256
size_bytes
description
```

### Session trace bridge

A result may reference an Agent Session.

Cockpit may capture that session's last completed JSONL trace as `session_trace` only when:

```text
session.worker_id == task.worker_id
session.workspace_id == task.workspace_id
last_trace exists
```

A trace from another worker or workspace is rejected.

### Evidence Bundle layout

```text
.mado/cockpit/evidence/
└─ <task-id>/
   └─ <bundle-id>/
      ├─ manifest.json
      ├─ task.json
      ├─ result.json
      └─ files/
         ├─ workspace-changes.txt
         ├─ 01-test_result-tests.txt
         └─ session-trace.jsonl
```

The copied task/result files freeze the contracts as they existed when the bundle was created.

### M0.3 golden fixtures

The fixture set verifies:

```text
completed + git_diff + test_result
  → ready_for_qa

completed + missing required evidence
  → incomplete

failed + complete evidence
  → evidence may validate
  → task remains not completed

evidence file outside worktree
  → rejected

task with no evidence policy
  → rejected

matching session trace
  → bundle capture allowed
```

MCC-M0.3 validates evidence presence, ownership, hashing, and provenance. It does not yet independently judge whether the implementation is correct. Independent validation begins in MCC-M0.4 with the QA Worker.

### MCC-M0.4 Builder → QA Handoff ✅

Delivered:

- `HandoffContract` domain model
- `QAVerdict` domain model
- Builder readiness gate
- QA role and worker separation
- separate QA workspace requirement
- immutable handoff contract
- mutable handoff status record
- Builder Evidence Bundle snapshot
- Builder working-tree source snapshot
- deterministic snapshot tree SHA-256
- auto-created QA Task Contract
- required `qa_report` evidence
- `pass | needs_fix | blocked` verdicts
- source-task routing after verdict
- handoff / QA lifecycle events
- CLI create/list/inspect/verdict commands

### Handoff preconditions

A handoff may be created only when:

```text
source task status == ready_for_qa
source result readiness == ready_for_qa
QA worker != source worker
QA worker role == qa
QA mission == source mission
QA workspace != source workspace
source and QA workspaces are ready
```

The source task moves to `qa_in_review` after handoff creation.

### Review snapshot

QA never receives a pointer to mutable Builder evidence alone.

Cockpit materializes this snapshot inside the QA worktree:

```text
.mado/handoffs/<handoff-id>/snapshot/
├─ source_bundle/
│  ├─ manifest.json
│  ├─ task.json
│  ├─ result.json
│  └─ files/
├─ source_tree/
│  └─ tracked + non-ignored untracked Builder files
└─ source_state.json
```

`source_tree` is built from:

```text
git ls-files -co --exclude-standard
```

This captures tracked files plus non-ignored untracked files, including new implementation files that are not represented by tracked diff content alone.

`source_state.json` records:

- source workspace
- source branch
- source HEAD
- copied file count
- source evidence-bundle digest

The entire snapshot is hashed as a deterministic tree digest. Before accepting any verdict, Cockpit recomputes the digest and rejects the verdict if QA modified the snapshot.

### QA Task

Handoff creation automatically assigns a new Task Contract to the QA worker.

Its contract requires:

```yaml
required_evidence:
  - qa_report
```

The QA report must be submitted through the normal Result / Evidence pipeline. This keeps QA subject to the same evidence-first rules as Builder.

### Verdict contract

```text
QA result              Verdict       Source task
------------------------------------------------
completed + validated  pass          qa_passed
completed + validated  needs_fix     needs_fix
completed/blocked
  + validated          blocked       qa_blocked
```

`pass` and `needs_fix` require a completed QA Result Contract. `blocked` accepts a completed or blocked QA Result, but still requires validated evidence.

A QA result from another task or worker cannot resolve the handoff.

### Immutable source vs mutable state

```text
handoff.json  immutable transfer identity
status.json   awaiting_qa / pass / needs_fix / blocked
verdict.json  final QA verdict and reviewed digest
```

Resolving a handoff never rewrites `handoff.json`.

### M0.4 golden fixtures

The fixture set verifies:

```text
Builder ready_for_qa
  → handoff created
  → source snapshot materialized
  → QA task auto-created
  → QA report submitted
  → PASS
  → source task qa_passed

source not ready
  → handoff rejected

Builder == QA
  → rejected

QA modifies source snapshot
  → verdict rejected

QA returns needs_fix
  → source task needs_fix
```

First dogfood target remains MADO Asset Foundry / MAF-M0.3 Image QA.

### MCC-M0.5 Operator ✅

MCC-M0.5 introduces a deterministic orchestration layer over M0.0 through M0.4.

Delivered:

- `OperatorPlan` and `OperatorState`
- persistent Operator runs
- Builder / QA worker provisioning
- Builder / QA worktree provisioning
- evidence-first Builder Task assignment
- deterministic `advance` state machine
- explicit Builder / QA session launch
- active-session resume instead of duplication
- Operator-level Result submission
- automatic session-trace binding
- automatic Handoff creation after Builder readiness
- QA verdict routing
- `needs_fix` revision loop
- session stop support
- Operator lifecycle events
- CLI start/list/status/advance/launch/stop/result/verdict commands
- fake-provider golden fixtures with no model quota use

### Operator principle

The Operator is a control plane, not an unconstrained autonomous agent.

```text
Operator may:
  inspect state
  provision known roles
  create legal workspaces
  assign evidence-first tasks
  start/resume explicit agent turns
  collect structured results
  create Handoffs after preconditions pass
  route QA verdicts

Operator may not:
  weaken evidence requirements
  bypass QA separation
  mutate Handoff evidence
  infer PASS without a QA verdict
  call a model from operator advance
```

### Operator storage

```text
.mado/cockpit/operators/
└─ <operator-id>/
   ├─ plan.json
   └─ state.json
```

`plan.json` freezes mission intent, Builder/QA identities, Builder Task ID, provider, required evidence, and base Git ref.

`state.json` tracks orchestration status, current Handoff, Builder/QA session IDs, last action, last error, and timestamps.

### Operator state machine

```text
provisioning
  ↓
awaiting_builder
  ├─ evidence incomplete → builder_attention
  ├─ blocked             → blocked
  └─ ready_for_qa
        ↓
     awaiting_qa
        ├─ QA evidence incomplete → qa_attention
        └─ QA result ready
              ↓
        awaiting_verdict
          ├─ pass      → completed
          ├─ blocked   → blocked
          └─ needs_fix
                ↓
             needs_fix
                ↓
          Builder revision
                ↓
          fresh ready_for_qa
                ↓
          new Handoff
```

`failed`, `blocked`, and `completed` are terminal for deterministic `advance`.

### Model execution boundary

`operator advance` never invokes Codex or another model.

Model execution only occurs through explicit launch:

```text
operator launch <id> builder
operator launch <id> qa
```

When the role already has an active session, launch resumes the same external conversation through the M0.2 adapter. Stopped or failed sessions are replaced on the next launch.

This keeps subscription or API usage visible at the invocation boundary.

### Operator Result binding

`operator result` resolves the correct Task from the Operator run:

```text
role=builder → Builder Task
role=qa      → current Handoff QA Task
```

If that role has a recorded Agent Session, its latest completed trace is automatically supplied to the M0.3 Evidence pipeline. It only satisfies the contract when `session_trace` is one of the declared required evidence kinds.

After Result submission, Operator immediately performs the deterministic advance step.

### Revision loop

A `needs_fix` verdict preserves the old Handoff:

```text
Handoff #1
  → QA needs_fix
  → preserved

Builder Task
  → revised Result
  → ready_for_qa

Handoff #2
  → new immutable review snapshot
```

This produces an auditable sequence of review attempts instead of rewriting history.

### M0.5 golden fixtures

```text
Operator start
  → Builder + QA workers
  → two isolated worktrees
  → Builder Task

Builder validated Result
  → automatic Handoff
  → awaiting_qa

advance repeated
  → same Handoff
  → no duplicate review

QA validated Result
  → awaiting_verdict

PASS
  → source task qa_passed
  → Operator completed

NEEDS_FIX
  → source task needs_fix
  → Builder revision
  → new Handoff

active Builder session
  → second launch resumes same session

session_trace required
  → latest Operator session trace is bundled

operator stop
  → stored session becomes stopped
```

The session fixtures inject a fake provider, so CI does not require Codex authentication or consume model quota.

### MCC-M0.6 Capability Pager Bridge ✅

MCC-M0.6 connects Worker needs to MADO SYSTEM ONE-compatible capability resolution while preserving Cockpit authority over execution.

Delivered:

- `CapabilityDescriptor`
- `CapabilityRequest`
- `CapabilitySuggestion`
- `CapabilityResolution`
- `CapabilityBinding`
- System One-compatible registry import
- deterministic zero-quota Pager
- subprocess JSON Pager protocol
- real local System One resolver bridge
- Cockpit confidence/cost/risk/prerequisite policy gate
- safe alternative fallback
- unresolved fail-closed path
- persistent requests/resolutions/bindings
- Operator capability resolution
- Operator launch binding gate
- bound capability injection into Worker prompts
- capability lifecycle events
- CLI import/list/resolve/bindings surface
- Operator capability CLI surface
- zero-quota golden fixtures

### System One contract alignment

Cockpit accepts the descriptor vocabulary already exported by `mado-system-one/src/capability/types.ts`:

```text
CapabilityKind
CapabilityAvailability
CapabilityDescriptor
CapabilityResolutionInput
CapabilitySuggestion
```

Registry import accepts the System One camelCase JSON form such as:

```json
{
  "id": "github",
  "kind": "plugin",
  "name": "GitHub",
  "shortDescription": "Inspect repositories.",
  "availability": "available",
  "riskTags": [],
  "costClass": "low"
}
```

Cockpit normalizes this into its persistent snake_case representation, then converts back to the public System One shape when crossing the Node bridge.

### Advisory authority boundary

System One's `CapabilitySuggestion` remains advisory.

Cockpit requires:

```text
advisoryOnly == true
confidence >= policy minimum
candidate availability == available
candidate cost <= max cost
candidate risk tags do not violate policy
candidate prerequisites are available
```

A Pager cannot directly bind or execute a capability.

### Default Cockpit policy

M0.6 defaults:

```text
min_confidence = 0.40
max_cost_class = low

denied_risk_tags:
  billing
  production
  publish
  delete
  external_message
```

This encodes the subscription/local-first posture directly into the bridge.

Capabilities with unknown cost fail the default gate instead of silently being treated as cheap.

### Alternative fallback

System One may return:

```text
primary
alternatives[]
```

Cockpit evaluates candidates in that advisory order.

Example:

```text
System One:
  primary = prod-deploy
  alternatives = [qa-review]

Cockpit policy:
  prod-deploy
    → high cost
    → production/publish risk
    → reject

  qa-review
    → free
    → available
    → allowed

Resolution:
  selected = qa-review
  reason = selected_alternative
```

If no candidate passes, Resolution status is `unresolved` and no Binding is created.

### Real System One bridge

`scripts/system_one_capability_bridge.mjs` loads a locally built checkout:

```text
<MADO_SYSTEM_ONE_ROOT>/
└─ dist/src/index.js
```

and invokes the real exported:

```text
CapabilityRegistry
CapabilityResolver
```

The bridge uses JSON stdin/stdout:

```text
Python Cockpit
  ↓ request + descriptors
Node bridge
  ↓
local MADO SYSTEM ONE dist
  ↓
CapabilityResolver
  ↓ CapabilitySuggestion
Python Cockpit policy gate
```

The M0.6 bridge provider inside Node is deterministic and zero-quota. This deliberately tests the cross-repo resolver contract without requiring Laya, API credit, or model authentication.

Future Pager providers can replace that provider without changing the Cockpit-side JSON or policy contracts.

### Deterministic Pager

Cockpit also includes a pure-Python deterministic Pager for normal unit tests.

It returns the same advisory suggestion shape using lexical matching.

It is explicitly a fixture/default Pager, not a replacement for MADO SYSTEM ONE.

### Operator integration

Operator can resolve a capability for either role:

```text
operator capability <operator-id> builder
operator capability <operator-id> qa
```

The default request is compiled from:

- role
- Task objective
- required evidence
- deliverables

Operator metadata is attached to the Capability Request for traceability.

When a registry exists, Operator launch requires at least one bound capability for that role.

```text
registry absent
  → M0.5 backward-compatible launch

registry present
  + no binding
  → launch rejected

registry present
  + binding
  → bound capability included in Worker prompt
```

The Worker prompt includes capability ID, name, kind, cost class, and `instructionsRef` when present.

### M0.6 storage

```text
.mado/cockpit/capabilities/
├─ registry.json
├─ requests/
│  └─ capreq_*.json
├─ resolutions/
│  └─ capres_*.json
└─ bindings/
   └─ capbind_*.json
```

### M0.6 golden fixtures

```text
System One camelCase registry
  → imports into Cockpit

Builder implementation request
  → deterministic Pager
  → codex-cli suggested
  → policy allowed
  → Worker binding

dangerous high-cost primary
  → policy rejects
safe alternative
  → selected and bound

dangerous candidate only
  → unresolved
  → no binding

System One JSON suggestion
  → subprocess bridge contract parsed

registry active + no binding
  → Operator launch rejected

binding present
  → Operator launch allowed
  → capability appears in Worker prompt

capability lifecycle
  → request/resolution/binding events persisted
```

The default fixture suite consumes no model quota.

### MCC-M0.7 Human Question Gate ✅

Delivered:

- `RecoveryAttempt` domain model
- `HumanQuestionGate` domain model
- `GateResolution` domain model
- MADO Vibe Shipping question-discipline rules
- materiality classification
- human-language linting
- safe reversible default suppression
- system-should-investigate-first suppression
- consent-required escalation
- four-stage operational recovery requirement
- recovery-success suppression
- immutable Gate request storage
- separate Gate status and resolution
- safe-default-only choose-for-me
- standalone Gate CLI
- Operator Gate request/resolve CLI
- Operator `awaiting_human` state
- launch/advance pause while Gate is open
- deterministic resume after resolution
- Gate lifecycle events
- golden fixtures for interruption precision

### M0.7 decision outcomes

```text
implementation detail
  → suppressed

non-material decision
  → suppressed

safe reversible default
  → suppressed + recorded default

human lacks system context
  → suppressed + investigate first

operational blocker + incomplete recovery
  → suppressed + missing recovery list

operational blocker + recovery succeeded
  → suppressed

operational blocker + all recovery exhausted
  → Gate open

privacy/cost/destructive/external/core meaning
  + unresolved + material
  → Gate open

consent required
  → Gate open
```

### M0.7 Operator loop

```text
Operator running
  ↓
Gate candidate
  ↓
Gate Manager
  ├─ suppress → Operator continues
  └─ ask
       ↓
  awaiting_human
       ↓
  Human choice / safe default
       ↓
  Gate Resolution
       ↓
  restore prior Operator state
       ↓
  deterministic advance
```

### M0.7 golden fixtures

```text
technical database choice
  → suppressed

safe reversible layout choice
  → suppressed

unknown service limit
  → system_should_resolve_first

partial operational recovery
  → recovery_required
  → Gate not opened

all four recovery paths exhausted
  → operational Gate opens

successful retry
  → recovery_succeeded
  → Gate not opened

paid service decision
  → consent Gate opens
  → choose-for-me selects stay_free

avoidable technical jargon
  → rejected from human-facing Gate

Operator privacy Gate
  → awaiting_human
  → launch rejected
  → advance no-op
  → resolve
  → awaiting_builder restored

gate.json
  → unchanged after resolution

Event Spine
  → gate.requested
  → gate.resolved
```

### MCC-M0.8 Cockpit UI ✅

MCC-M0.8 exposes the stabilized control plane through a dependency-free localhost web cockpit.

Delivered:

- `CockpitDashboard` derived read model
- `CockpitUI` action boundary
- `ThreadingHTTPServer` local server
- embedded responsive HTML/CSS/JavaScript
- Mission filtering
- Operator cards with status and next action
- Worker and Capability binding cards
- open Human Question Gate panel
- evidence and Handoff production summary
- recent Event Spine view
- deterministic Operator Advance action
- Human Gate resolution action
- safe-default Gate action
- per-process POST token
- localhost-only bind by default
- explicit remote-bind opt-in
- CSP / no-cache / frame-deny headers
- `mado-cockpit ui` CLI command
- HTTP and dashboard golden fixtures

### UI principle: read-wide / write-narrow

M0.8 intentionally exposes more state than actions.

```text
READ:
  missions
  operators
  workers
  workspaces
  sessions
  capabilities
  tasks
  evidence
  handoffs
  human gates
  event spine

WRITE:
  deterministic operator advance
  explicit Human Gate choice
  declared Gate safe_default
```

Not exposed as direct M0.8 UI actions:

- Agent launch / resume
- Capability resolution
- workspace deletion
- Git push
- publication
- deployment
- billing-bearing actions
- external messaging

Those remain behind the CLI and the existing policy / Human Gate contracts.

The UI therefore cannot become a shortcut around the control plane it is meant to visualize.

### Local web architecture

```text
Browser
  ↓ HTTP on localhost
Cockpit UI server
  ↓
CockpitDashboard
  ↓ reads
.mado/cockpit/*

Browser POST
  ↓ token required
CockpitUI action method
  ↓
existing domain manager
  ↓
state + Event Spine
```

There is no separate UI database and no frontend state persistence.

### Dashboard layout

The first screen prioritizes human attention rather than provider identity.

```text
┌────────────────────────────────────────────────────────────┐
│ Project / localhost state / Refresh                        │
├───────────────┬────────────────────────────────────────────┤
│ Missions      │ KPI strip                                  │
│ filter        ├──────────────────────────┬─────────────────┤
│               │ Operators                │ Human Gates     │
│               │ state + next action      │ choices/impact  │
│               ├──────────────────────────┼─────────────────┤
│               │ Workers + Capabilities   │ Evidence        │
│               ├──────────────────────────┴─────────────────┤
│               │ Event Spine                                │
└───────────────┴────────────────────────────────────────────┘
```

The UI auto-refreshes every eight seconds and offers manual refresh.

### HTTP surface

Read endpoints:

```text
GET /
GET /api/dashboard
```

Write endpoints:

```text
POST /api/operator/advance
POST /api/gate/resolve
```

Gate resolution is Operator-aware. If a Gate belongs to an Operator, the UI calls `OperatorManager.resolve_gate` so the prior Operator state is restored and deterministic execution resumes through the same M0.7 contract.

### Security boundary

Default:

```text
host = 127.0.0.1
port = 8765
```

A non-local bind is rejected unless `allow_remote=True` / `--allow-remote` is explicit.

Every server process creates a random POST token. UI write requests must supply it in:

```text
X-Mado-Cockpit-Token
```

Security response headers include:

- Content Security Policy
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Cache-Control: no-store`

M0.8 is a localhost-first development cockpit, not an authenticated multi-user web service.

### Dependency contract

M0.8 adds no runtime dependency.

```text
Python standard library
  ├─ http.server
  ├─ threading
  ├─ urllib.parse
  └─ webbrowser

Frontend
  ├─ HTML
  ├─ CSS
  └─ vanilla JavaScript
```

This keeps setup aligned with the non-engineer-friendly goal:

```bash
pip install -e ".[dev]"
mado-cockpit ui --open
```

### M0.8 golden fixtures

```text
Cockpit state
  → Dashboard aggregate

Mission / Worker / Gate
  → Dashboard API

GET /
  → UI HTML

GET /api/dashboard
  → JSON control-plane snapshot

POST without token
  → 403

POST with token
  → domain operation

Gate resolve through UI
  → Gate Manager / Operator Manager contract

0.0.0.0 without allow_remote
  → rejected

CLI ui defaults
  → 127.0.0.1:8765
```

The HTTP fixture binds only an ephemeral localhost port.

### v0.1 completion

M0.8 completes the original v0.1 spine:

```text
State
  ↓
Isolated Workspace
  ↓
Agent Session
  ↓
Evidence
  ↓
Independent QA
  ↓
Operator
  ↓
Capability Pager
  ↓
Human Question Gate
  ↓
Cockpit UI
```

The next phase can focus on dogfooding, live visual verification, richer read models, and carefully promoted actions rather than adding more foundational layers.

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
