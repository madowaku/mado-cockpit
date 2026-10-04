# MCC-M2.4 Human Control Lease / Automation Fence

MCC-M2.4 gives MADO a durable answer to a different human-control question than the Human Question Gate.

```text
Human Question Gate
= who decides?

Human Control Lease
= who has the wheel right now?
```

## Design law

When a person holds active control of an interactive resource:

```text
automation/chat/routine/replay/system action
  -> durable human_control_fenced receipt
  -> no dispatch
```

The lease holder may perform person-initiated operations through an otherwise-permitted path.

The lease does not itself grant new action permissions. After the Human Control fence is passed, normal live policy still applies.

## Durable lease

The lease schema is:

```text
mado.human-control-lease.v1
```

Stored under:

```text
.mado/cockpit/control_leases/
  hctrl_<id>.json
```

A lease contains:

- resource kind and ID;
- holder;
- optional reason;
- acquired timestamp;
- heartbeat timestamp;
- expiry timestamp;
- released/expired timestamps;
- active/released/expired status.

Resource identifiers are not used as filenames.

## Lifecycle

### Acquire

A human acquires control for a bounded TTL.

Only one active lease may exist for a resource.

A second acquisition while the first lease is active fails rather than silently stealing control.

### Heartbeat

The matching holder can extend the lease.

Heartbeat cannot change the holder.

### Release

The matching holder explicitly releases control.

The resource immediately returns to normal Action Policy evaluation.

### Expiry

A stale Human Control lease expires automatically when read.

Expiry is fail-open **only for this temporary automation fence**: once the lease is no longer active, normal execution policy resumes.

It does not mean the action is allowed. The action still has to pass M2.2/M2.3 policy, revalidation, equivalence and receipt rules.

## Gateway ordering

For actions with a `control_scope`, M2.4 adds this check after authoritative revalidation and approval binding, but before shadow/live policy dispatch:

```text
revalidate
  -> approval digest check
  -> Human Control Lease fence
  -> shadow policy
  -> action equivalence
  -> live policy
  -> receipt
  -> dispatch
```

An active lease is a stronger temporary automation fence than an allow policy.

## Lease-holder identity

While a lease is active, the Action Gateway allows the control fence to pass only when both are true:

```text
initiator.kind == person
actor == lease.holder
```

Every other initiator, including another person identity, is fenced.

The lease therefore cannot be bypassed merely by labeling an automated action as person-initiated while retaining a different actor.

## Transient fence vs declined action

A Human Control refusal is not the same as the user declining the action itself.

M2.3 equivalence fencing therefore deliberately ignores prior receipts whose source is:

```text
human_control_fenced
```

Otherwise this bad sequence would occur:

```text
human takes control
agent click refused
human releases control
same agent click remains permanently retry-fenced
```

M2.4 instead guarantees:

```text
active lease -> automation fenced
release/expiry -> same automation may be evaluated normally again
```

A genuine policy denial remains eligible for M2.3 same-context retry fencing.

## Control scope

`ActionCandidate` now has an optional:

```text
control_scope = {
  kind,
  resource_id
}
```

Examples:

```text
browser / browser-session-123
computer / computer-456
interactive-session / session-789
```

The control scope participates in both the full action digest and equivalence digest, so actions aimed at different interactive resources are never treated as equivalent.

Actions without a control scope are unaffected by M2.4.

## Receipt evidence

A fenced Action Decision contains:

```text
decision.source = human_control_fenced
dispatch_status = not_dispatched
control_scope
control_lease.id
control_lease.holder
control_lease.expires_at
```

The Action receipt does not contain lease reasons or human-entered page content.

Lease lifecycle events are also recorded:

```text
control.lease.acquired
control.lease.heartbeat
control.lease.released
control.lease.expired
```

## Human-only operation surface

M2.4 does not publish acquire/release as ChatGPT or OpenDots agent tools.

An agent must not be able to grant itself a Human Control lease.

The initial human/operator surface is local:

```bash
python -m mado_cockpit.control_lease --root . acquire \
  --kind browser \
  --resource-id browser-session-123 \
  --holder human:owner \
  --ttl-seconds 300

python -m mado_cockpit.control_lease --root . status \
  --kind browser \
  --resource-id browser-session-123

python -m mado_cockpit.control_lease --root . heartbeat \
  --lease-id hctrl_... \
  --holder human:owner \
  --ttl-seconds 300

python -m mado_cockpit.control_lease --root . release \
  --lease-id hctrl_... \
  --holder human:owner
```

A future Cockpit UI can call the same manager through a human-authenticated route.

## Relationship to OpenBot

M2.4 adopts the design law visible in OpenBot's computer gateway:

- Take Control is an explicit human handoff;
- takeover/release are audited;
- automated computer actions must not race a person who has the wheel.

MADO does not import OpenBot's computer runtime or control-state implementation.

The MADO-native difference is that control is represented as a generic resource lease and enforced inside the shared M2.x Action Gateway.

## Current integration boundary

MADO does not yet have a general browser/computer dispatch adapter beneath the Action Gateway.

Therefore M2.4 verifies the Governance Kernel with production-shaped browser candidates and a real Cockpit store, while leaving existing OpenDots and ChatGPT tools unchanged.

When browser/computer actions are added, they must supply a `control_scope`; they inherit M2.4 without changing the lease contract.
