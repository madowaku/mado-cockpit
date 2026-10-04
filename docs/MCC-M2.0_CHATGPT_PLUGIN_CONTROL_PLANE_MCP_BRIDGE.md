# MCC-M2.0 ChatGPT Plugin Control Plane / MCP Bridge

MCC-M2.0 exposes the verified MADO Cockpit control plane through the official Model Context Protocol so ChatGPT and other MCP hosts can use the same mission state as OpenDots.

## Scope

M2.0 is the **tool bridge**, not the final public deployment.

It provides:

- official Python MCP SDK v2;
- Streamable HTTP at `/mcp`;
- stdio for local MCP hosts;
- the five verified MADO tools;
- ChatGPT-friendly tool titles, descriptions, schemas, and annotations;
- safe public projections that omit M1.x transport IDs and internal filesystem paths;
- loopback-first serving with explicit Host allowlists required for non-loopback binds;
- official MCP Client tests and an HTTP wire smoke.

It does not yet provide production OAuth 2.1 or the Human Gate MCP App UI. Those are separate release gates.

## Tool map

| MCP tool | Behavior | Annotation |
| --- | --- | --- |
| `mado_check_mission` | Read mission state and open Human Gate | read-only, closed-world |
| `mado_advance_mission` | Deterministic orchestration only | write, non-destructive, closed-world |
| `mado_answer_human_gate` | Apply an explicit human decision | write, non-destructive, closed-world |
| `mado_show_evidence` | Read safe Builder/QA evidence metadata | read-only, closed-world |
| `mado_show_qa_result` | Read QA handoff/result/verdict | read-only, closed-world |

No MCP tool exposes model launch, arbitrary shell execution, publishing, capability binding, or arbitrary Cockpit CLI execution.

## Reuse, do not fork the policy

The MCP layer delegates to the existing M1.3 surface:

```text
ChatGPT / MCP host
      |
      | tools/call
      v
MCC-M2.0 MCP Bridge
      |
      | mado.opendots.tool-call.v1 internally
      v
MCC-M1.3 Tool Surface
      |
      v
MCC-M1.2 Runtime Adapter / Cockpit
```

This deliberately reuses the same stale-Gate protection, evidence projection, QA projection, and deterministic Operator boundary already dogfooded through OpenDots.

## Public result shape

M2.0 removes transport-only fields before returning a tool result to an MCP host.

The host receives:

```json
{
  "ok": true,
  "data": {},
  "presentation": {}
}
```

It does not receive:

```text
tool_call_id
request_id
M1.2 receipt path
worktree path
session trace path
evidence file path
handoff snapshot path
```

The `presentation` object is retained because M2.1/M2.2 can attach a portable MCP App renderer without changing the data-tool contract.

## Human Question Gate

The ChatGPT-facing write tool requires:

```text
operator_id
gate_id
choice OR choose_for_me
```

`gate_id` is mandatory on the MCP surface even though the older OpenDots compatibility surface keeps it optional.

The server rereads the current Operator and rejects a stale Gate ID before changing state.

The MCP server instructions explicitly tell the model never to infer a Human Gate answer.

## Local server

Install:

```bash
pip install -e .
```

Run Streamable HTTP:

```bash
mado-cockpit-mcp --root . --host 127.0.0.1 --port 8787
```

Endpoint:

```text
http://127.0.0.1:8787/mcp
```

Run stdio instead:

```bash
mado-cockpit-mcp --root . --transport stdio
```

## MCP Inspector

```bash
npx @modelcontextprotocol/inspector@latest
```

Connect to:

```text
http://127.0.0.1:8787/mcp
```

## Non-loopback serving

M2.0 fails closed when binding to a non-loopback address without an explicit Host allowlist.

Example development bind:

```bash
mado-cockpit-mcp \
  --root . \
  --host 0.0.0.0 \
  --port 8787 \
  --allowed-host mcp.example.test \
  --allowed-host 'mcp.example.test:*'
```

Equivalent environment variables:

```text
MADO_MCP_ALLOWED_HOSTS=mcp.example.test,mcp.example.test:*
MADO_MCP_ALLOWED_ORIGINS=https://example.test
```

This is transport hardening, not user authentication.

## ChatGPT boundary

For ChatGPT developer-mode testing, expose the local `/mcp` endpoint through an approved HTTPS tunnel or deployment and add that URL as a Plugin connection.

For any deployment that exposes private Cockpit data or write tools to real users, add OAuth 2.1 before public use.

M2.0 intentionally does not encourage publishing an unauthenticated Cockpit endpoint.

## Verification

The normal test suite uses the official in-memory MCP `Client` to verify:

- exactly five tools;
- read/write annotations;
- required `gate_id`;
- real Operator reads;
- real Human Gate resolution;
- stale Gate rejection as a model-visible tool error;
- no internal transport IDs or Cockpit paths in public results;
- non-loopback HTTP fail-closed behavior.

The dedicated M2.0 workflow additionally starts the real Streamable HTTP server and connects with the official MCP Client over HTTP.
