# MCC-M2.5 Agency Agents Intake / External Persona Registry Result — 2026-10-05

MCC-M2.5 was validated as the external persona provenance and trust boundary for MADO Cockpit.

## Passing runs

### Cockpit CI

- Workflow: `CI`
- Run ID: `37258792350`
- Commit: `a9b91f8e30193b224f8599c9f308b94cb9de6b10`
- Result: `success`

```text
157 passed in 4.42s
```

### External Persona Registry

- Workflow: `External Persona Registry`
- Run ID: `37258792358`
- Commit: `a9b91f8e30193b224f8599c9f308b94cb9de6b10`
- Result: `success`
- Focused M2.5 tests: `10 passed in 0.11s`
- Evidence artifact: `external-persona-registry-evidence`
- Artifact ID: `11322849353`
- Artifact size: `8350 bytes`
- Artifact SHA-256: `8cd8f90c947915c85a6a5807537c791ab632e9fba6b4eeacd865009a940ffa62`

## Intake smoke

The production-shaped smoke created two Agency Agents-style persona definitions:

```text
game-development/godot/godot-gameplay-scripter.md
testing/testing-evidence-collector.md
```

and one ordinary non-agent README.

The first intake recorded:

```text
created            2
skipped non-agent  1
```

Both external personas began in:

```text
trust = experimental
```

The Godot persona was then explicitly promoted by the human-review surface to:

```text
trust = trusted
actor = human:smoke
```

with a review note bound to the exact source digest.

## Exact-source trust binding

Before source mutation, reconcile reported:

```json
{
  "current": 2
}
```

The trusted Godot source digest was:

```text
a82e7c300089c4a80ba93ebff1a28d52ad0d18b750089e99a90dba6bc8244d86
```

The upstream fixture was then modified without changing its logical persona path.

Reconcile reported:

```json
{
  "changed": 1,
  "current": 1
}
```

Reconcile did not mutate registry state.

After explicit re-intake at a new pinned revision, the same stable persona ID was preserved:

```text
extp_5822667e01f77efa
```

but the source digest became:

```text
d85eafe17eb102eff3330c76fafe4c96339795dacad62d1a9542c32b3e05b86e
```

and trust was automatically reset to:

```text
experimental
```

The record retained:

```text
previous_source_sha256 =
a82e7c300089c4a80ba93ebff1a28d52ad0d18b750089e99a90dba6bc8244d86
```

This proves a prior review cannot silently authorize new upstream instructions.

## Stable identity

Persona IDs are based on:

```text
provider + repository + source path
```

rather than source bytes.

Therefore MADO can preserve one logical persona identity while still treating every changed source digest as a new review boundary.

## Revision-only updates

Focused tests verified that a new pinned repository revision with byte-identical persona content:

```text
revision changes
source SHA unchanged
```

updates provenance without revoking an existing trusted decision.

Trust remains bound to the same exact bytes.

## Agency Agents detection

Focused tests verified that ordinary Markdown is not accidentally imported.

A candidate must carry the Agency Agents frontmatter shape:

```text
name
description
color
emoji
vibe
```

Non-agent Markdown is counted as skipped.

Requested agent filters fail closed when the requested slug or display name cannot be found.

## Normalized contract

The verified record extracts a bounded MADO-native contract:

```text
mission_summary
critical_rule_headings
deliverable_headings
success_metrics
capability_assumptions
runtime_claims
```

The full upstream persona body is preserved only in the exact source snapshot.

This keeps the compact registry inspectable without losing the reviewed original.

## Capability firewall

M2.5 intentionally records:

```text
capability_assumptions.status = unverified
```

Agency Agents prose cannot grant runtime powers.

Claims such as browser use, deployment, shell access, screenshots, or persistent memory remain external instructions until MADO's real Capability Pager and governance layers authorize a concrete capability.

The smoke also verified that source text containing memory language becomes:

```text
runtime_claims.persistent_memory = unverified
```

rather than being treated as a host capability.

## Human review ledger

Focused tests verified:

- non-human actor identifiers cannot change trust;
- promotion to `trusted` requires a review note;
- trust changes are appended to a per-persona JSONL review ledger;
- trust changes are also written to the Event Spine.

The current CLI audit identity uses the form:

```text
human:<id>
```

This is a human-only operator surface in M2.5, not yet an authenticated identity system.

## Drift reconciliation

The focused suite verified all four reconcile states:

```text
current
changed
removed
unregistered
```

Reconcile is observational and does not silently update source snapshots or trust.

## Path boundary

Direct single-file intake rejects persona files that resolve outside the supplied source root.

This keeps source provenance tied to the declared checkout boundary.

## Durable evidence

M2.5 writes:

```text
.mado/cockpit/personas/
├─ registry.json
├─ records/
├─ sources/
├─ reviews/
└─ intakes/
```

The dedicated CI artifact contained 11 files, including the smoke output, exact source snapshots, normalized records, registry, trust-review history, intake receipts, and focused pytest output.

## Event Spine

The real smoke recorded:

```text
persona.intake.recorded
persona.intake.recorded
persona.intake.completed
persona.trust.changed
persona.intake.recorded
persona.intake.completed
```

No full external persona prompt was copied into Event Spine events.

## Product boundary

MCC-M2.5 stops at external persona intake and review.

It does not yet:

- attach a persona to a Worker;
- compile a persona into a Codex custom-agent TOML;
- route a Mission to a persona automatically;
- convert prose tool claims into capabilities;
- let persona instructions override Action Policy Gateway;
- let persona instructions override Human Control Lease;
- auto-fetch or auto-update Agency Agents.

Those remain explicit later-stage contracts.

## MCC-M2.5 status

```text
MCC-M2.5 Agency Agents Intake / External Persona Registry
status: VERIFIED

Agency Agents detection: passed
pinned revision provenance: passed
exact source SHA-256 snapshot: passed
stable persona identity: passed
normalized persona contract: passed
experimental-by-default trust: passed
human trust review ledger: passed
trusted promotion review-note gate: passed
same bytes/new revision preserves trust: passed
changed source resets trust: passed
previous trusted source digest retained: passed
current reconcile: passed
changed reconcile: passed
removed reconcile: passed
unregistered reconcile: passed
requested-agent fail-closed: passed
source-root path boundary: passed
Event Spine evidence: passed
focused tests: 10 passed
Cockpit CI: 157 passed
evidence artifact: uploaded
```
