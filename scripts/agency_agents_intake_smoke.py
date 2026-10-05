from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from mado_cockpit.models import Project
from mado_cockpit.persona_registry import ExternalPersonaRegistry
from mado_cockpit.store import CockpitStore


def _agent(
    name: str,
    *,
    mission: str,
    extra: str = "",
) -> str:
    return f"""---
name: {name}
description: Production-shaped Agency Agents intake fixture
color: purple
emoji: TEST
vibe: Evidence-first specialist.
---

# {name}

## Your Core Mission

### Mission
- {mission}

## Critical Rules You Must Follow

### Evidence Before Claims
- Produce evidence before declaring completion.

## Your Technical Deliverables

### Implementation
- Produce a reviewable artifact.

## Your Success Metrics

- Evidence exists for the claimed result.

{extra}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    store = CockpitStore(root)
    store.init(
        Project(
            id="mcc-m2.5-smoke",
            name="MCC-M2.5 Smoke",
            root=str(root),
        )
    )
    registry = ExternalPersonaRegistry(store)

    upstream = root / "agency-agents-fixture"
    godot = upstream / (
        "game-development/godot/"
        "godot-gameplay-scripter.md"
    )
    qa = upstream / "testing/testing-evidence-collector.md"
    godot.parent.mkdir(parents=True, exist_ok=True)
    qa.parent.mkdir(parents=True, exist_ok=True)
    godot.write_text(
        _agent(
            "Godot Gameplay Scripter",
            mission="Build typed, evidence-backed gameplay systems.",
        ),
        encoding="utf-8",
    )
    qa.write_text(
        _agent(
            "Evidence Collector",
            mission="Verify claims against reproducible evidence.",
        ),
        encoding="utf-8",
    )
    (upstream / "README.md").write_text(
        "# Non-agent fixture\n",
        encoding="utf-8",
    )

    first = registry.intake_tree(
        upstream,
        revision="fixture-rev-1",
    )
    if first["counts"].get("created") != 2:
        raise RuntimeError(
            f"Expected two created personas, got: {first['counts']}"
        )

    godot_item = next(
        item
        for item in first["items"]
        if item["slug"] == "godot-gameplay-scripter"
    )
    persona_id = godot_item["persona_id"]
    trusted = registry.set_trust(
        persona_id,
        state="trusted",
        actor="human:smoke",
        note="Smoke fixture reviewed at exact source digest.",
    )
    trusted_sha = trusted["source"]["sha256"]

    before_change = registry.reconcile(upstream)
    if before_change["counts"].get("current") != 2:
        raise RuntimeError(
            "Expected both imported personas to reconcile as current."
        )

    godot.write_text(
        _agent(
            "Godot Gameplay Scripter",
            mission="Build typed, evidence-backed gameplay systems.",
            extra="\n## Upstream Change\n- New reviewed behavior.\n",
        ),
        encoding="utf-8",
    )

    drift = registry.reconcile(upstream)
    if drift["counts"].get("changed") != 1:
        raise RuntimeError(
            "Expected one changed persona before re-intake."
        )

    second = registry.intake_tree(
        upstream,
        revision="fixture-rev-2",
        agents=["godot-gameplay-scripter"],
    )
    updated = registry.inspect(persona_id)
    if second["items"][0]["intake_status"] != "updated":
        raise RuntimeError(
            "Changed source did not produce updated intake status."
        )
    if updated["trust"]["state"] != "experimental":
        raise RuntimeError(
            "Changed trusted persona was not demoted to experimental."
        )
    if updated["previous_source_sha256"] != trusted_sha:
        raise RuntimeError(
            "Previous trusted source digest was not retained."
        )

    result = {
        "schema": "mado.mcc-m2.5-smoke.v1",
        "status": "passed",
        "first_intake": first["id"],
        "second_intake": second["id"],
        "persona_id": persona_id,
        "trusted_source_sha256": trusted_sha,
        "updated_source_sha256": updated["source"]["sha256"],
        "trust_after_source_change": updated["trust"]["state"],
        "reconcile_before_change": before_change["counts"],
        "reconcile_with_drift": drift["counts"],
        "event_types": [
            event["type"]
            for event in store.list_events()
            if event["type"].startswith("persona.")
        ],
    }
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
