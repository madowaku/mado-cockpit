import json

import pytest

from mado_cockpit.cli import main
from mado_cockpit.design_spec import (
    CHANGE_SCHEMA,
    DesignSpecError,
    DesignSpecManager,
    render_markdown,
)
from mado_cockpit.models import Mission, Project
from mado_cockpit.store import CockpitStore


@pytest.fixture
def harness(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(Project(id="demo", name="Demo", root=str(tmp_path)))
    store.save_mission(Mission(id="MCC-UI", title="Cockpit UI"))
    manager = DesignSpecManager(store)
    manager.init("MCC-UI")
    return store, manager


def change(base=0, operations=None, source="conversation:design-session-01"):
    if operations is None:
        operations = [
            {"op": "set", "field": "goal", "value": "Review missions safely"},
            {"op": "set", "field": "audiences", "value": ["solo creator"]},
            {
                "op": "upsert", "field": "screens",
                "value": {
                    "id": "missions", "title": "Mission control",
                    "purpose": "Inspect status and evidence",
                    "states": ["loading", "ready", "empty"],
                    "actions": [{"id": "open", "label": "Open detail",
                                 "next_screen": "detail"}],
                    "accessibility": ["Keyboard focus visible"],
                },
            },
            {
                "op": "upsert", "field": "screens",
                "value": {
                    "id": "detail", "title": "Mission detail",
                    "purpose": "Review evidence and human gates",
                    "actions": [{"id": "approve", "label": "Review approval"}],
                },
            },
            {
                "op": "upsert", "field": "journeys",
                "value": {
                    "id": "review", "title": "Human approval journey",
                    "steps": [
                        {"screen_id": "missions", "action_id": "open"},
                        {"screen_id": "detail", "action_id": "approve"},
                    ],
                    "done_when": ["Human decision recorded"],
                },
            },
            {
                "op": "record_decision", "field": "decisions",
                "value": {
                    "id": "dec-1",
                    "statement": "Gate before any mutation",
                    "rationale": "Humans retain control",
                },
            },
            {
                "op": "upsert", "field": "open_questions",
                "value": {
                    "id": "q-1", "question": "What should the default view be?",
                    "choices": ["Board", "List"],
                },
            },
        ]
    return {
        "schema": CHANGE_SCHEMA, "base_revision": base,
        "source_ref": source, "initiator": "agent:codex",
        "operations": operations,
    }


def test_review_gated_promotion_persists_markdown_history_and_evidence(harness):
    store, manager = harness
    proposed = manager.propose("MCC-UI", change())
    assert proposed["status"] == "pending"
    assert manager.show("MCC-UI")["revision"] == 0
    with pytest.raises(DesignSpecError, match="human-confirm"):
        manager.review("MCC-UI", proposed["id"], decision="approve",
                       reviewer="creator", human_confirm=False)
    approved = manager.review(
        "MCC-UI", proposed["id"], decision="approve",
        reviewer="creator", human_confirm=True, note="LGTM",
    )
    assert approved["applied_revision"] == 1
    spec = manager.show("MCC-UI")
    assert spec["revision"] == 1
    assert spec["decisions"][0]["approved_by"] == "creator"
    assert spec["decisions"][0]["source_ref"] == "conversation:design-session-01"
    assert spec["journeys"][0]["steps"][0]["screen_id"] == "missions"
    assert len(manager.history("MCC-UI")) == 2
    assert "## Human-approved decisions" in render_markdown(spec)
    assert manager.validate("MCC-UI")["valid"]
    assert any(e["type"] == "design.change.approved" for e in store.list_events())
    assert manager.review("MCC-UI", proposed["id"], decision="approve",
                          reviewer="creator", human_confirm=True) == approved
    assert manager.show("MCC-UI")["revision"] == 1


def test_stale_proposal_refuses_promotion(harness):
    _, manager = harness
    first = manager.propose("MCC-UI", change(operations=[
        {"op": "set", "field": "goal", "value": "A"},
    ]))
    second = manager.propose("MCC-UI", change(operations=[
        {"op": "set", "field": "goal", "value": "B"},
    ]))
    manager.review("MCC-UI", first["id"], decision="approve",
                   reviewer="owner", human_confirm=True)
    with pytest.raises(DesignSpecError, match="stale proposal"):
        manager.review("MCC-UI", second["id"], decision="approve",
                       reviewer="owner", human_confirm=True)
    assert manager.show("MCC-UI")["goal"] == "A"
    with pytest.raises(DesignSpecError, match="stale base_revision"):
        manager.propose("MCC-UI", change())


def test_rejected_proposal_does_not_modify_spec(harness):
    _, manager = harness
    proposed = manager.propose("MCC-UI", change(operations=[
        {"op": "set", "field": "goal", "value": "Never shipped"},
    ]))
    manager.review("MCC-UI", proposed["id"], decision="reject",
                   reviewer="owner", human_confirm=True)
    assert manager.show("MCC-UI")["revision"] == 0
    with pytest.raises(DesignSpecError, match="opposite direction"):
        manager.review("MCC-UI", proposed["id"], decision="approve",
                       reviewer="owner", human_confirm=True)


@pytest.mark.parametrize("operations", [
    [{"op": "upsert", "field": "journeys",
      "value": {"id": "x", "title": "Broken",
                "steps": [{"screen_id": "missing"}]}}],
    [{"op": "upsert", "field": "screens",
      "value": {"id": "home", "title": "Home", "purpose": "View",
                "actions": [{"id": "go", "label": "Go",
                             "next_screen": "missing"}]}}],
    [{"op": "record_decision", "field": "decisions",
      "value": {"id": "../bad", "statement": "x", "rationale": "y"}}],
    [{"op": "unsafe_eval", "field": "goal", "value": "oops"}],
])
def test_invalid_ops_are_rejected_before_proposal(harness, operations):
    _, manager = harness
    with pytest.raises(DesignSpecError):
        manager.propose("MCC-UI", change(operations=operations))
    assert manager.proposals("MCC-UI") == []


def test_question_resolution_and_append_only_decisions(harness):
    _, manager = harness
    first = manager.propose("MCC-UI", change(operations=[
        {"op": "upsert", "field": "open_questions",
         "value": {"id": "q", "question": "Default layout?"}},
        {"op": "record_decision", "field": "decisions",
         "value": {"id": "d", "statement": "List first", "rationale": "Fewer controls"}},
    ]))
    manager.review("MCC-UI", first["id"], decision="approve",
                   reviewer="owner", human_confirm=True)
    second = manager.propose("MCC-UI", change(base=1, operations=[
        {"op": "resolve_question", "field": "open_questions",
         "id": "q", "value": "List"},
    ]))
    manager.review("MCC-UI", second["id"], decision="approve",
                   reviewer="owner", human_confirm=True)
    assert manager.show("MCC-UI")["open_questions"][0]["status"] == "resolved"
    assert manager.validate("MCC-UI")["open_questions"] == 0
    with pytest.raises(DesignSpecError, match="append-only"):
        manager.propose("MCC-UI", change(base=2, operations=[
            {"op": "record_decision", "field": "decisions",
             "value": {"id": "d", "statement": "Override", "rationale": "x"}},
        ]))


def test_tampered_markdown_is_detected(harness):
    store, manager = harness
    path = store.base / "design_specs" / "MCC-UI" / "spec.md"
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(DesignSpecError, match="out of sync"):
        manager.validate("MCC-UI")


def test_mission_identifier_cannot_escape_store(harness):
    _, manager = harness
    with pytest.raises(DesignSpecError, match="safe ID"):
        manager.init("../../etc")


def test_cli_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init", "--project-id", "demo"]) == 0
    assert main(["mission", "create", "MCC-UI", "Cockpit UI"]) == 0
    assert main(["design-spec", "init", "MCC-UI"]) == 0
    input_file = tmp_path / "change.json"
    input_file.write_text(json.dumps(change(operations=[
        {"op": "set", "field": "goal", "value": "Make UI specs durable"},
    ])), encoding="utf-8")
    capsys.readouterr()
    assert main(["design-spec", "propose", "MCC-UI", "--file", str(input_file)]) == 0
    proposal = json.loads(capsys.readouterr().out)
    assert main(["design-spec", "review", "MCC-UI", proposal["id"],
                 "--decision", "approve", "--reviewer", "creator",
                 "--human-confirm"]) == 0
    capsys.readouterr()
    assert main(["design-spec", "validate", "MCC-UI"]) == 0
    assert json.loads(capsys.readouterr().out)["revision"] == 1
