# MCC-M1.7 Agent Reach Adapter / External Web Capability Router

> The original working title was MCC-M1.6. The repository already uses MCC-M1.6 for the OpenDots browser E2E / Human Gate milestone, so this integration is numbered MCC-M1.7 to keep milestone identity unique.

## Goal

Expose Agent Reach channels to the existing MADO Cockpit Capability Pager without making Agent Reach the control plane.

The adapter is deliberately thin:

1. run the read-only machine contract `agent-reach doctor --json`;
2. validate the returned schema;
3. normalize each channel into a Cockpit `CapabilityDescriptor`;
4. preserve non-Agent-Reach capabilities already in the registry;
5. replace only descriptors previously managed by this adapter.

Cockpit remains the policy and binding authority. Agent Reach remains the external-web provider.

## Health contract

Agent Reach reports:

- `status`
- `name`
- `message`
- `tier`
- ordered `backends`
- `active_backend`

MADO Cockpit intentionally fails closed.

| Agent Reach | active_backend | Cockpit availability |
| --- | --- | --- |
| ok | present | available |
| ok | missing | unavailable |
| warn | any | unavailable |
| off | any | unavailable |
| error | any | unknown |

A binary existing on PATH is not evidence of a healthy route. The provider becomes routable only when Agent Reach itself reports a successful probe and names the backend actually serving the channel.

## Registry identity

Managed capabilities use stable IDs:

`agent-reach.<channel>`

Examples:

- `agent-reach.github`
- `agent-reach.twitter`
- `agent-reach.youtube`
- `agent-reach.web`

Provider metadata records the upstream status, backend order, active backend, tier, and the sanitized doctor message.

The sync refuses to overwrite an unmanaged capability with the same ID.

## CLI

Inspect without mutating the registry:

```bash
mado-cockpit capability agent-reach doctor
```

Refresh Agent Reach-managed descriptors:

```bash
mado-cockpit capability agent-reach sync
```

Override the executable or timeout when needed:

```bash
mado-cockpit capability agent-reach sync \
  --agent-reach-binary /path/to/agent-reach \
  --timeout 30
```

The default executable may also be supplied through `MADO_AGENT_REACH_BIN`.

## Execution contract

A bound `agent-reach.<channel>` capability means:

1. Cockpit selected the platform capability under normal Capability Pager policy.
2. The last sync observed `status=ok` and a non-empty `active_backend`.
3. The worker may use Agent Reach's published channel instructions and the recorded active backend for read-oriented external-web work.
4. Authentication, browser cookies, provider keys, installs, and system mutation are not performed by this adapter.
5. If a live operation fails, treat the registry entry as stale evidence. Re-run the doctor/sync path before changing credentials or installing anything.

Agent Reach owns backend fallback semantics. Cockpit records the ordered candidates and current active backend but does not duplicate Agent Reach's internal backend-selection logic.

## Security boundaries

- subprocess execution uses an argv list with `shell=False` semantics;
- doctor runs with a timeout;
- schema drift is rejected rather than guessed;
- diagnostic strings are redacted again at the Cockpit boundary;
- `warn`, `off`, and `error` channels cannot become routable capabilities;
- sync updates only descriptors marked `managed_by=mado-cockpit.agent-reach`;
- no install/configure/login command is invoked.

## Acceptance fixture

The deterministic fixture contains:

- GitHub: `ok + active_backend=gh` -> available;
- Twitter: `warn + active_backend=null` -> unavailable;
- Web: `error + active_backend=null` -> unknown.

Tests also cover schema drift, redaction, managed-entry replacement, preservation of existing capabilities, and collision refusal.
