# MADO Cockpit

**MADO Cockpit** is the production control plane for MADO SYSTEM ONE.

It turns AI agents, workspaces, capabilities, evidence, and human decisions into one observable production team.

## Current spine

### MCC-M0.0 Skeleton

Established:

- Project
- Mission
- Worker
- Event
- local JSON state store
- initialization, mission, worker, and status CLI commands

### MCC-M0.1 Worktree Worker

Adds isolated Git workspaces for workers.

Each worker receives a deterministic branch and linked worktree:

```text
Mission MCC-M0.1
├─ builder
│  ├─ branch: cockpit/mcc-m0.1-builder
│  └─ .mado/worktrees/mcc-m0.1-builder
└─ qa
   ├─ branch: cockpit/mcc-m0.1-qa
   └─ .mado/worktrees/mcc-m0.1-qa
```

Workspace lifecycle is persisted under `.mado/cockpit/workspaces/` and emits `workspace.created` / `workspace.removed` events.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"

mado-cockpit init
mado-cockpit mission create MCC-DEMO "Build the first cockpit fixture"

mado-cockpit worker create builder --role builder --mission MCC-DEMO
mado-cockpit worker create qa --role qa --mission MCC-DEMO

mado-cockpit workspace create builder
mado-cockpit workspace create qa

mado-cockpit workspace list
mado-cockpit workspace status mcc-demo-builder

mado-cockpit status
pytest
```

Cleanup:

```bash
mado-cockpit workspace remove mcc-demo-builder --force --delete-branch
mado-cockpit workspace remove mcc-demo-qa --force --delete-branch
```

State is stored under `.mado/cockpit/`. Linked worktrees live under `.mado/worktrees/`.

## MCC-M0.1 golden fixture

The fixture proves:

```text
2 workers
2 worktrees
1 repository
0 shared uncommitted files
0 workspace collision
```

Each worker writes a different file into its worktree. The test verifies that neither file appears in the other worker's workspace, then removes both worktrees and their fixture branches.

## Milestone path

1. **MCC-M0.0 Skeleton** — domain model, state store, CLI ✅
2. **MCC-M0.1 Worktree Worker** — isolated Git worktrees ✅
3. **MCC-M0.2 Agent Session Adapter** — Codex CLI first
4. **MCC-M0.3 Evidence Return** — task/result/evidence contracts
5. **MCC-M0.4 Builder → QA Handoff** — independent validation loop
6. **MCC-M0.5 Operator** — agent-controlled cockpit
7. **MCC-M0.6 Capability Pager Bridge**
8. **MCC-M0.7 Human Question Gate**
9. **MCC-M0.8 Cockpit UI**

See [docs/MADO_COCKPIT_SPEC.md](docs/MADO_COCKPIT_SPEC.md).
