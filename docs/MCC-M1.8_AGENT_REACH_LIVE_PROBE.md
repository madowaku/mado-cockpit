# MCC-M1.8 Agent Reach Live Probe / External Web Evidence

## Goal

MCC-M1.7 trusts Agent Reach's read-only `doctor --json` health contract. MCC-M1.8 adds a second evidence layer: a safe public read must actually return expected content before Cockpit treats the route as verified.

```text
Agent Reach doctor
      ↓
status=ok + active_backend
      ↓
fixed public live probe
      ↓
content identity check
      ↓
SHA-256 evidence
      ↓
Capability metadata / fail-closed downgrade
```

## Supported probes

The first slice covers three read-only channels.

| Channel | Fixture | Probe mode |
| --- | --- | --- |
| GitHub | `octocat/Hello-World` | exact active backend via `gh api` |
| RSS | CPython public Atom feed | protocol-equivalent GET + XML parse |
| Web | `https://example.com/` through Jina Reader | exact active backend route |

Targets are hard-coded. M1.8 does not accept arbitrary URLs, perform login, mutate remote state, import cookies, or install tools.

The RSS channel is intentionally marked `protocol_equivalent`: Agent Reach's backend is the in-process `feedparser` Python module, not a standalone executable that Cockpit can safely invoke across environments. The probe therefore verifies a real public feed retrieval and valid XML parse while preserving that distinction in evidence.

## Eligibility

A live probe runs only when the current Agent Reach doctor snapshot reports:

```text
status == ok
active_backend != null
```

Otherwise the probe is recorded as `skipped` and no network request is attempted for that channel.

## Evidence record

Each attempt is persisted under:

```text
.mado/cockpit/external_web_evidence/agent_reach/<probe-id>.json
```

The record contains:

- provider
- channel
- backend
- fixed target
- probe mode
- status: `passed`, `failed`, or `skipped`
- SHA-256 of successful content
- byte count
- short redacted excerpt
- redacted failure detail
- checked timestamp

Full remote response bodies are not persisted.

## Routing effect

Evidence is not decorative.

For Agent Reach capabilities covered by a live probe:

- `passed` sets `live_probe_verified=true` and retains the doctor-derived availability.
- `failed` or `skipped` sets `live_probe_verified=false`.
- if the capability was `available`, a non-passing live probe downgrades it to `unknown`.

This prevents the Capability Pager from selecting a route that looked healthy in doctor but failed a real public read.

A later M1.7 sync may refresh doctor-derived availability. Run the live probe again after sync when verified external-read health matters.

## CLI

Run all supported probes:

```bash
mado-cockpit capability agent-reach probe
```

Probe selected channels:

```bash
mado-cockpit capability agent-reach probe \
  --channel github \
  --channel web
```

Inspect persisted evidence:

```bash
mado-cockpit capability agent-reach evidence
mado-cockpit capability agent-reach evidence --channel web
```

## Security boundaries

- fixed public targets only
- GET/read-only semantics only
- no shell command construction
- subprocess timeout
- HTTP response byte cap
- schema/identity checks before `passed`
- secrets redacted from diagnostics and excerpts
- full response bodies are never persisted
- non-routable doctor channels do not touch the network
- failed live reads fail closed into `unknown`
