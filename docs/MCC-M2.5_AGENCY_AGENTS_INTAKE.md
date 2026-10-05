# MCC-M2.5 Agency Agents Intake / External Persona Registry

MCC-M2.5 introduces a MADO-native intake boundary for external agent personas.

The first supported corpus is:

```text
https://github.com/msitarzewski/agency-agents
```

The milestone deliberately does **not** install Agency Agents directly into Codex, Claude, Gemini, or another execution host.

Instead, it treats Agency Agents as an external persona/procedure corpus that must pass through MADO provenance, trust, capability, policy, and evidence boundaries before it can influence execution.

## Design law

```text
external persona text
      ↓
pinned source revision
      ↓
exact SHA-256 snapshot
      ↓
normalized persona record
      ↓
experimental trust
      ↓
human review
      ↓
reviewed / trusted / rejected
```

A persona is not a capability.

A persona may describe tools, memory, authority, experience, or runtime behavior that the current host does not actually provide.

MCC-M2.5 therefore records persona instructions while keeping runtime capabilities unverified until the existing Cockpit Capability Pager and policy layers resolve them separately.

## Input boundary

M2.5 does not clone repositories or perform network access.

The operator supplies a local, already checked-out source tree plus a pinned source revision:

```bash
python -m mado_cockpit.persona_registry \
  --root . \
  intake \
  --source-root C:\Dev\External\agency-agents \
  --revision <git-commit-sha>
```

The default source identity is:

```text
provider    agency-agents
repository  https://github.com/msitarzewski/agency-agents
```

The revision is required.

This keeps network credentials, clone policy, repository trust, and update scheduling outside the persona parser.

## Agency Agents detection

The upstream repository contains both agent definitions and ordinary Markdown documentation.

M2.5 treats a Markdown file as an Agency Agents persona only when its frontmatter contains all of:

```text
name
description
color
emoji
vibe
```

Ordinary README/runbook/strategy Markdown is skipped.

The current parser supports the scalar frontmatter shape used by Agency Agents and fails closed on unsupported frontmatter syntax.

## Normalized record

Each imported persona becomes:

```text
mado.external-persona.v1
```

with:

- stable MADO persona ID;
- provider;
- upstream slug and display name;
- division;
- description and presentation metadata;
- repository, revision, source path, SHA-256 and byte size;
- exact frozen source snapshot;
- MADO trust state;
- normalized mission summary;
- critical-rule headings;
- deliverable headings;
- success metrics;
- explicit unverified capability assumptions;
- explicit unverified runtime-memory claims when the source makes memory claims.

The full persona text is preserved as a source snapshot rather than copied into the registry index.

## Stable identity

Persona identity is derived from:

```text
provider + repository + source path
```

not from source content.

Therefore an upstream edit preserves the same logical persona ID while producing a new source SHA-256.

This allows MADO to distinguish:

```text
same persona, new source
```

from:

```text
different persona
```

## Trust states

M2.5 defines:

```text
experimental
reviewed
trusted
rejected
```

Every new external persona begins as:

```text
experimental
```

Trust changes are available only through the local operator CLI in this milestone.

They require an actor in the form:

```text
human:<id>
```

Promotion to `trusted` additionally requires a review note.

Example:

```bash
python -m mado_cockpit.persona_registry \
  --root . \
  trust extp_... \
  --state trusted \
  --actor human:owner \
  --note "Reviewed exact source digest and accepted constraints."
```

M2.5 does not expose trust promotion as a ChatGPT MCP tool or an agent tool.

The actor string is an audit identity, not a replacement for future authenticated UI identity.

## Source changes revoke prior trust

A reviewed/trusted decision is bound to the exact source digest that was reviewed.

If the upstream persona bytes change and are intaken again:

```text
trusted persona
      ↓ source SHA changes
same stable persona ID
      ↓
trust = experimental
      ↓
human re-review required
```

The new record keeps:

```text
previous_source_sha256
```

so the trust reset is inspectable.

If only the pinned repository revision changes while the persona bytes remain identical, the revision is refreshed without revoking trust.

## Reconcile / drift

Before re-intake, an operator can compare the registered corpus against a local upstream checkout:

```bash
python -m mado_cockpit.persona_registry \
  --root . \
  reconcile \
  --source-root C:\Dev\External\agency-agents
```

The report classifies entries as:

```text
current       registered bytes still match
changed       same registered path, different bytes
removed       registered path no longer exists
unregistered  valid Agency Agents persona not yet registered
```

Reconcile is observational.

It does not silently update records or trust.

## Filtered intake

A whole upstream checkout can be scanned, or intake can be narrowed by division:

```bash
python -m mado_cockpit.persona_registry \
  --root . \
  intake \
  --source-root C:\Dev\External\agency-agents \
  --revision <sha> \
  --division game-development
```

or by agent slug/display name:

```bash
python -m mado_cockpit.persona_registry \
  --root . \
  intake \
  --source-root C:\Dev\External\agency-agents \
  --revision <sha> \
  --agent godot-gameplay-scripter \
  --agent testing-evidence-collector
```

A requested agent that cannot be found fails the intake instead of silently producing a partial requested set.

## Durable storage

M2.5 stores:

```text
.mado/cockpit/personas/
├─ registry.json
├─ records/
│  └─ extp_<id>.json
├─ sources/
│  └─ extp_<id>/
│     └─ <source-sha256>.md
├─ reviews/
│  └─ extp_<id>.jsonl
└─ intakes/
   └─ pint_<id>.json
```

`registry.json` is the compact discovery index.

The per-persona record is authoritative for normalized metadata and trust.

The source snapshot freezes the exact external instructions that were reviewed.

The review log records trust transitions.

The intake receipt records the pinned repository revision and the set of imported records.

## Event Spine

M2.5 records:

```text
persona.intake.recorded
persona.intake.completed
persona.trust.changed
```

Events contain persona/source identifiers and trust state, not the entire external prompt body.

## Capability boundary

Agency Agents personas often mention runtime powers such as shell access, screenshots, browsers, persistent memory, frameworks, or specialized tools.

M2.5 does not convert those prose claims into capability bindings.

Normalized records explicitly state:

```text
capability_assumptions.status = unverified
```

Future routing must still pass through MADO's existing capability and policy contracts.

This means:

```text
persona says "use browser"
≠ browser capability granted

persona says "remember"
≠ persistent memory exists

persona says "deploy"
≠ production permission granted
```

## Execution boundary

M2.5 stops at registry and review.

It does not yet:

- attach a persona to a Worker;
- compile a persona into a Codex custom-agent TOML;
- route a Mission to a persona;
- grant capabilities based on persona prose;
- allow a persona to alter Human Control Lease policy;
- auto-update from upstream.

Those belong to later milestones.

A safe next stage can consume only `reviewed` or `trusted` records and compile their persona instructions into a Worker context while preserving Capability Pager, Action Policy Gateway, Human Question Gate, and Human Control Lease authority.

## Evidence fixture

The dedicated smoke:

1. creates two production-shaped Agency Agents Markdown fixtures;
2. imports both;
3. promotes the Godot persona to `trusted`;
4. verifies both reconcile as `current`;
5. mutates the upstream Godot source;
6. verifies reconcile reports `changed`;
7. re-intakes the changed persona at a new revision;
8. verifies the stable persona ID is preserved;
9. verifies trust resets to `experimental`;
10. verifies the prior trusted source SHA is retained.

CI uploads the resulting persona registry, snapshots, review log, intake receipts, focused test output, and smoke result as:

```text
external-persona-registry-evidence
```

## MCC-M2.5 acceptance target

```text
Agency Agents scalar-frontmatter detection
exact source snapshot
pinned revision provenance
stable persona identity
normalized persona contract
experimental-by-default trust
human review ledger
trusted promotion requires note
source change resets trust
same bytes/new revision preserves trust
current/changed/removed/unregistered reconcile
filtered division/agent intake
requested-agent fail-closed
Event Spine evidence
focused tests
real filesystem smoke
full Cockpit regression CI
```
