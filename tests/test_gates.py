import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.gates import HumanQuestionGateManager
from mado_cockpit.models import (
    Mission,
    Project,
    RecoveryAttempt,
)
from mado_cockpit.operator import OperatorManager
from mado_cockpit.store import CockpitStore


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    git(path, "init", "-b", "main")
    git(
        path,
        "config",
        "user.email",
        "fixture@example.com",
    )
    git(
        path,
        "config",
        "user.name",
        "Fixture",
    )
    (path / ".gitignore").write_text(
        ".mado/\n",
        encoding="utf-8",
    )
    (path / "README.md").write_text(
        "fixture\n",
        encoding="utf-8",
    )
    git(path, "add", ".")
    git(path, "commit", "-m", "fixture")


def setup_store(
    tmp_path: Path,
) -> CockpitStore:
    init_repo(tmp_path)
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    store.save_mission(
        Mission(
            id="MCC-M0.7",
            title="Human Question Gate",
        )
    )
    return store


def exhausted_recovery() -> list[RecoveryAttempt]:
    return [
        RecoveryAttempt(
            strategy="retry",
            status="failed",
            detail="Retry reproduced the blocker.",
        ),
        RecoveryAttempt(
            strategy="alternative_capability",
            status="no_match",
            detail="No allowed capability could resolve it.",
        ),
        RecoveryAttempt(
            strategy="alternative_worker",
            status="unavailable",
            detail="No replacement worker is available.",
        ),
        RecoveryAttempt(
            strategy="evidence_search",
            status="exhausted",
            detail="Existing evidence did not answer the decision.",
        ),
    ]


def test_gate_suppresses_implementation_detail(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    result = manager.request(
        question="PostgreSQL or SQLite?",
        reason="Storage needs a choice.",
        materiality="other",
        implementation_detail=True,
        materially_changes_result=True,
        user_has_context_to_answer=True,
    )

    assert result["ask"] is False
    assert (
        result["gate_reason"]
        == "implementation_detail"
    )
    assert manager.list() == []


def test_gate_suppresses_safe_reversible_default(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    result = manager.request(
        question="Cards or rows?",
        reason="Both preserve the same product meaning.",
        materiality="other",
        materially_changes_result=True,
        can_infer_safely=True,
        reversible_default_exists=True,
        safe_default="cards",
    )

    assert result == {
        "ask": False,
        "gate_reason": "safe_reversible_default",
        "materiality": "other",
        "choices": [],
        "allow_choose_for_me": False,
        "default_choice": None,
        "resolution": "cards",
    }


def test_gate_requires_system_to_investigate_first(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    result = manager.request(
        question="Which service limit should we design around?",
        reason="The connected service has not been inspected.",
        materiality="other",
        materially_changes_result=True,
        user_has_context_to_answer=False,
    )

    assert result["ask"] is False
    assert (
        result["gate_reason"]
        == "system_should_resolve_first"
    )


def test_operational_gate_requires_full_recovery_history(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    partial = [
        RecoveryAttempt(
            strategy="retry",
            status="failed",
            detail="Retry failed.",
        )
    ]
    result = manager.request(
        question="Should we stop this attempt or change the goal?",
        reason="The current implementation path remains blocked.",
        materiality="other",
        materially_changes_result=True,
        user_has_context_to_answer=True,
        recovery_attempts=partial,
    )

    assert result["ask"] is False
    assert (
        result["gate_reason"]
        == "recovery_required"
    )
    assert result["missing_recovery"] == [
        "alternative_capability",
        "alternative_worker",
        "evidence_search",
    ]


def test_operational_gate_opens_after_recovery_is_exhausted(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    result = manager.request(
        question="Should we stop this attempt or change the goal?",
        reason="All automatic recovery paths are exhausted.",
        materiality="other",
        choices=[
            "stop",
            "change_goal",
        ],
        impacts={
            "stop": "Preserve current evidence and end the attempt.",
            "change_goal": "Continue after the mission objective is revised.",
        },
        recommendation="stop",
        materially_changes_result=True,
        user_has_context_to_answer=True,
        recovery_attempts=exhausted_recovery(),
    )

    assert result["ask"] is True
    assert (
        result["gate_reason"]
        == "material_unresolved_decision"
    )
    gate = result["gate"]
    assert len(
        gate["recovery_attempts"]
    ) == 4
    assert (
        result["status"]["status"]
        == "open"
    )


def test_consent_gate_opens_without_fake_recovery_and_safe_default_resolves(
    tmp_path,
):
    store = setup_store(tmp_path)
    manager = HumanQuestionGateManager(
        store
    )

    opened = manager.request(
        question=(
            "This can start a paid service. "
            "Do you want to enable it, or stay on the free path?"
        ),
        reason="Enabling it may create charges.",
        materiality="cost",
        choices=[
            "enable_paid",
            "stay_free",
        ],
        impacts={
            "enable_paid": "May create charges.",
            "stay_free": "Keeps the current zero-cost path.",
        },
        recommendation="stay_free",
        safe_default="stay_free",
        consent_required=True,
        materially_changes_result=True,
    )

    assert opened["ask"] is True
    assert (
        opened["gate_reason"]
        == "consent_required"
    )
    assert (
        opened["gate"][
            "allow_choose_for_me"
        ]
        is True
    )

    gate_id = opened["gate"]["id"]
    gate_path = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "gates"
        / gate_id
        / "gate.json"
    )
    original = json.loads(
        gate_path.read_text(
            encoding="utf-8"
        )
    )

    resolved = manager.resolve(
        gate_id,
        choose_for_me=True,
    )

    assert (
        resolved["resolution"]["choice"]
        == "stay_free"
    )
    assert (
        resolved["resolution"]["method"]
        == "safe_default"
    )
    assert (
        resolved["status"]["status"]
        == "resolved"
    )
    assert json.loads(
        gate_path.read_text(
            encoding="utf-8"
        )
    ) == original


def test_gate_rejects_avoidable_technical_jargon(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    with pytest.raises(
        RuntimeError,
        match="implementation jargon",
    ):
        manager.request(
            question=(
                "Should I use PostgreSQL or SQLite?"
            ),
            reason="Technical choice.",
            materiality="core_meaning",
            materially_changes_result=True,
            user_has_context_to_answer=True,
        )


def test_operator_pauses_for_gate_and_resumes_after_resolution(
    tmp_path,
):
    store = setup_store(tmp_path)
    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.7",
        "Build the Human Question Gate fixture",
        required_evidence=[
            "git_diff",
        ],
    )
    operator_id = run["plan"]["id"]

    gated = operator.request_gate(
        operator_id,
        question=(
            "Should this project be visible only "
            "to invited people, or publicly?"
        ),
        reason=(
            "This changes who can see the project."
        ),
        materiality="privacy",
        choices=[
            "invite_only",
            "public",
        ],
        impacts={
            "invite_only": (
                "Only invited people can view it."
            ),
            "public": (
                "Anyone can view it."
            ),
        },
        recommendation="invite_only",
        safe_default="invite_only",
        materially_changes_result=True,
        user_has_context_to_answer=True,
    )

    paused = gated["operator"]
    assert (
        paused["state"]["status"]
        == "awaiting_human"
    )
    assert (
        paused["next_action"]
        == "resolve_human_question_gate"
    )
    assert (
        paused["human_gate"][
            "status"
        ]["status"]
        == "open"
    )

    with pytest.raises(
        RuntimeError,
        match="waiting for Human Question Gate",
    ):
        operator.launch(
            operator_id,
            "builder",
            sessions=None,
        )

    advanced = operator.advance(
        operator_id
    )
    assert (
        advanced["state"]["status"]
        == "awaiting_human"
    )

    resumed = operator.resolve_gate(
        operator_id,
        choice="invite_only",
        note="Keep the first fixture private.",
    )["operator"]

    assert (
        resumed["state"]["status"]
        == "awaiting_builder"
    )
    assert (
        resumed["state"][
            "current_gate_id"
        ]
        is None
    )
    assert resumed["human_gate"] is None


def test_gate_events_record_requested_and_resolved(
    tmp_path,
):
    store = setup_store(tmp_path)
    manager = HumanQuestionGateManager(
        store
    )

    opened = manager.request(
        question="Should each person pick one favorite or rank several options?",
        reason="These create meaningfully different voting experiences.",
        materiality="core_meaning",
        choices=[
            "pick_one",
            "rank_options",
        ],
        materially_changes_result=True,
        user_has_context_to_answer=True,
        mission_id="MCC-M0.7",
    )
    manager.resolve(
        opened["gate"]["id"],
        choice="pick_one",
    )

    event_types = [
        json.loads(line)["type"]
        for line in store.events_file.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    assert "gate.requested" in event_types
    assert "gate.resolved" in event_types


def test_recovery_success_suppresses_human_escalation(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    result = manager.request(
        question="Should we change the goal?",
        reason="A retry was attempted.",
        materiality="other",
        materially_changes_result=True,
        user_has_context_to_answer=True,
        recovery_attempts=[
            RecoveryAttempt(
                strategy="retry",
                status="succeeded",
                detail="Retry completed successfully.",
            )
        ],
    )

    assert result["ask"] is False
    assert (
        result["gate_reason"]
        == "recovery_succeeded"
    )


def test_invalid_recovery_status_is_rejected(
    tmp_path,
):
    manager = HumanQuestionGateManager(
        setup_store(tmp_path)
    )

    with pytest.raises(
        RuntimeError,
        match="Unsupported recovery status",
    ):
        manager.request(
            question="Should we change the goal?",
            reason="Invalid recovery metadata.",
            materiality="other",
            materially_changes_result=True,
            user_has_context_to_answer=True,
            recovery_attempts=[
                RecoveryAttempt(
                    strategy="retry",
                    status="maybe",
                    detail="Ambiguous status.",
                )
            ],
        )
