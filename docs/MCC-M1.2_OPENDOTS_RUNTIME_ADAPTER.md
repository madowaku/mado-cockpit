# MCC-M1.2 OpenDots Runtime Adapter

MCC-M1.2 adds a narrow adapter between an OpenDots-facing workspace and the existing MADO Cockpit control plane.

The goal is not to fork OpenDots or let a Dot bypass Cockpit policy. OpenDots is treated as a human/agent workspace surface; Cockpit remains the owner of mission state, Human Question Gates, evidence, QA handoff, and execution policy.

## Boundary

```text
OpenDots Space / Dot
        |
        | versioned JSON request
        v
MCC-M1.2 OpenDots Runtime Adapter
        |
        | allowlisted deterministic action
        v
MADO Cockpit Operator
        |
        +-- Event Spine
        +-- Human Question Gate
        +-- Evidence / Handoff / QA
```

M1.2 deliberately does **not** expose agent launch, shell execution, result submission, publishing, capability binding, or arbitrary Cockpit CLI execution.

Supported actions:

| Action | Effect |
| --- | --- |
| `operator.status` | Read one Operator run |
| `operator.advance` | Run deterministic Operator state advancement |
| `gate.resolve` | Resolve the Operator's current Human Question Gate |

This keeps OpenDots from becoming a second execution authority.

## Envelope

```json
{
  "schema": "mado.opendots.runtime.v1",
  "request_id": "od_req_001",
  "action": "operator.status",
  "source": {
    "dot_id": "scout",
    "space_id": "space-alpha",
    "thread_id": "thread-42"
  },
  "target": {
    "operator_id": "opr_123"
  },
  "payload": {}
}
```

The adapter rejects unknown top-level fields. Credentials and transport authorization data are not part of the M1.2 envelope. Authentication belongs to the tunnel/transport layer rather than being copied into Cockpit receipts.

## Idempotency

Every accepted request is hashed using canonical JSON and persisted under:

```text
.mado/cockpit/integrations/opendots/receipts/<request-id>.json
```

Replaying the same `request_id` with identical content returns the stored response without invoking Cockpit a second time.

Reusing a `request_id` with different content fails closed.

Successful and failed Cockpit runtime calls are both recorded, so a transport retry cannot accidentally repeat a deterministic state transition.

## Event Spine

The adapter records metadata-only events:

```text
opendots.request.completed
opendots.request.replayed
```

Events include request ID, action, Dot ID, Operator ID, and status. The request payload itself is not copied into the Event Spine.

## Local invocation

The adapter is intentionally transport-neutral. A fixture or bridge can invoke it through stdin:

```bash
python -m mado_cockpit.opendots --root . < request.json
```

or from a file:

```bash
python -m mado_cockpit.opendots --root . --file request.json
```

Validation failures return exit code `2`. Cockpit runtime failures are returned as stable error receipts and exit code `1`.

## Security posture

MCC-M1.2 is intentionally smaller than a general RPC bridge.

It does not listen on a network port, accept bearer tokens in the request, expose `operator.launch`, expose arbitrary shell or CLI execution, or let OpenDots mutate evidence, handoffs, capability policy, or mission files directly.

A future transport can carry this envelope through the M1.1 secure tunnel without changing the Cockpit-facing contract.

## Golden fixtures

`tests/test_opendots.py` verifies:

```text
versioned status envelope          -> accepted
same request replay               -> no duplicate side effect
request-id content drift          -> rejected
operator.launch                   -> rejected
Human Gate resolution             -> bounded and explicit
Cockpit runtime failure           -> stable replayable error
transport credential field        -> rejected
Event Spine                       -> metadata only
```
