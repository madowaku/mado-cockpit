# MCC-ART-M0.0 / M0.1 Artifact Workspace Contract + Cloudflare Artifacts Adapter

Status: implemented candidate  
Date: 2026-10-06

## Goal

This track introduces a provider-neutral **Artifact Workspace** for versioned agent work and a first provider adapter for Cloudflare Artifacts.

The split is deliberate:

```text
GitHub
source / human collaboration / release
        |
        v
Artifact Workspace
agent working plane
        |
        +--> baseline
        +--> mission fork
        +--> task fork
        +--> session fork
        +--> experiment fork
```

M0.0 defines the MADO contract.

M0.1 maps that contract to Cloudflare Artifacts REST control-plane operations and standard Git-over-HTTPS data-plane access.

## Official Cloudflare surface used

The first adapter uses the Cloudflare Artifacts REST API:

```text
POST   /accounts/:account/artifacts/namespaces/:namespace/repos
POST   /accounts/:account/artifacts/namespaces/:namespace/repos/:name/import
POST   /accounts/:account/artifacts/namespaces/:namespace/repos/:name/fork
GET    /accounts/:account/artifacts/namespaces/:namespace/repos/:name
DELETE /accounts/:account/artifacts/namespaces/:namespace/repos/:name

POST   /accounts/:account/artifacts/namespaces/:namespace/tokens
DELETE /accounts/:account/artifacts/namespaces/:namespace/tokens/:id
```

Cloudflare API tokens authenticate these control-plane routes.

Repo-scoped Artifacts tokens authenticate normal Git operations against the returned HTTPS remote.

References:

- https://developers.cloudflare.com/artifacts/api/rest-api/
- https://developers.cloudflare.com/artifacts/concepts/repositories/
- https://developers.cloudflare.com/artifacts/examples/sandbox-sdk-artifacts/

## M0.0 Artifact Workspace contract

Durable workspace records use:

```text
mado.artifact-workspace.v1
```

A record contains:

- MADO workspace ID;
- provider ID;
- namespace;
- remote provider repo ID;
- repo name;
- uncredentialed HTTPS remote;
- default branch;
- workspace kind;
- parent workspace/repo when forked;
- optional mission / worker / task / session refs;
- lifecycle status;
- source URL for imported baselines;
- timestamps.

Supported first-stage kinds are:

```text
baseline
mission
task
session
experiment
```

The contract intentionally does not claim that every Artifact Workspace is a local filesystem worktree.

The existing `git_worktree` workspace remains the local execution primitive.

Artifact Workspace is a remote, versioned working-memory primitive.

## Durable layout

Cockpit records only metadata:

```text
.mado/cockpit/artifacts/
├─ workspaces/
│  └─ artw_<id>.json
└─ leases/
   └─ artl_<id>.json
```

Raw repository files remain in the artifact provider.

## Secret boundary

Cloudflare create, import, and fork responses can return an initial Git token.

MADO deliberately does not persist that bootstrap token.

Workspace records therefore always contain:

```text
bootstrap_token_persisted = false
```

For auditable access, Cockpit mints an explicit repo-scoped lease.

Lease records use:

```text
mado.artifact-lease.v1
```

and persist only:

- token ID;
- repo/workspace identity;
- read/write scope;
- expiry;
- lease status;
- issue/revoke timestamps.

They explicitly record:

```text
plaintext_persisted = false
```

The plaintext credential and authenticated Git remote exist only in the returned `EphemeralArtifactCredential`.

They are never written into workspace JSON, lease JSON, or Event Spine records.

## Lease TTL

Cloudflare currently documents repo token TTL limits of:

```text
minimum: 60 seconds
maximum: 31,536,000 seconds
```

MADO enforces those bounds before making a remote request.

The default Cockpit lease is one hour.

## Authenticated remote

Cloudflare's Sandbox SDK + Artifacts example authenticates a Git HTTPS remote by placing the token secret in HTTP basic-auth userinfo.

MADO exposes the equivalent only ephemerally:

```text
https://x:<repo-token>@<artifact-remote>
```

The `?expires=` suffix from the returned token is not included in the password component.

A remote that already contains credentials is rejected.

## M0.1 Cloudflare Artifacts adapter

`CloudflareArtifactsClient` uses only Python's standard library.

No Cloudflare SDK dependency is required.

Configuration:

```text
CLOUDFLARE_ACCOUNT_ID
CLOUDFLARE_API_TOKEN
CLOUDFLARE_ARTIFACTS_NAMESPACE   # default: default
```

The API token is accepted only from the environment by the Cockpit CLI. There is no `--api-token` command-line flag, avoiding accidental process-list/history leakage.

The config dataclass also hides the token from `repr()`.

## CLI

Create an empty baseline:

```bash
mado-cockpit artifact create mado-baseline \
  --kind baseline \
  --description "MADO working baseline"
```

Import the public GitHub source as a baseline:

```bash
mado-cockpit artifact import mado-cockpit-baseline \
  https://github.com/madowaku/mado-cockpit.git \
  --branch main \
  --depth 100
```

Fork a mission/task workspace:

```bash
mado-cockpit artifact fork <BASELINE_WORKSPACE_ID> \
  mission-123-builder \
  --kind mission \
  --mission MCC-123 \
  --worker builder
```

Local inspection requires no Cloudflare credentials:

```bash
mado-cockpit artifact list
mado-cockpit artifact inspect <WORKSPACE_ID>
mado-cockpit artifact leases --workspace <WORKSPACE_ID>
```

Mint a one-hour write lease:

```bash
mado-cockpit artifact lease <WORKSPACE_ID> \
  --scope write \
  --ttl 3600 \
  --reveal-secret
```

`--reveal-secret` is intentionally required before any token is minted.

The resulting JSON contains the plaintext token and authenticated remote once. Treat stdout as secret-bearing output and pipe it only into an authorized consumer.

Revoke it:

```bash
mado-cockpit artifact revoke <LEASE_ID>
```

Delete a workspace:

```bash
mado-cockpit artifact delete <WORKSPACE_ID> \
  --confirm-repo mission-123-builder
```

Deletion fails while recorded leases remain active.

## Event Spine

The adapter records metadata-only events:

```text
artifact.workspace.created
artifact.workspace.imported
artifact.workspace.forked
artifact.lease.issued
artifact.lease.revoked
artifact.workspace.deleted
```

Events never contain API-token plaintext, repo-token plaintext, or authenticated remotes.

## Import boundary

M0.1 supports Cloudflare's public HTTPS import route.

It does not inject GitHub credentials into source URLs.

Private repository intake should use a later credential-aware bridge with an explicit policy boundary.

## Failure behavior

The adapter fails closed on:

- invalid or credentialed remotes;
- path-like repo names;
- invalid token scope;
- token TTL outside Cloudflare's documented bounds;
- Cloudflare v4 error envelopes;
- missing expected fields in successful responses;
- deletion without exact repo-name confirmation;
- deletion while a recorded lease is active;
- attempts to persist token plaintext.

A `409 Conflict` from a still-importing or still-forking repo is surfaced as an API error in M0.1.

Automatic polling/retry belongs to a later orchestration milestone.

## Relationship to local worktrees

M0.1 does not replace `WorktreeManager`.

Current shape:

```text
local
Git worktree
    |
    +--> Codex execution

remote
Artifact Workspace
    |
    +--> Git history
    +--> forkable agent memory
    +--> future Sandbox execution
```

The future bridge can choose placement without changing Mission or Evidence contracts.

## Acceptance fixture

Focused tests cover:

- create and fork route mapping;
- public HTTPS import;
- workspace metadata persistence;
- no bootstrap token persistence;
- repo-scoped lease creation;
- authenticated remote construction;
- lease revocation;
- destructive delete confirmation;
- active-lease delete fence;
- Cloudflare error envelopes;
- token TTL boundaries;
- control-plane token redaction.

The offline smoke additionally proves:

```text
baseline
  -> task fork
  -> write lease
  -> revoke
  -> scan durable .mado state
  -> no token plaintext
```

No Cloudflare credentials are required for CI.

## Next

The natural next milestone is:

```text
MCC-ART-M0.2 Mission -> Repo Fork
```

It should attach a forked Artifact Workspace to a Mission/Worker automatically.

After that:

```text
MCC-ART-M0.3 Agent Repo Lease / Scoped Token
MCC-ART-M0.4 Sandbox <-> Artifact Workspace Bridge
MCC-ART-M0.5 Push Event -> QA Handoff
```

The crucial rule remains:

```text
workspace access != execution authority
Git push != QA pass
Artifact history != promotion
```
