# MCC-M2.2 Action Policy Gateway

MCC-M2.2 adds the execution-time governance choke point extracted by M2.1 from the OpenBot intake.

The rule is simple:

```text
No durable decision receipt
        =
No side effect
```

## Scope

M2.2 implements the six P0 gaps identified by the pinned OpenBot governance diff:

1. execution-time default deny;
2. deny before allow;
3. broken policy fails closed;
4. audit before act;
5. unknown external MCP effect becomes write;
6. approval is not execution authority.

M2.2 intentionally does not add CEL, policy dry-run, actor/initiator separation, action-equivalence fencing, or human computer takeover. Those remain M2.3/M2.4 work.

## Action candidate

Every governed action is represented as a bounded candidate containing:

```text
action
effect: read | write
target_kind
authoritative target facts
arguments
actor
optional capability
optional mission_id
```

Raw arguments are never copied into the durable decision receipt. The receipt stores only a canonical SHA-256 arguments digest.

## Policy evaluation

The gateway evaluates:

```text
deny rules
  -> allow rules
  -> default deny
```

A deny match is final.

A rule exception or a rule returning anything other than a boolean is a policy error and refuses the action.

An absent policy also refuses the action.

## Audit before act

The execution order is:

```text
candidate
  -> optional authoritative revalidation
  -> policy decision
  -> write action decision receipt
  -> append action.decision.recorded
  -> dispatch
  -> mark dispatched / failed
```

The dispatch callback cannot run until the receipt file has been written successfully.

Approved receipts begin with:

```text
status = approved
dispatch_status = pending
```

Only after the callback returns do they become:

```text
dispatch_status = dispatched
```

A refusal has:

```text
status = refused
dispatch_status = not_dispatched
```

## Approval revalidation

`ActionPolicyGateway.execute` accepts both:

- a revalidation callback;
- an optional digest representing the action the human approved.

Immediately before policy and dispatch, the callback resolves the current authoritative action again.

If revalidation fails, the attempt receives a durable refusal receipt.

If the current action digest differs from the approved digest, dispatch is refused with:

```text
source = approval_changed
```

The human's approval therefore never acts as a permanent execution token.

## External MCP effect classification

M2.2 defines the conservative boundary:

```text
readOnlyHint == true
AND destructiveHint != true
    -> read

everything else
    -> write
```

Missing annotations are writes.

`readOnlyHint: false` is a write.

A contradictory destructive read-only declaration is a write.

This classifier is ready for the future external-MCP router without trusting an unknown tool as read-only.

## Initial dogfood policy

The first production-shaped consumers are the two existing bounded MADO writes:

```text
mado_advance_mission
mado_answer_human_gate
```

The internal policy permits only those exact closed-world operations.

All other action names default-deny.

The Human Gate write additionally re-reads the current Operator/Gate immediately before dispatch. A stale Gate therefore fails inside the generic Action Policy Gateway as a durable refusal rather than relying only on an earlier UI decision.

## Receipt location

```text
.mado/cockpit/action_decisions/
  actdec_<id>.json
```

Receipts contain target metadata and digests, but not raw action arguments.

The normal Cockpit event spine also receives:

```text
action.decision.recorded
action.dispatched
action.dispatch.failed
```

## Why this is not OpenBot code

M2.2 uses the design laws pinned in M2.1, but is a MADO-native implementation.

There is no OpenBot package dependency and no copied policy engine.

The existing MADO Human Gate, Operator, Runtime Adapter, event store and MCP bridge remain the source of truth.

## Verification laws

Tests prove:

- no policy means deny;
- deny beats broad allow;
- broken deny and allow rules fail closed;
- unknown MCP tools classify as write;
- the durable receipt exists before dispatch begins;
- refused actions never dispatch;
- approved actions are revalidated and changed actions are refused;
- revalidation failures create durable refusal receipts;
- raw arguments are absent from receipts;
- MADO's existing write tools continue through the gateway.
