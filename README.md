# MADO Cockpit

**MADO Cockpit** is the agent execution plane for MADO SYSTEM ONE. ChatGPT Space is the preferred human-facing control plane.

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


### MCC-M0.4 Builder → QA Handoff

A `ready_for_qa` Builder task can now be handed to a **different worker with `role=qa`**.

Handoff creation freezes both the Builder evidence and the reviewable working tree into the QA worktree:

```text
.mado/handoffs/<handoff-id>/snapshot/
├─ source_bundle/
│  ├─ manifest.json
│  ├─ task.json
│  ├─ result.json
│  └─ files/
├─ source_tree/
│  └─ tracked + non-ignored untracked files
└─ source_state.json
```

The whole snapshot receives a deterministic tree SHA-256. QA must not modify it, and Cockpit checks the digest again before accepting a verdict.

Cockpit also creates a dedicated QA Task Contract requiring `qa_report` evidence.

```text
Builder Task
  ↓ ready_for_qa
Handoff snapshot
  ↓
QA Task
  ↓ qa_report
QA Result
  ↓
Verdict
  ├─ pass      → source task = qa_passed
  ├─ needs_fix → source task = needs_fix
  └─ blocked   → source task = qa_blocked
```

Builder cannot QA its own task. QA must be a separate worker and workspace in the same mission.


### MCC-M0.5 Operator

The Cockpit now has a deterministic Operator layer that composes M0.0 through M0.4.

The Operator does not invent policy or silently spend model quota. It performs only legal state transitions and keeps model execution explicit.

```text
Mission + Objective
  ↓
Operator start
  ├─ create Builder worker
  ├─ create QA worker
  ├─ create 2 worktrees
  └─ assign Builder Task
        ↓
operator launch builder
        ↓
operator result builder
        ↓
automatic advance
        ↓
Handoff + QA Task
        ↓
operator launch qa
        ↓
operator result qa
        ↓
operator verdict
        ↓
completed / needs_fix / blocked
```

`operator advance` never calls Codex. It only observes state and performs deterministic orchestration such as creating the next Handoff.

If a recorded Builder or QA session is still active, `operator launch` resumes the same conversation instead of spawning a duplicate session. Stopped or failed sessions are replaced when launched again.

A `needs_fix` verdict routes the original Builder Task back for revision. A new validated Builder Result creates a fresh Handoff while preserving the previous review history.


### MCC-M0.6 Capability Pager Bridge

Workers can now receive capabilities through a **System One-compatible advisory resolution contract** instead of treating tools as ambient global powers.

```text
Task / Worker need
      ↓
Capability Request
      ↓
Capability Pager
      ↓
System One suggestion
(advisoryOnly = true)
      ↓
Cockpit Policy Gate
├─ availability
├─ confidence
├─ cost class
├─ risk tags
└─ prerequisites
      ↓
Capability Binding
      ↓
Worker prompt / execution boundary
```

The registry uses the same public descriptor fields as MADO SYSTEM ONE: `kind`, `availability`, `prerequisites`, `riskTags`, `costClass`, descriptions, and optional instruction references.

System One does **not** get final execution authority. Its suggestion remains advisory. Cockpit rechecks policy and may reject the primary suggestion, select an allowed alternative, or leave the request unresolved.

Default Cockpit policy is conservative:

```text
minimum confidence: 0.40
maximum cost class: low
denied risks:
  billing
  production
  publish
  delete
  external_message
```

When a capability registry is active, `operator launch` fails closed if that Worker has no bound capability. Registry-free M0.5 workflows remain backward compatible.

The real bridge lives at `scripts/system_one_capability_bridge.mjs`. It loads the local built `mado-system-one/dist/src/index.js` and executes the actual System One `CapabilityRegistry` and `CapabilityResolver`. The M0.6 bridge provider is deterministic and zero-quota, so integration can be exercised without consuming API credit.


### MCC-M0.7 Human Question Gate

MADO Cockpit now has a structured **human-attention firewall**.

The Gate does not ask whenever the system is uncertain. It first decides whether the question belongs to the human at all.

```text
candidate decision
      ↓
implementation detail?
      ├─ yes, no technical-control request → suppress
      ↓
consent required?
      ├─ yes → ask
      ↓
material?
      ├─ no → safe default / continue
      ↓
safe + reversible inference?
      ├─ yes → record default / continue
      ↓
does the user know the answer?
      ├─ no → system investigates first
      ↓
operational blocker?
      ├─ yes → require recovery history
      ↓
Human Question Gate
```

Human-owned materialities are `privacy`, `cost`, `destructive`, `external_action`, and `core_meaning`.

Operational `other` questions may surface only after `retry`, `alternative_capability`, `alternative_worker`, and `evidence_search` are exhausted. If any recovery succeeds, escalation is suppressed.

An open Gate freezes the Operator in `awaiting_human`. `operator advance` becomes a no-op and `operator launch` is rejected until the Gate is resolved.

`choose for me` means only "use this Gate's declared safe default." Gate resolution records a decision; it does not itself spend money, publish, delete data, send messages, or perform other external actions.


### MCC-M0.8 Cockpit UI

The v0.1 control plane now has a dependency-free local web cockpit.

```text
Browser
  ↓ localhost
Cockpit UI
  ↓
Python domain managers
  ├─ Operator
  ├─ Evidence
  ├─ Handoff
  ├─ Capability
  ├─ Human Gate
  └─ Event Spine
```

The first UI is intentionally **read-wide / write-narrow**.

Visible surfaces include missions, Operator state and next action, Workers and bound capabilities, open Human Question Gates, evidence/handoff counts, and recent Event Spine entries.

UI actions are limited to deterministic `operator advance`, explicit Human Gate choices, free-form Human Gate decisions, and a Gate's declared safe default.

Agent launch, capability resolution, deployment, publishing, workspace deletion, and other higher-impact actions remain behind the existing CLI, policy, and Gate contracts.

The UI uses only Python's standard library: `ThreadingHTTPServer` plus embedded vanilla HTML/CSS/JS. No frontend build toolchain is required.

Security defaults:

```text
bind = 127.0.0.1
remote bind = refused unless explicitly allowed
POST = per-process random Cockpit token required
CSP = local inline app policy
frame embedding = denied
cache = disabled
```

### MCC-M0.9 Mission Envelope / Outcome Envelope

Cockpit now has a transport-neutral boundary for a Space-style Control Plane.

```text
Space / control surface
        ↓
Mission Envelope
        ↓
Cockpit execution plane
  ├─ policy validation
  ├─ Operator
  ├─ isolated workers
  ├─ Evidence
  ├─ QA
  └─ Human Question Gate
        ↓
Outcome Envelope
        ↓
Space / control surface
```

Mission input is content-addressed and stored immutably under `.mado/cockpit/control/inbox/`. Duplicate delivery is idempotent. Changed content for the same mission requires an explicit source revision.

M0.9 fails closed on authority escalation. A Mission Envelope cannot silently enable paid execution, publishing, deletion, or external messaging.

Start the bridge from JSON:

```bash
mado-cockpit control receive mission.json
mado-cockpit control inspect <ENVELOPE_ID>
mado-cockpit control start <ENVELOPE_ID>
mado-cockpit control outcome <ENVELOPE_ID>
```

The Outcome Envelope intentionally projects only steering-relevant state: mission status, next action, human attention, evidence kinds/bundles, QA verdict, and implementation branch. Raw agent traces and internal Operator state are not copied into the control-plane response.

### MCC-M1.0 Space Transport Adapter

M0.9's Mission/Outcome contracts are now reachable through a bounded **MCP transport** for ChatGPT and Codex.

```text
ChatGPT Space / ChatGPT / Codex
            ↓
       Plugin + MCP
            ↓
  SpaceTransportAdapter
            ↓
   ControlPlaneBridge
            ↓
       MADO Cockpit
            ↓
   Outcome Envelope
```

The transport exposes seven focused tools:

```text
mado_submit_mission
mado_list_missions
mado_inspect_mission
mado_start_mission
mado_refresh_outcome
mado_resolve_human_attention
mado_acknowledge_outcome
```

Write calls can carry a stable `request_id`. Replaying the same request with the same input returns the recorded result; reusing that ID with changed input fails closed.

Outcome consumption is also explicit: `mado_refresh_outcome` returns an `outcome_digest`, and `mado_acknowledge_outcome` accepts only that exact revision.

Install the optional MCP transport:

```bash
pip install -e ".[space]"
```

Run the local Streamable HTTP endpoint:

```bash
mado-cockpit-space-mcp \
  --root . \
  --transport streamable-http
```

Default endpoint:

```text
http://127.0.0.1:8780/mcp
```

M1.0 refuses non-local HTTP binds. For ChatGPT developer-mode testing, use a secure MCP tunnel rather than exposing this unauthenticated development server.

The repo also contains a local plugin package and marketplace:

```text
plugins/mado-cockpit-space/
.agents/plugins/marketplace.json
```

The plugin can launch the same MCP bridge over stdio and includes a control-plane skill that preserves the Mission Envelope, evidence, QA, and Human Question Gate boundaries.

See [MCC-M1.0 Space Transport Adapter](docs/MCC_M1_0_SPACE_TRANSPORT_ADAPTER.md).

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

Once the Builder task is `ready_for_qa`, create a QA worker and handoff:

```bash
mado-cockpit worker create qa \
  --role qa \
  --mission MCC-DEMO \
  --provider codex

mado-cockpit workspace create qa
mado-cockpit handoff create MCC-DEMO-BUILD qa
```

The handoff response includes an auto-created `qa_task_id`. QA writes its report in its own worktree and submits it:

```bash
mado-cockpit result submit <QA_TASK_ID> \
  --status completed \
  --summary "Independent QA complete." \
  --evidence qa_report=qa-report.txt
```

Resolve the handoff using the QA Result:

```bash
mado-cockpit handoff verdict <HANDOFF_ID> \
  --qa-result <QA_RESULT_ID> \
  --verdict pass \
  --summary "QA accepts the Builder result."
```

Use `needs_fix` to route the source task back to Builder, or `blocked` when QA cannot complete validation.

The same production loop can now be bootstrapped through one Operator ID:

```bash
mado-cockpit operator start MCC-DEMO \
  "Implement the smallest safe next step." \
  --require git_diff \
  --require test_result
```

Then use the returned `operator_id`:

```bash
mado-cockpit operator launch <OPERATOR_ID> builder

mado-cockpit operator result <OPERATOR_ID> builder \
  --status completed \
  --summary "Builder result ready." \
  --evidence test_result=tests.txt

mado-cockpit operator launch <OPERATOR_ID> qa

mado-cockpit operator result <OPERATOR_ID> qa \
  --status completed \
  --summary "QA complete." \
  --evidence qa_report=qa-report.txt

mado-cockpit operator verdict <OPERATOR_ID> \
  --verdict pass \
  --summary "Independent QA passed."
```

Inspect the full production run at any time:

```bash
mado-cockpit operator status <OPERATOR_ID>
mado-cockpit operator list
```

Enable the M0.6 capability layer by importing a System One-compatible registry:

```bash
mado-cockpit capability import fixtures/capabilities/mcc-m0.6.json
mado-cockpit capability list
```

Resolve and bind a capability with the zero-quota deterministic pager:

```bash
mado-cockpit operator capability <OPERATOR_ID> builder
mado-cockpit capability bindings
```

After that, `operator launch` includes the bound capability and its `instructionsRef` in the worker prompt.

To exercise the actual MADO SYSTEM ONE resolver locally, first build System One:

```bash
cd C:\Dev\Projects\mado-system-one
npm install
npm run build
```

Then point Cockpit at that repo:

```bash
mado-cockpit operator capability <OPERATOR_ID> builder \
  --pager system-one \
  --system-one-root C:\Dev\Projects\mado-system-one
```

The bridge itself is still zero-quota in M0.6: it uses a deterministic fixture provider *inside* the real System One resolver. This verifies the cross-repo contract without silently invoking a paid model.

Open a human-owned Gate from an Operator:

```bash
mado-cockpit operator gate request <OPERATOR_ID> \
  "This can start a paid service. Do you want to enable it, or stay on the free path?" \
  --reason "Enabling it may create charges." \
  --materiality cost \
  --choice enable_paid \
  --choice stay_free \
  --impact "enable_paid=May create charges." \
  --impact "stay_free=Keeps the zero-cost path." \
  --recommend stay_free \
  --safe-default stay_free \
  --consent-required
```

Resolve explicitly:

```bash
mado-cockpit operator gate resolve <OPERATOR_ID> \
  --choice stay_free
```

Or accept only the declared safe default:

```bash
mado-cockpit operator gate resolve <OPERATOR_ID> \
  --choose-for-me
```

For an operational blocker, escalation requires exhausted recovery:

```bash
mado-cockpit operator gate request <OPERATOR_ID> \
  "Should we stop this attempt or change the goal?" \
  --reason "Automatic recovery paths are exhausted." \
  --materiality other \
  --choice stop \
  --choice change_goal \
  --attempt "retry=failed:Retry reproduced the blocker." \
  --attempt "alternative_capability=no_match:No allowed capability matched." \
  --attempt "alternative_worker=unavailable:No replacement worker is available." \
  --attempt "evidence_search=exhausted:Existing evidence did not resolve the decision."
```

Inspect Gates at any time:

```bash
mado-cockpit gate list --status open
mado-cockpit gate inspect <GATE_ID>
```

MCC-M0.2 does **not** pretend to interrupt an already-running Codex turn. `stop` closes a turn-based session only when no turn is executing.

Launch the local Cockpit:

```bash
mado-cockpit ui --open
```

Default address:

```text
http://127.0.0.1:8765/
```

The Dashboard auto-refreshes every eight seconds and also exposes a manual Refresh control.

Remote bind is refused unless it is deliberate and explicit:

```bash
mado-cockpit ui \
  --host 0.0.0.0 \
  --allow-remote
```

M0.8 remains designed primarily as a localhost control surface.

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


## MCC-M0.4 golden fixtures

The handoff fixtures verify:

```text
ready_for_qa Builder → separate QA worker
Evidence Bundle      → immutable QA snapshot
Builder working tree → source_tree snapshot
QA report            → required evidence
PASS                 → qa_passed
NEEDS_FIX            → needs_fix
self-review           → rejected
snapshot mutation     → verdict rejected
```


## MCC-M0.5 golden fixtures

The Operator fixtures verify:

```text
Mission + objective     → Builder + QA + 2 worktrees + Task
Builder validated       → automatic Handoff
repeated advance        → no duplicate Handoff
QA validated            → awaiting_verdict
PASS                    → Operator completed
NEEDS_FIX               → Builder revision path
revised Builder result  → new Handoff, old history preserved
active Codex session    → resumed, not duplicated
session trace           → automatically bound into Result
operator stop           → recorded session closed
```

The model-facing fixtures use an injected fake provider, so Operator tests do not consume Codex quota.


## MCC-M0.6 golden fixtures

The Capability Pager fixtures verify:

```text
System One camelCase registry → Cockpit descriptor import
deterministic task match       → capability binding
dangerous/high-cost primary    → rejected by Cockpit policy
safe advisory alternative      → selected and bound
no safe candidate              → unresolved, no binding
System One JSON suggestion     → bridge contract accepted
registry active + no binding   → Operator launch rejected
bound capability               → injected into Worker prompt
capability request/resolution  → Event Spine persisted
```

The default tests do not require Node, System One, Laya, or model quota. The Node bridge is an opt-in local integration surface against a built `mado-system-one` checkout.


## MCC-M0.7 golden fixtures

The Human Question Gate fixtures verify:

```text
implementation detail           → suppressed
safe reversible default         → suppressed
user lacks system context        → investigate first
partial recovery history         → escalation suppressed
all recovery exhausted           → operational Gate opens
recovery succeeds                → escalation suppressed
cost consent                     → Gate opens immediately
avoidable technical jargon      → rejected
choose-for-me                    → declared safe_default only
Gate request                     → immutable gate.json
Operator Gate open               → awaiting_human
operator advance while open      → no progress
operator launch while open       → rejected
Gate resolution                  → Operator resumes prior state
gate requested/resolved          → Event Spine persisted
```


## MCC-M0.8 golden fixtures

The Cockpit UI fixtures verify:

```text
control-plane state        → combined Dashboard snapshot
project / mission / worker → visible in Dashboard API
open Gate                  → visible in Dashboard API
GET /                      → Cockpit HTML
GET /api/dashboard         → local state JSON
POST without token         → 403
POST with token            → domain action allowed
Gate resolve from UI       → Gate Manager contract used
free-form Gate             → text decision resolved
remote bind without opt-in → rejected
UI CLI defaults            → 127.0.0.1:8765
```

The UI server fixture binds an ephemeral localhost port and uses only the Python standard library.

## Milestone path

1. **MCC-M0.0 Skeleton** — domain model, state store, CLI ✅
2. **MCC-M0.1 Worktree Worker** — isolated Git worktrees ✅
3. **MCC-M0.2 Agent Session Adapter** — Codex CLI first ✅
4. **MCC-M0.3 Evidence Return** — task/result/evidence contracts ✅
5. **MCC-M0.4 Builder → QA Handoff** — independent validation loop ✅
6. **MCC-M0.5 Operator** — deterministic agent-controlled cockpit ✅
7. **MCC-M0.6 Capability Pager Bridge** ✅
8. **MCC-M0.7 Human Question Gate** ✅
9. **MCC-M0.8 Cockpit UI** ✅
10. **MCC-M0.9 Mission / Outcome Envelope Bridge** ✅
11. **MCC-M1.0 Space Transport Adapter** ✅

See [docs/MADO_COCKPIT_SPEC.md](docs/MADO_COCKPIT_SPEC.md).
