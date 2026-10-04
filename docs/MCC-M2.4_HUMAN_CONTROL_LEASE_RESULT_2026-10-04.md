# MCC-M2.4 Human Control Lease / Automation Fence Result — 2026-10-04

MCC-M2.4 was validated as the temporary human-takeover fence layered on top of the verified M2.3 Action Gateway.

## Passing runs

### Cockpit CI

- Workflow: `CI`
- Run ID: `37185022338`
- Commit: `3698d1703bc16fd0da134e48c78350f64d07f497`
- Result: `success`

```text
147 passed
```

### Human Control Lease

- Workflow: `Human Control Lease`
- Run ID: `37185022350`
- Commit: `3698d1703bc16fd0da134e48c78350f64d07f497`
- Result: `success`
- Focused M2.4 tests: `31 passed`
- Evidence artifact: `human-control-lease-evidence`
- Artifact ID: `11296701845`
- Artifact SHA-256: `a24605e7cddaa676c72ee831ecaf9865302d758dac8a49ab09f384c83c0ee350`

### Governance regressions

At the same commit:

```text
Action Policy Gateway   46 passed
Policy Shadow           40 passed
```

Both workflows completed successfully.

## Human Control smoke

The dedicated smoke used a real Cockpit store and a production-shaped browser action candidate.

The controlled resource was:

```text
kind        browser
resource_id browser-session-m2.4
```

The first lease was acquired by:

```text
human:owner
```

The smoke then exercised:

```text
acquire
  -> heartbeat
  -> agent action refused
  -> lease-holder person action dispatched
  -> release
  -> same agent action dispatched
  -> second short lease
  -> agent action refused
  -> lease expiry
  -> same agent action dispatched
```

Observed dispatch sequence:

```text
human-under-control
agent-after-release
agent-after-expiry
```

No agent dispatch occurred while a Human Control lease was active.

## Durable automation fence

The first automated attempt created:

```text
decision.source = human_control_fenced
dispatch_status = not_dispatched
```

with the Action Decision receipt linked to the active control lease.

The real smoke recorded:

```text
lease       hctrl_15c7a499b563
receipt     actdec_c80fe873482c
```

The lease holder's person-initiated action produced:

```text
receipt     actdec_db852bb449ea
dispatch    dispatched
lease       hctrl_15c7a499b563
```

This proves the Action Gateway can distinguish:

```text
actor      = human:owner
initiator  = person
```

from an automated/chat action targeting the same resource.

## Identity rule

An active Human Control lease does not merely check `initiator.kind`.

The fence is passed only when:

```text
initiator.kind == person
AND
actor == lease.holder
```

Therefore:

- chat/routine/replay/system actions are fenced;
- another human identity is fenced;
- the actual lease holder can proceed to normal live policy evaluation.

The lease does not bypass policy. It only decides who may attempt to act while the resource is under human control.

## Release resumes automation

The first lease was explicitly released.

Immediately after release, the same agent action was evaluated normally and dispatched.

This exposed an important interaction with M2.3 retry fencing.

A Human Control refusal is temporary control-state evidence, not a durable human decline of the underlying action.

M2.4 therefore changed equivalence fencing so receipts with:

```text
decision.source = human_control_fenced
```

do not create a retry fence after the lease is gone.

A genuine policy refusal continues to create the M2.3 same-context equivalence fence.

## Expiry resumes automation

The second lease used a short test TTL.

Before expiry:

```text
agent action
  -> human_control_fenced
  -> not_dispatched
```

After the controlled clock passed the expiry:

```text
lease status = expired
agent action  = dispatched
```

The Cockpit event spine recorded:

```text
control.lease.expired
```

Expiry only removes the temporary Human Control fence.

The action still has to pass all normal M2.2/M2.3 policy, revalidation, equivalence and audit rules.

## Lease lifecycle

The durable manager supports:

```text
acquire
heartbeat
status/current
release
automatic expiry
```

Only one active lease may exist for a resource.

A second acquisition while control is held fails instead of silently stealing the wheel.

Heartbeat and release require the matching holder.

TTL is bounded:

```text
minimum  15 seconds
maximum  3600 seconds
```

## Durable storage

Control leases are stored under:

```text
.mado/cockpit/control_leases/
  hctrl_<id>.json
```

The resource ID is not used in the filename.

The lease itself records:

```text
scope
holder
reason
acquired_at
heartbeat_at
expires_at
released_at
expired_at
status
```

The associated Action Decision receipt records only the minimum control evidence:

```text
control_scope
control_lease.id
control_lease.holder
control_lease.expires_at
```

It does not copy the lease reason or page content.

## Event ledger

M2.4 adds:

```text
control.lease.acquired
control.lease.heartbeat
control.lease.released
control.lease.expired
```

The existing Action Gateway continues to record:

```text
action.decision.recorded
action.dispatched
action.dispatch.failed
```

A Human Control fence is therefore visible as both control-state history and an Action Decision refusal.

## Human-only control surface

M2.4 intentionally does not publish lease acquisition as a ChatGPT MCP tool or an OpenDots agent tool.

An agent cannot grant itself Human Control.

The initial operator surface is:

```bash
python -m mado_cockpit.control_lease --root . acquire ...
python -m mado_cockpit.control_lease --root . status ...
python -m mado_cockpit.control_lease --root . heartbeat ...
python -m mado_cockpit.control_lease --root . release ...
```

The dedicated CI exercised all four CLI operations successfully.

A future authenticated Cockpit UI can use the same `ControlLeaseManager`.

## OpenBot pattern adopted

The OpenBot intake showed an important separation:

```text
policy governs what the Bot may do
Take Control is a human handoff
control taken/released is audited
automation does not race a human driver
```

MADO adopts the design law without importing OpenBot runtime code.

The MADO-native implementation generalizes control from a Bot computer into a resource scope:

```text
browser
computer
interactive-session
future controlled resources
```

## Current product boundary

MADO does not yet have a general real browser/computer action adapter beneath the M2.x Action Gateway.

M2.4 therefore verifies the Governance Kernel using production-shaped browser candidates and a real Cockpit store.

Existing OpenDots/ChatGPT MADO tools do not currently declare a browser/computer `control_scope`, so their existing behavior is unchanged.

When a real browser/computer adapter is introduced, every mutating action on an interactive resource must supply its `control_scope` and will inherit M2.4 automatically.

## MCC-M2.4 status

```text
MCC-M2.4 Human Control Lease / Automation Fence
status: VERIFIED

durable lease acquire: passed
single-holder conflict: passed
heartbeat renewal: passed
holder-bound release: passed
automatic expiry: passed
automation fenced during active control: passed
live allow cannot override human control: passed
other-person identity fenced: passed
lease-holder person path: passed
release resumes automation: passed
expiry resumes automation: passed
human-control refusal is transient for M2.3 equivalence: passed
control scope included in action identity: passed
lease lifecycle event ledger: passed
human-only CLI: passed
focused tests: 31 passed
Cockpit CI: 147 passed
Action Policy Gateway regression: passed
Policy Shadow regression: passed
```
