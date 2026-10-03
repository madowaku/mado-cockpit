# MCC-M1.0 Space Transport Adapter

Status: Implemented
Parent: MCC-M0.9 Mission Envelope / Outcome Envelope

## Decision

M1.0 connects ChatGPT/Codex to the MADO Cockpit execution plane through MCP.

It does not depend on an unpublished or product-internal Space page API.

```text
ChatGPT Space / ChatGPT / Codex
            ↓
       Plugin / MCP
            ↓
   SpaceTransportAdapter
            ↓
    ControlPlaneBridge
            ↓
   Mission Envelope v1
            ↓
       MADO Cockpit
            ↓
  Operator / Evidence / QA
            ↓
   Outcome Envelope v1
            ↑
       Plugin / MCP
            ↑
ChatGPT Space / ChatGPT / Codex
```

The M0.9 Envelope contracts remain the semantic boundary. MCP is only the transport.

## Goals

- Let ChatGPT or Codex submit Space-derived mission intent.
- Keep duplicate delivery idempotent.
- Start accepted missions without bypassing Cockpit policy.
- Return compact outcome state without leaking local execution internals.
- Surface Human Question Gates to the control plane.
- Accept Gate decisions through the same Cockpit safety contract.
- Acknowledge a specific outcome revision by digest.
- Package the workflow as a local plugin for development and dogfood.
- Keep the transport replaceable.

## Non-goals

M1.0 does not:

- use an undocumented Space API;
- edit Space pages directly;
- expose Cockpit state directories as a remote file API;
- publish an unauthenticated public MCP endpoint;
- grant paid, publish, delete, or external-message authority;
- auto-launch model turns from a read/status request;
- replace the M0.9 Mission/Outcome schemas.

## Transport service

`SpaceTransportAdapter` is a pure Python service layer over `ControlPlaneBridge`.

It exposes:

```text
submit_mission
list_missions
inspect_mission
start_mission
refresh_outcome
resolve_human_attention
acknowledge_outcome
```

The service layer is independent of the MCP SDK so it can later be reused by another transport.

## Request idempotency

Write-like transport operations may include a caller-supplied `request_id`.

Cockpit persists a receipt:

```text
.mado/cockpit/control/transports/space-mcp/
└─ requests/
   └─ <request-id>.json
```

The receipt binds:

- transport name
- request ID
- operation
- canonical input SHA-256
- returned result
- completion timestamp

Replaying the same request ID with identical operation/input returns the recorded result.

Reusing the same request ID with different input fails closed.

This protects against retries, reconnects, and duplicate agent tool calls.

## Output acknowledgement

A compiled Outcome Envelope receives a canonical SHA-256 digest.

After the control plane consumes the result, it can acknowledge that exact revision.

```text
refresh_outcome
  ↓
Outcome Envelope
  ↓ SHA-256
outcome_digest
  ↓
acknowledge_outcome
  ↓
transport ack receipt
```

Acknowledgements are stored at:

```text
.mado/cockpit/control/transports/space-mcp/
└─ acks/
   └─ <envelope-id>/
      └─ <outcome-digest>.json
```

A stale or substituted digest is rejected.

## Space-facing projection

The MCP transport does not return the full Operator inspection object.

Allowed examples:

- envelope ID
- mission ID / title / objective
- accepted/started status
- Outcome Envelope
- next action
- Human Question Gate projection
- evidence kinds and bundle IDs
- QA verdict
- implementation branch

Not returned by transport projections:

- local worktree filesystem paths
- raw agent session traces
- full Operator internal state
- internal recovery details unless already projected by the Human Gate contract

Local Cockpit UI/CLI remains the diagnostic surface.

## MCP tool surface

The server exposes seven focused tools:

```text
mado_submit_mission
mado_list_missions
mado_inspect_mission
mado_start_mission
mado_refresh_outcome
mado_resolve_human_attention
mado_acknowledge_outcome
```

Read tools are annotated read-only.

Write tools are marked non-destructive. Idempotent tools are marked where the transport contract guarantees replay safety.

`mado_refresh_outcome` is intentionally not read-only because compiling an outcome persists an outbox snapshot and Event Spine entry.

## Human attention

The control plane may never resolve an arbitrary human-owned choice on its own.

`mado_resolve_human_attention` accepts exactly one of:

```text
choice=<explicit user choice>
choose_for_me=true
```

`choose_for_me=true` still means only the Gate's declared safe default.

The tool cannot widen that authority.

## Execution authority

The M0.9 fail-closed rule remains active.

Mission Envelopes cannot set these to true:

```text
allow_paid
allow_publish
allow_delete
allow_external_message
```

MCP does not add a side door around this rule.

## Server transport

The official MCP Python SDK is an optional dependency:

```bash
pip install -e ".[space]"
```

Entrypoint:

```bash
mado-cockpit-space-mcp
```

Default development transport:

```text
Streamable HTTP
http://127.0.0.1:8780/mcp
```

Stdio is also supported:

```bash
mado-cockpit-space-mcp --transport stdio
```

The target repo is selected by:

```text
--root <path>
```

or:

```text
MADO_COCKPIT_ROOT=<path>
```

## Remote safety boundary

M1.0 refuses non-local HTTP binds.

This is deliberate.

A server that reads private Cockpit state or performs actions must not become publicly reachable without authentication and authorization.

Development testing may use an approved secure MCP tunnel.

A future remote milestone can add an authenticated gateway without changing the MCP tool or Envelope semantics.

## Plugin package

Repo-local plugin:

```text
plugins/mado-cockpit-space/
├─ .codex-plugin/
│  └─ plugin.json
├─ .mcp.json
└─ skills/
   └─ control-plane/
      └─ SKILL.md
```

Repo marketplace:

```text
.agents/plugins/marketplace.json
```

The bundled MCP config launches:

```text
mado-cockpit-space-mcp --transport stdio
```

The host environment must have the project installed and must point `MADO_COCKPIT_ROOT` at the Cockpit repo when the current working directory is not the target repo.

## Golden fixtures

M1.0 verifies:

```text
same request ID + same input
  → same recorded result

same request ID + changed input
  → rejected

submit mission
  → accepted envelope projection

start mission
  → Operator started
  → no local worktree path in response

Builder → Evidence → QA → PASS
  → Outcome Envelope

Outcome Envelope + exact digest
  → acknowledgement stored

wrong outcome digest
  → rejected

Human Gate
  → Space-facing human_attention

choose_for_me
  → safe default only

MCP server
  → exactly seven bounded tools

read tool
  → readOnlyHint=true

remote HTTP bind
  → rejected
```

Fixtures use the existing fake/no-model execution path. No live model quota is required.

## Definition of done

M1.0 is complete when a ChatGPT/Codex MCP client can submit a Mission Envelope, start the existing Cockpit execution flow, inspect/refresh the Outcome Envelope, route a Human Gate response, and acknowledge the consumed outcome without bypassing M0.9 authority or exposing local execution internals.

## Next milestone

**MCC-M1.1 Authenticated Remote MCP Gateway / Space Dogfood**

Add the smallest authenticated remote/developer-mode path needed to connect a real ChatGPT Space session to this tool surface, then run one real mission end-to-end.

The remote layer must not change the Mission/Outcome contracts.
