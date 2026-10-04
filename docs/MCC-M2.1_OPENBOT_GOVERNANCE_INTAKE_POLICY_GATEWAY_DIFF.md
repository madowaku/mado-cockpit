# MCC-M2.1 OpenBot Governance Intake / Policy Gateway Diff

MCC-M2.1 inspects OpenBot's governance architecture and converts the useful design laws into a pinned, machine-readable diff against MADO Cockpit.

It is an **intake**, not an OpenBot dependency.

## Upstream pin

Inspected source:

```text
CopilotKit/OpenBot
release: v0.1.0
commit: cb5dc32a44517622c6db4e527e61d3abb389b43c
```

Pinned files:

```text
server/src/computer/policy.ts
server/src/computer/gateway.ts
server/src/plugins/mcp.ts
server/src/approvals/service.ts
server/src/approvals/types.ts
server/src/audit.ts
```

Their blob SHAs live in:

```text
fixtures/openbot/mcc-m2.1-governance-intake.json
```

M2.1 does not import OpenBot packages or copy its implementation.

## What MADO already has

MADO is not starting from zero.

### Capability selection policy

`CapabilityManager` already separates a pager's advisory suggestion from Cockpit policy.

The capability policy checks:

- confidence;
- cost class;
- denied risk tags;
- prerequisites;
- availability.

A pager cannot bind a capability merely by recommending it.

### Human-owned decisions

`HumanQuestionGateManager` already decides when a question belongs to the person, persists a Gate, records request/resolution events, and rejects stale Gate IDs through the Operator path.

M1.4-M1.9 then proved this contract through real OpenDots cards, browser clicks, deterministic conversation replay, and normal Chat.

### Event ledger

`CockpitStore.append_event` already gives MADO a durable event spine for missions, sessions, capabilities, handoffs and Human Gates.

### Bounded MCP surface

M2.0 exposes five explicit tools with read/write annotations and a mandatory Gate ID on the ChatGPT-facing decision tool.

These are strong primitives. They are not yet a universal action gateway.

## OpenBot laws worth adopting

### 1. Execution-time default deny

Capability availability and action permission are different questions.

OpenBot asks policy again at the point where an action would actually be dispatched. An absent policy means the action is not permitted.

**MADO gap:** Capability policy exists at selection/binding time, but no generic execution-time policy guards future browser, computer, external MCP or publishing actions.

**M2.2:** add the execution-time Action Policy Gateway.

### 2. Deny before allow

A specific refusal must beat a broad permission.

**MADO gap:** no shared action-rule vocabulary currently defines precedence.

**M2.2:** deny-first semantics.

### 3. Broken policy fails closed

A malformed or failing rule must not enlarge authority.

**MADO gap:** invalid capability metadata is rejected, but there is no execution-time rule engine with a defined safe error result.

**M2.2:** policy exceptions become refusals and durable receipts.

### 4. Audit before act

OpenBot's critical ordering is:

```text
resolve target
  -> decide policy
  -> persist decision row
  -> dispatch action
```

The audit row is not a report written after the side effect.

**MADO gap:** MADO records many events, but nothing yet proves every future external side effect has a durable pre-dispatch decision receipt.

**M2.2:** no dispatch without a recorded Action Decision.

### 5. Unknown external MCP effects fail toward write

MADO knows the behavior of its own five MCP tools.

That is not enough once Cockpit can call arbitrary third-party MCP servers.

**MADO gap:** no external-tool effect classifier.

**M2.2:** any external tool not positively established as read-only is a write.

### 6. Approval is not execution authority

A human approval says what the person decided. It does not freeze the world.

OpenBot re-resolves/revalidates the action before execution.

MADO already applies the narrow version of this law to Human Gates by checking the current Gate ID.

**MADO gap:** generic actions do not yet have a target/grant/policy revalidation contract.

**M2.2:** approved actions must pass the same gateway again against current facts before dispatch.

## Important ideas deferred beyond M2.2

OpenBot contains several good patterns that should not inflate the first gateway milestone.

### Stable action equivalence

OpenBot fingerprints actions so a denied write is not immediately attempted again through a new volatile tool-call ID.

Useful, but M2.2 can be correct without it.

Target:

```text
MCC-M2.3
```

### Actor vs initiator

```text
actor
= whose authority is used

initiator
= what caused the run
  person / routine / system / replay
```

This matters once Cockpit has more autonomous scheduled actions.

Target:

```text
MCC-M2.3
```

### Policy dry-run

Shadow evaluation before enforcement is useful for promoting new governance rules safely.

Target:

```text
MCC-M2.3
```

### Human takeover fencing

Human Question Gates and interactive computer takeover are different primitives.

A future browser/computer session should have a control lease where automated actions are refused while the person drives.

Target:

```text
MCC-M2.4
```

## Machine-readable diff

Generate the current intake report:

```bash
python -m mado_cockpit.governance_intake --root .
```

Write a durable report:

```bash
python -m mado_cockpit.governance_intake \
  --root . \
  --output .mado/cockpit/governance/m2.1-diff.json
```

The compiler validates that every governance claim names a pinned upstream source file.

It also refuses intake fixtures that authorize direct OpenBot source copying or stop treating MADO as the source of truth.

## M2.2 contract extracted by M2.1

The next milestone is intentionally small.

```text
MCC-M2.2 Action Policy Gateway
```

Its five laws are:

1. No side effect executes without an execution-time policy decision.
2. Deny wins over allow and policy evaluation errors refuse.
3. A durable decision receipt exists before dispatch.
4. An external tool not positively classified read-only is treated as write.
5. Human approval does not bypass revalidation of the current action.

That gives MADO the missing choke point without importing OpenBot's product, database, CEL engine, computer runtime or organization model.

## Adoption decision

```text
OpenBot source code dependency      NO
OpenBot package dependency          NO
OpenBot as MADO source of truth     NO

Policy-gateway design laws          YES
Audit-before-act ordering           YES
Fail-closed unknown effects         YES
Approval revalidation pattern       YES
Takeover/equivalence ideas          LATER
```

The aim is not to become OpenBot.

The aim is to make MADO Cockpit's execution boundary as explicit and inspectable as its already-verified Human Gate boundary.
