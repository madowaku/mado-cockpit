from pathlib import Path

import pytest

from mado_cockpit.models import Project
from mado_cockpit.persona_registry import (
    DEFAULT_REPOSITORY,
    ExternalPersonaRegistry,
    PersonaRegistryError,
    main,
)
from mado_cockpit.store import CockpitStore


def _agent_text(
    name: str,
    *,
    description: str = "A focused external specialist",
    mission: str = "Build the smallest evidence-backed result.",
    extra: str = "",
) -> str:
    return f"""---
name: {name}
description: {description}
color: purple
emoji: TEST
vibe: Evidence-first specialist.
---

# {name} Agent Personality

You have persistent memory claims that the host must verify separately.

## Your Core Mission

### Deliver useful work
- {mission}

## Critical Rules You Must Follow

### Evidence Before Claims
- Never claim success without evidence.

### Respect Boundaries
- Do not invent runtime capabilities.

## Your Technical Deliverables

### Implementation
- A focused implementation.

### Verification
- A reproducible verification artifact.

## Your Success Metrics

- Required evidence is present.
- Unsupported capability claims are not treated as powers.

{extra}
"""


def _write_agent(
    root: Path,
    relative_path: str,
    name: str,
    *,
    extra: str = "",
) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _agent_text(name, extra=extra),
        encoding="utf-8",
    )
    return path


def _registry(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="m2.5-fixture",
            name="M2.5 Fixture",
            root=str(tmp_path),
        )
    )
    return store, ExternalPersonaRegistry(store)


def test_intake_normalizes_and_snapshots_external_persona(tmp_path):
    store, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    source = _write_agent(
        upstream,
        "game-development/godot/godot-gameplay-scripter.md",
        "Godot Gameplay Scripter",
    )

    receipt = registry.intake_tree(
        upstream,
        revision="abc123",
        divisions=["game-development"],
    )

    assert receipt["counts"]["created"] == 1
    persona_id = receipt["items"][0]["persona_id"]
    record = registry.inspect(persona_id)

    assert record["provider"] == "agency-agents"
    assert record["division"] == "game-development"
    assert record["slug"] == "godot-gameplay-scripter"
    assert record["trust"]["state"] == "experimental"
    assert record["source"]["revision"] == "abc123"
    assert (
        record["contract"]["mission_summary"]
        == "Deliver useful work"
    )
    assert record["contract"]["critical_rule_headings"] == [
        "Evidence Before Claims",
        "Respect Boundaries",
    ]
    assert record["contract"]["capability_assumptions"]["status"] == (
        "unverified"
    )
    assert record["contract"]["runtime_claims"]["persistent_memory"] == (
        "unverified"
    )

    snapshot = tmp_path / record["snapshot"]["path"]
    assert snapshot.read_bytes() == source.read_bytes()
    assert registry.registry_file.exists()
    assert any(
        event["type"] == "persona.intake.completed"
        for event in store.list_events()
    )


def test_non_agent_markdown_is_skipped(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    upstream.mkdir()
    (upstream / "README.md").write_text(
        "# Not a persona\n",
        encoding="utf-8",
    )
    _write_agent(
        upstream,
        "testing/testing-evidence-collector.md",
        "Evidence Collector",
    )

    receipt = registry.intake_tree(
        upstream,
        revision="rev-1",
    )

    assert receipt["counts"]["intaken"] == 1
    assert receipt["counts"]["skipped_non_agents"] == 1


def test_filters_fail_closed_when_requested_agent_is_missing(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    _write_agent(
        upstream,
        "engineering/engineering-code-reviewer.md",
        "Code Reviewer",
    )

    with pytest.raises(
        PersonaRegistryError,
        match="were not found",
    ):
        registry.intake_tree(
            upstream,
            revision="rev-1",
            agents=["godot-gameplay-scripter"],
        )


def test_trust_promotion_requires_human_actor_and_review_note(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    _write_agent(
        upstream,
        "testing/testing-evidence-collector.md",
        "Evidence Collector",
    )
    receipt = registry.intake_tree(
        upstream,
        revision="rev-1",
    )
    persona_id = receipt["items"][0]["persona_id"]

    with pytest.raises(
        PersonaRegistryError,
        match="human:<id>",
    ):
        registry.set_trust(
            persona_id,
            state="trusted",
            actor="agent:builder",
            note="Reviewed.",
        )

    with pytest.raises(
        PersonaRegistryError,
        match="review note",
    ):
        registry.set_trust(
            persona_id,
            state="trusted",
            actor="human:owner",
        )

    trusted = registry.set_trust(
        persona_id,
        state="trusted",
        actor="human:owner",
        note="Reviewed source and accepted the persona constraints.",
    )

    assert trusted["trust"]["state"] == "trusted"
    review_log = (
        registry.reviews_dir / f"{persona_id}.jsonl"
    ).read_text(encoding="utf-8")
    assert '"to_state": "trusted"' in review_log


def test_same_content_new_revision_preserves_trust(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    _write_agent(
        upstream,
        "engineering/engineering-code-reviewer.md",
        "Code Reviewer",
    )
    first = registry.intake_tree(
        upstream,
        revision="rev-1",
    )
    persona_id = first["items"][0]["persona_id"]
    registry.set_trust(
        persona_id,
        state="trusted",
        actor="human:owner",
        note="Reviewed exact source bytes.",
    )

    second = registry.intake_tree(
        upstream,
        revision="rev-2",
    )
    record = registry.inspect(persona_id)

    assert second["items"][0]["intake_status"] == "revision_updated"
    assert record["source"]["revision"] == "rev-2"
    assert record["trust"]["state"] == "trusted"


def test_changed_source_resets_trust_and_keeps_stable_identity(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    source = _write_agent(
        upstream,
        "game-development/godot/godot-gameplay-scripter.md",
        "Godot Gameplay Scripter",
    )
    first = registry.intake_tree(
        upstream,
        revision="rev-1",
    )
    persona_id = first["items"][0]["persona_id"]
    trusted = registry.set_trust(
        persona_id,
        state="trusted",
        actor="human:owner",
        note="Reviewed exact source bytes.",
    )
    trusted_sha = trusted["source"]["sha256"]

    source.write_text(
        _agent_text(
            "Godot Gameplay Scripter",
            extra="\n## New Upstream Rule\n- Changed source.\n",
        ),
        encoding="utf-8",
    )

    second = registry.intake_tree(
        upstream,
        revision="rev-2",
    )
    record = registry.inspect(persona_id)

    assert second["items"][0]["persona_id"] == persona_id
    assert second["items"][0]["intake_status"] == "updated"
    assert record["trust"]["state"] == "experimental"
    assert record["previous_source_sha256"] == trusted_sha
    assert record["source"]["sha256"] != trusted_sha
    assert (
        record["trust"]["source_sha256"]
        == record["source"]["sha256"]
    )


def test_reconcile_reports_current_changed_removed_and_unregistered(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    current = _write_agent(
        upstream,
        "engineering/current.md",
        "Current Agent",
    )
    changed = _write_agent(
        upstream,
        "testing/changed.md",
        "Changed Agent",
    )
    removed = _write_agent(
        upstream,
        "design/removed.md",
        "Removed Agent",
    )
    registry.intake_tree(
        upstream,
        revision="rev-1",
    )

    changed.write_text(
        _agent_text(
            "Changed Agent",
            extra="\nChanged after intake.\n",
        ),
        encoding="utf-8",
    )
    removed.unlink()
    _write_agent(
        upstream,
        "game-development/new-agent.md",
        "New Agent",
    )

    report = registry.reconcile(upstream)

    assert current.exists()
    assert report["counts"] == {
        "current": 1,
        "changed": 1,
        "removed": 1,
        "unregistered": 1,
    }
    statuses = {
        item["path"]: item["status"]
        for item in report["items"]
    }
    assert statuses["engineering/current.md"] == "current"
    assert statuses["testing/changed.md"] == "changed"
    assert statuses["design/removed.md"] == "removed"
    assert statuses["game-development/new-agent.md"] == "unregistered"


def test_intake_rejects_path_escape(tmp_path):
    _, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    upstream.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text(
        _agent_text("Outside Agent"),
        encoding="utf-8",
    )

    with pytest.raises(
        PersonaRegistryError,
        match="inside source_root",
    ):
        registry.intake_file(
            outside,
            source_root=upstream,
            repository=DEFAULT_REPOSITORY,
            revision="rev-1",
        )


def test_event_ledger_records_intake_and_trust_changes(tmp_path):
    store, registry = _registry(tmp_path)
    upstream = tmp_path / "agency-agents"
    _write_agent(
        upstream,
        "testing/testing-evidence-collector.md",
        "Evidence Collector",
    )
    receipt = registry.intake_tree(
        upstream,
        revision="rev-1",
    )
    persona_id = receipt["items"][0]["persona_id"]
    registry.set_trust(
        persona_id,
        state="reviewed",
        actor="human:owner",
        note="Reviewed but not yet trusted.",
    )

    event_types = [
        event["type"]
        for event in store.list_events()
    ]
    assert "persona.intake.recorded" in event_types
    assert "persona.intake.completed" in event_types
    assert "persona.trust.changed" in event_types


def test_module_cli_intake_and_reconcile(tmp_path, capsys):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="m2.5-cli",
            name="M2.5 CLI",
            root=str(tmp_path),
        )
    )
    upstream = tmp_path / "agency-agents"
    _write_agent(
        upstream,
        "testing/testing-evidence-collector.md",
        "Evidence Collector",
    )

    code = main(
        [
            "--root",
            str(tmp_path),
            "intake",
            "--source-root",
            str(upstream),
            "--revision",
            "rev-cli",
            "--agent",
            "testing-evidence-collector",
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert '"ok": true' in output.lower()

    code = main(
        [
            "--root",
            str(tmp_path),
            "reconcile",
            "--source-root",
            str(upstream),
        ]
    )
    output = capsys.readouterr().out

    assert code == 0
    assert '"current": 1' in output
