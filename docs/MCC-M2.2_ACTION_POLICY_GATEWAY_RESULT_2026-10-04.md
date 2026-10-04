# MCC-M2.2 Action Policy Gateway Result — 2026-10-04

MCC-M2.2 was validated as the execution-time governance choke point for MADO Cockpit.

## Passing runs

### Cockpit CI

- Workflow: `CI`
- Run ID: `37182622632`
- Commit: `741ddc663e1a34128a4a4e8e5ea2c1856c3b1c8f`
- Result: `success`

```text
123 passed
```

### Action Policy Gateway

- Workflow: `Action Policy Gateway`
- Run ID: `37182622639`
- Commit: `741ddc663e1a34128a4a4e8e5ea2c1856c3b1c8f`
- Result: `success`
- Focused M2.2 tests: `28 passed`
- Evidence artifact: `action-policy-gateway-evidence`
- Artifact ID: `11295812005`
- Artifact SHA-256: `2638d845cd92a4102d1b6e1363fec0115dd7bfb528e6e3b4f7fb2077307f477f`

## Real governed MCP write

The dedicated workflow created a real Cockpit project, Mission, Operator, and Human Question Gate in a temporary Git repository.

It then started the real M2.0 Streamable HTTP MCP server at:

```text
http://127.0.0.1:8788/mcp
```

The official MCP client called:

```text
mado_check_mission
  -> status = awaiting_human

mado_answer_human_gate
  -> gate_id = gate_a7102814ce1b
  -> choice = stay_free

mado_check_mission
  -> status = awaiting_builder
```

The M2.2 HTTP smoke result was:

```json
{
  "schema": "mado.action-policy-http-smoke.v1",
  "version": "MCC-M2.2",
  "ok": true,
  "url": "http://127.0.0.1:8788/mcp",
  "operator_id": "opr_e4e13e33b1d1",
  "gate_id": "gate_a7102814ce1b",
  "choice": "stay_free",
  "final_status": "awaiting_builder",
  "receipt": {
    "id": "actdec_79136bd10295",
    "action": "mado_answer_human_gate",
    "decision": {
      "allowed": true,
      "source": "allow",
      "rule_id": "allow:mado_answer_human_gate",
      "reason": "MADO permits resolution of the current Human Question Gate."
    },
    "dispatch_status": "dispatched",
    "arguments_digest": "e7e812db4a9d0d4e761519705b6c4b553f81272c666670cae0b190920af53a30"
  },
  "decision_before_dispatch": true
}
```

This proves the real wire path:

```text
official MCP Client
  -> Streamable HTTP /mcp
  -> M2.0 MadoMcpBridge
  -> M1.3 OpenDotsToolSurface
  -> M2.2 ActionPolicyGateway
  -> durable action decision receipt
  -> M1.2 runtime / Operator
  -> Human Gate resolution
  -> Cockpit state
```

## Receipt before dispatch

The smoke independently read the Cockpit event stream and asserted:

```text
action.decision.recorded
        occurs before
action.dispatched
```

The dispatch callback is not called until the receipt file is successfully written.

The durable receipt is stored under:

```text
.mado/cockpit/action_decisions/
  actdec_<id>.json
```

An approved receipt starts as:

```text
status          approved
dispatch_status pending
```

and becomes:

```text
dispatch_status dispatched
```

only after the actual action returns.

A refused action stays:

```text
status          refused
dispatch_status not_dispatched
```

## Six M2.1 P0 gaps closed

### 1. Execution-time default deny

`evaluate_action_policy(None, candidate)` refuses.

An empty policy also refuses unless an explicit allow rule matches.

Capability availability is therefore not execution authority.

### 2. Deny precedes allow

Deny rules are evaluated before allow rules.

A specific deny wins even if a later broad allow also matches.

### 3. Broken policy fails closed

Both cases refuse:

- a rule throws;
- a rule returns anything other than a boolean.

The decision source becomes:

```text
policy_error
```

No policy-evaluation failure can widen authority.

### 4. Audit before act

The gateway order is:

```text
candidate
  -> authoritative revalidation
  -> policy decision
  -> durable receipt
  -> action.decision.recorded
  -> dispatch
  -> action.dispatched / action.dispatch.failed
```

The focused test inspects the receipt from inside the dispatch callback to prove it already exists.

### 5. Unknown external MCP effects become write

M2.2 classifies an external MCP tool as read only when:

```text
readOnlyHint == true
AND
destructiveHint != true
```

All other cases are writes, including:

- missing annotations;
- `readOnlyHint: false`;
- unknown annotation state;
- contradictory `readOnlyHint: true` plus `destructiveHint: true`.

### 6. Approval is not execution authority

`ActionPolicyGateway.execute` can receive:

- an authoritative revalidation callback;
- the digest of the action the person approved.

The current action is resolved again immediately before policy and dispatch.

If the action has changed, the durable refusal source is:

```text
approval_changed
```

If revalidation itself fails, the refusal source is:

```text
revalidation_error
```

Neither case dispatches.

## Human Gate dogfood

The existing `mado_answer_human_gate` path now uses the generic M2.2 gateway.

When a Gate ID is supplied:

1. the tool arguments are validated;
2. M2.2 rereads the current Operator and open Gate;
3. stale Gate identity becomes a durable `action_refused` result;
4. the current action must match the approved action digest;
5. the internal MADO policy must explicitly allow the action;
6. the decision receipt is persisted;
7. only then does `gate.resolve` run.

The older M1.3 stale-Gate pre-check was deliberately removed because it refused before the M2.2 receipt existed.

The renderer contract was updated accordingly: stale cards now receive a structured, receipt-backed refusal rather than an exception thrown before governance.

## Initial governed writes

The first explicit internal policy permits exactly:

```text
mado_advance_mission
mado_answer_human_gate
```

Both are closed-world MADO operations.

Any other action name defaults to deny.

This is intentionally narrower than creating a general-purpose allow policy before browser, computer, publishing, or third-party MCP dispatches exist.

## Receipt privacy

Raw action arguments are never written to the receipt.

M2.2 stores:

```text
arguments_digest = SHA-256(canonical arguments)
```

A focused test uses a literal secret value and verifies the value never appears in the receipt file.

Targets are stored because policy/audit must identify what was governed. Future credential-bearing target shapes must continue to use metadata, never secret material.

## Regression evidence

After the Action Gateway was inserted into the existing MADO write surface, the following real integration workflows remained green on the core integration commit:

```text
OpenDots Dogfood              success
OpenDots Browser E2E          success
OpenDots Browser Chat         success
OpenDots Conversation Replay  success
ChatGPT MCP Bridge            success
```

This means the same gateway now sits beneath both major control planes:

```text
OpenDots
   |
   +-> M1.3 Tool Surface --+
                           |
ChatGPT / MCP              +-> M2.2 Action Policy Gateway
   |                       |
   +-> M2.0 MCP Bridge ----+
                           |
                        Cockpit
```

## CI fail-closed lesson preserved

The dedicated workflow uses:

```bash
set -o pipefail
```

for piped verification output.

This carries forward the M1.9 lesson that `pytest | tee` or a browser smoke piped through `tee` must not be allowed to turn a failed verifier into a green job.

## Deferred scope

M2.2 intentionally does not implement:

- stable equivalent-action decline fencing;
- actor vs initiator policy dimensions;
- policy dry-run / shadow mode;
- human takeover/control leases;
- a general CEL expression language.

Those remain candidates for M2.3/M2.4.

## MCC-M2.2 status

```text
MCC-M2.2 Action Policy Gateway
status: VERIFIED

execution-time default deny: passed
deny before allow: passed
broken policy fail-closed: passed
audit before act: passed
unknown external MCP -> write: passed
approval revalidation: passed
changed-approved-action refusal: passed
stale Human Gate durable refusal: passed
raw argument minimization: passed
real Streamable HTTP MCP write: passed
Cockpit final state verification: passed
focused tests: 28 passed
Cockpit CI: 123 passed
OpenDots regression workflows: passed
ChatGPT MCP regression workflow: passed
```
