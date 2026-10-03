# MCC-M0.9 Space Control Plane Bridge

Status: Proposed  
Parent: `MADO_COCKPIT_SPEC.md v0.1`

## Decision

MADO's top-level architecture is split into two planes:

```text
ChatGPT Space
= Control Plane

MADO Cockpit
= Agent Execution Plane
```

Space owns human-facing intent, priorities, decisions, planning context, and summarized mission state.

MADO Cockpit owns execution authority, worker isolation, capability policy, agent sessions, evidence, QA, recovery, and auditable state transitions.

GitHub remains the durable implementation record.

## Why this change

MCC-M0.0 through M0.8 proved that Cockpit can safely execute work, but its UI and Operator were described as the production control plane.

With Space available as the human/agent collaboration surface, Cockpit no longer needs to become the primary planning UI.

Instead:

```text
Human
  ↓
Space
  ├─ goals
  ├─ priorities
  ├─ product decisions
  ├─ mission briefs
  └─ readable status
  ↓
Mission Envelope
  ↓
MADO Cockpit
  ├─ policy validation
  ├─ Human Question Gate
  ├─ capability resolution
  ├─ isolated workers
  ├─ Codex sessions
  ├─ evidence
  ├─ independent QA
  └─ recovery / rollback
  ↓
Outcome Envelope
  ↓
Space
```

## Authority boundary

### Space owns

- What are we trying to accomplish?
- Why does it matter?
- What is the current priority?
- Which human decisions have been made?
- Which mission should start, pause, continue, or be abandoned?
- What status should be visible to the human?

### Cockpit owns

- Is this mission executable?
- Which worker/worktree receives it?
- Which capabilities are permitted?
- May an external or paid action occur?
- What evidence is required?
- Is the result ready for QA?
- Did QA validate the result?
- Is automatic recovery possible?
- Does a decision require the human?

### GitHub owns

- source code
- commits
- branches
- pull requests
- durable implementation history

## Critical rule

**Space content is context, not execution authority.**

Free-form Space prose MUST NOT be passed directly to a Builder as privileged execution instructions.

Every executable request must first compile into a validated Mission Envelope.

## Mission Envelope

Initial contract:

```json
{
  "schema_version": "mado.mission-envelope.v1",
  "mission_id": "MCC-M0.9",
  "title": "Space Control Plane Bridge",
  "objective": "Connect Space intent to Cockpit execution safely.",
  "source": {
    "kind": "space",
    "space_id": null,
    "page_id": null,
    "revision": null
  },
  "priority": "normal",
  "constraints": [],
  "deliverables": [],
  "required_evidence": [
    "git_diff",
    "test_result"
  ],
  "human_decisions": [],
  "execution_policy": {
    "allow_paid": false,
    "allow_publish": false,
    "allow_delete": false,
    "allow_external_message": false
  }
}
```

Unknown fields should be preserved as metadata but MUST NOT silently increase execution authority.

## Envelope validation

Cockpit accepts an envelope only when:

1. `schema_version` is supported.
2. `mission_id`, `title`, and `objective` are present.
3. At least one required evidence kind exists.
4. Execution policy is explicit.
5. No requested authority exceeds Cockpit policy.
6. Material privacy/cost/destructive/external/core-meaning ambiguity routes through Human Question Gate.
7. The envelope can be persisted immutably before execution begins.

Invalid envelopes fail closed.

## Outcome Envelope

Cockpit returns a compact human/control-plane projection instead of exposing raw internal state.

Initial contract:

```json
{
  "schema_version": "mado.outcome-envelope.v1",
  "mission_id": "MCC-M0.9",
  "status": "completed",
  "summary": "Bridge contract implemented and independently validated.",
  "next_action": null,
  "human_attention": null,
  "evidence": {
    "bundle_id": "evb_...",
    "kinds": ["git_diff", "test_result", "qa_report"]
  },
  "qa": {
    "verdict": "pass"
  },
  "implementation": {
    "repository": "madowaku/mado-cockpit",
    "branch": "cockpit/mcc-m0.9-builder"
  }
}
```

Raw traces stay in Cockpit. Space receives only the level of detail needed for steering.

## Sync model

M0.9 should NOT assume a magical bidirectional live-sync API.

The bridge is transport-neutral:

```text
Space adapter
or manual export
or Plugin/MCP adapter
        ↓
Mission Envelope
        ↓
Cockpit
        ↓
Outcome Envelope
        ↓
Space adapter
or manual import
or Plugin/MCP adapter
```

This lets Cockpit implement the contract now and attach the best available Space integration later.

## Event Spine additions

Add:

```text
control.mission.received
control.mission.accepted
control.mission.rejected
control.outcome.compiled
control.human_attention.requested
control.human_attention.resolved
```

Events should include the mission ID and envelope digest.

## Storage

```text
.mado/cockpit/control/
├─ inbox/
│  └─ <envelope-id>/
│     ├─ mission.json
│     └─ status.json
└─ outbox/
   └─ <envelope-id>/
      └─ outcome.json
```

Mission input is immutable after acceptance.

Subsequent Space edits create a new envelope revision rather than rewriting the accepted request.

## Cockpit UI reclassification

MCC-M0.8 remains useful, but its role changes.

Old framing:

```text
Cockpit UI = control plane UI
```

New framing:

```text
Space      = human-facing control plane
Cockpit UI = local execution observability / intervention console
```

The local Cockpit UI remains the place for:

- execution diagnostics
- evidence inspection
- worker/session inspection
- local Human Gate fallback
- recovery
- operator troubleshooting

It should not compete with Space as the primary planning surface.

## Operator reclassification

The Operator is now an **execution orchestrator**, not the top-level product control plane.

Operator receives an accepted Mission Envelope and deterministically drives:

```text
Builder
→ Evidence
→ Handoff
→ QA
→ Verdict
→ Outcome Envelope
```

## Human Question Gate routing

Human Question Gate stays inside Cockpit because it is part of the execution safety boundary.

However, the preferred presentation target becomes Space.

```text
Cockpit detects human-owned decision
  ↓
Gate opens locally
  ↓
Outcome/attention projection
  ↓
Space shows human question
  ↓
human answer
  ↓
Control response envelope
  ↓
Cockpit resolves Gate
```

Until a Space transport exists, the localhost UI/CLI remains the fallback.

## Security model

Space is never implicitly trusted as a privileged executor.

The bridge must resist:

- prompt injection inside Space content
- stale mission revisions
- duplicated delivery
- accidental replay
- authority escalation through prose
- evidence requirement weakening
- silent paid/publish/delete/external actions

Cockpit remains the final execution-policy authority.

## M0.9 implementation slice

Deliver the smallest transport-neutral bridge:

1. `MissionEnvelope` domain model.
2. `OutcomeEnvelope` domain model.
3. Envelope JSON schema/version validation.
4. Immutable control inbox/outbox persistence.
5. SHA-256 digest for accepted mission envelopes.
6. Idempotent duplicate reception.
7. Operator start-from-envelope adapter.
8. Outcome compiler from Operator state.
9. Event Spine additions.
10. CLI:
   - `control receive <mission.json>`
   - `control inspect <envelope-id>`
   - `control start <envelope-id>`
   - `control outcome <envelope-id>`
11. Zero-quota golden fixtures.

## Golden fixtures

```text
valid Mission Envelope
  → accepted + immutable digest

same envelope delivered twice
  → same accepted identity / no duplicate Operator

same mission ID + changed content
  → new revision required / silent overwrite rejected

missing evidence policy
  → rejected

paid execution requested while disallowed
  → rejected or Human Gate according to policy

accepted mission
  → Operator created

Operator completed + QA pass
  → Outcome Envelope compiled

raw session trace
  → not copied into Outcome Envelope

human Gate open
  → outcome reports human_attention
```

All fixtures must use fake providers and consume no model quota.

## Definition of done

M0.9 is complete when a JSON Mission Envelope can enter Cockpit, drive the existing M0.5-M0.8 execution spine without weakening any safety/evidence invariant, and produce a deterministic Outcome Envelope suitable for presentation in Space.

No direct Space API integration is required to declare M0.9 complete.

## Next milestone

**MCC-M1.0 Space Transport Adapter**

Only after the contract is stable should we bind it to whichever official Space surface is available.

The transport layer must remain replaceable without changing Mission/Outcome semantics.
