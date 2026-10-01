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
