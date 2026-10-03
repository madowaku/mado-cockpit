# MCC-M1.1 Secure MCP Tunnel / Real Space Dogfood

Status: Implemented
Parent: MCC-M1.0 Space Transport Adapter

## Decision

M1.1 proves the private MADO Cockpit MCP can be reached from a real ChatGPT/Codex client through OpenAI Secure MCP Tunnel without publishing the local server to the internet.

The dogfood is intentionally zero-quota:

```text
ChatGPT Space
   ↓
Secure MCP Tunnel
   ↓
mado-cockpit-space MCP
   ↓
dogfood handshake
   ↓
Mission Envelope
   ↓
ControlPlaneBridge
   ↓
Operator provision only
   ↓
Outcome Envelope
   ↓
ACK exact outcome digest
   ↓
local verification = complete
```

No Codex worker turn is launched in M1.1. The goal is to prove the transport, control boundary, and round-trip evidence before adding live agent execution.

## Official tunnel assumptions

The implementation follows OpenAI's Secure MCP Tunnel flow:

- `tunnel-client` runs inside the same trust boundary as the private MCP server.
- It opens outbound HTTPS to OpenAI and forwards MCP work to a local stdio or HTTP server.
- A tunnel profile is initialized with a `tunnel_id`.
- The runtime key is provided through `CONTROL_PLANE_API_KEY`.
- `tunnel-client doctor --profile <name> --explain` is the readiness check.
- `tunnel-client run --profile <name>` remains running while ChatGPT/Codex uses the tunnel.
- ChatGPT developer mode creates an app with Connection = Tunnel and selects or enters the `tunnel_id`.

Reference:
https://developers.openai.com/api/docs/guides/secure-mcp-tunnels

## Local commands

Install the Space extras:

```bash
pip install -e ".[space]"
```

Create the tunnel in OpenAI Platform and obtain:

```text
tunnel_id
runtime API key
```

Keep the API key only in the environment:

PowerShell:

```powershell
$env:CONTROL_PLANE_API_KEY="sk-..."
```

bash:

```bash
export CONTROL_PLANE_API_KEY="sk-..."
```

Preview the exact local commands without secrets:

```bash
mado-cockpit-tunnel plan \
  --tunnel-id tunnel_...
```

Initialize the profile:

```bash
mado-cockpit-tunnel init \
  --tunnel-id tunnel_...
```

Validate the profile and record evidence:

```bash
mado-cockpit-tunnel doctor
```

Run the tunnel in the foreground:

```bash
mado-cockpit-tunnel run
```

The generated stdio target is equivalent to:

```text
python -m mado_cockpit.space_mcp
  --root <cockpit-root>
  --transport stdio
```

There is no public local MCP listener in the default M1.1 tunnel path.

## Secret boundary

`CONTROL_PLANE_API_KEY` is:

- read from the runtime environment;
- passed only to the `tunnel-client` subprocess environment;
- never written to Cockpit JSON state;
- never included in command previews;
- never returned by the CLI.

Tunnel metadata such as profile name and `tunnel_id` may be stored because it is needed for local operation and is not treated as the runtime secret.

## Tunnel evidence

M1.1 records tunnel setup/diagnostic evidence under:

```text
.mado/cockpit/control/secure-tunnel/
├─ profiles/
│  └─ mado-cockpit-space.json
└─ evidence/
   └─ mado-cockpit-space/
      ├─ ...-init.json
      └─ ...-doctor.json
```

Evidence includes:

- operation
- profile
- tunnel ID
- redaction-safe command
- exit code
- stdout/stderr
- SHA-256 of stdout/stderr
- timestamp

A failed doctor remains evidence and returns unhealthy rather than being hidden.

## Plan compatibility

As of October 3, 2026, ChatGPT full MCP write/modify actions are available to Business and Enterprise/Edu workspaces. Pro developer mode can connect custom MCPs with read/fetch permissions but not the full write flow.

M1.1 therefore supports two dogfood modes:

### Read-only Tunnel probe

Suitable for a read-only MCP connection.

```text
ChatGPT
  ↓
mado_dogfood_probe
  ↓
HMAC proof returned
  ↓
local verify-probe
```

Prepare a challenge normally, then ask ChatGPT to call:

```text
mado_dogfood_probe(challenge_id, nonce)
```

Copy the returned `proof` and verify locally:

```bash
mado-cockpit-space-dogfood verify-probe \
  <challenge_id> <proof>
```

The probe tool is annotated read-only and does not write Cockpit transport receipts. The HMAC secret remains local and is never returned by `prepare`.

### Full write round trip

When the ChatGPT workspace permits full MCP write actions, use the normal handshake and submit → start → outcome → ACK flow below.

Reference:
https://help.openai.com/en/articles/12584461-developer-mode-and-full-mcp-connectors-in-chatgpt

## Real Space challenge

Prepare one challenge:

```bash
mado-cockpit-space-dogfood prepare
```

The result contains:

- `challenge_id`
- one-time nonce
- dogfood mission ID
- a copy/paste prompt for the ChatGPT Space

The Space client must first call:

```text
mado_dogfood_handshake
```

with the exact challenge ID and nonce.

The handshake returns:

- the immutable Mission Envelope for the dogfood;
- stable request IDs for submit/start/ack;
- exact step instructions.

The Mission Envelope explicitly prohibits:

- Codex launch/model quota consumption;
- paid execution;
- publish;
- delete;
- external messaging.

## Required round trip

The real client performs:

```text
1. mado_dogfood_handshake
2. mado_submit_mission
3. mado_start_mission
4. mado_refresh_outcome
5. mado_acknowledge_outcome
```

After `mado_start_mission`, the expected M1.1 state is:

```text
operator_status = awaiting_builder
```

That is intentional. M1.1 proves transport only and does not launch a Builder model turn.

## Verification

After the Space run:

```bash
mado-cockpit-space-dogfood verify <challenge_id>
```

Verification checks independently for:

```text
mcp_handshake
mission_submitted
mission_started
outcome_compiled
outcome_acknowledged
```

Only when all five are true does the challenge return:

```json
{
  "complete": true
}
```

The verification receipt is saved at:

```text
.mado/cockpit/dogfood/space/<challenge-id>/verification.json
```

## Why the handshake matters

Normal transport request receipts prove that the `SpaceTransportAdapter` was used, but a local test could call that service directly.

The dogfood handshake is exposed as a dedicated MCP tool and validates a locally generated nonce. Its evidence establishes that a client reached the MCP tool surface for that specific challenge before the normal Mission/Outcome flow began.

This is not a cryptographic attestation of the ChatGPT UI itself. It is an evidence-backed proof of the intended MCP path and challenge round trip.

## ChatGPT connection step

With `tunnel-client run` healthy:

1. Open ChatGPT Settings.
2. Enable Developer mode if the workspace/account permits it.
3. Go to ChatGPT Plugins.
4. Select the plus button to create a developer-mode app.
5. Under Connection choose Tunnel.
6. Select the available tunnel or enter the `tunnel_id`.
7. Review discovered MADO tools.
8. Add the app to the target Space/chat.
9. Paste the prompt returned by `mado-cockpit-space-dogfood prepare`.

OpenAI documents that local MCP servers cannot be connected directly from ChatGPT; Secure MCP Tunnel is the supported private path.

Reference:
https://developers.openai.com/plugins/deploy/connect-chatgpt

## Golden fixtures

M1.1 verifies:

```text
Tunnel plan
  → stdio MADO MCP command
  → no secret in preview

Tunnel init
  → runtime key passed only in subprocess env
  → non-secret local profile metadata

Tunnel doctor
  → exit status + stdout/stderr evidence
  → no runtime key persisted

missing CONTROL_PLANE_API_KEY
  → fail closed

dogfood prepare
  → challenge + nonce + zero-quota envelope

wrong nonce
  → rejected

handshake + submit + start + outcome + ack
  → verification complete

challenge before client calls
  → verification incomplete

MCP server
  → dogfood handshake tool discovered
```

CI uses fake tunnel-client execution. It never needs a real tunnel, API key, ChatGPT account, or model quota.

## Definition of done

Code-level M1.1 is complete when the tunnel harness, challenge protocol, MCP handshake, evidence capture, and verifier pass CI.

Operational dogfood is complete only after a real ChatGPT/Codex client uses Secure MCP Tunnel and the local verifier reports all five checks true.

## Next milestone

**MCC-M1.2 Space → Live Codex Execution / Remote Human Gate**

After transport dogfood succeeds, expose the smallest policy-gated path that lets an explicit Space request launch/resume the Builder or QA Codex session, return evidence, and route Human Question Gate decisions back through Space.

Model/quota execution must remain explicit and observable.
