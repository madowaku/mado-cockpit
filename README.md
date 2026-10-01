# MADO Cockpit

**MADO Cockpit** is the production control plane for MADO SYSTEM ONE.

It turns AI agents, workspaces, capabilities, evidence, and human decisions into one observable production team.

## MCC-M0.0 Skeleton

The first milestone deliberately starts below the UI layer.

It establishes:

- Project
- Mission
- Worker
- Event
- local JSON state store
- CLI commands for initialization, mission creation, worker creation, and status

The goal is to make the control-plane spine executable before adding worktrees, agent adapters, evidence bundles, or a graphical cockpit.

## Quick start

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -e ".[dev]"

mado-cockpit init
mado-cockpit mission create MCC-DEMO "Build the first cockpit fixture"
mado-cockpit worker create builder --role builder --mission MCC-DEMO
mado-cockpit status
pytest
```

State is stored under `.mado/cockpit/`.

## Milestone path

1. **MCC-M0.0 Skeleton** — domain model, state store, CLI
2. **MCC-M0.1 Worktree Worker** — isolated Git worktrees
3. **MCC-M0.2 Agent Session Adapter** — Codex CLI first
4. **MCC-M0.3 Evidence Return** — task/result/evidence contracts
5. **MCC-M0.4 Builder → QA Handoff** — independent validation loop
6. **MCC-M0.5 Operator** — agent-controlled cockpit
7. **MCC-M0.6 Capability Pager Bridge**
8. **MCC-M0.7 Human Question Gate**
9. **MCC-M0.8 Cockpit UI**

See [docs/MADO_COCKPIT_SPEC.md](docs/MADO_COCKPIT_SPEC.md).
