import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.evidence import EvidenceManager
from mado_cockpit.handoffs import HandoffManager
from mado_cockpit.models import Mission, Project, Worker
from mado_cockpit.store import CockpitStore
from mado_cockpit.worktrees import WorktreeManager


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


def setup_team(
    tmp_path: Path,
) -> tuple[
    CockpitStore,
    object,
    object,
    EvidenceManager,
    HandoffManager,
]:
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
            id="MCC-M0.4",
            title="Builder to QA Handoff",
        )
    )
    store.save_worker(
        Worker(
            id="builder",
            role="builder",
            mission_id="MCC-M0.4",
            provider="codex",
        )
    )
    store.save_worker(
        Worker(
            id="qa",
            role="qa",
            mission_id="MCC-M0.4",
            provider="codex",
        )
    )

    worktrees = WorktreeManager(store)
    builder_workspace = worktrees.create(
        "builder"
    )
    qa_workspace = worktrees.create(
        "qa"
    )

    return (
        store,
        builder_workspace,
        qa_workspace,
        EvidenceManager(store),
        HandoffManager(store),
    )


def make_builder_ready(
    builder_workspace,
    evidence: EvidenceManager,
) -> dict:
    evidence.create_task(
        "MCC-M0.4-BUILD",
        "builder",
        "Implement the handoff fixture",
        required_evidence=[
            "git_diff",
            "test_result",
        ],
    )

    builder_path = Path(
        builder_workspace.path
    )
    (
        builder_path / "feature.txt"
    ).write_text(
        "builder implementation\n",
        encoding="utf-8",
    )
    (
        builder_path / "tests.txt"
    ).write_text(
        "7 passed\n",
        encoding="utf-8",
    )

    return evidence.submit_result(
        "MCC-M0.4-BUILD",
        status="completed",
        summary="Builder implementation complete.",
        evidence_files=[
            ("test_result", "tests.txt"),
        ],
    )


def test_builder_to_qa_handoff_passes_with_independent_report(
    tmp_path,
):
    (
        store,
        builder_workspace,
        qa_workspace,
        evidence,
        handoffs,
    ) = setup_team(tmp_path)
    builder_result = make_builder_ready(
        builder_workspace,
        evidence,
    )

    created = handoffs.create(
        "MCC-M0.4-BUILD",
        "qa",
    )
    handoff = created["handoff"]

    assert (
        handoff["source_result_id"]
        == builder_result["result"]["id"]
    )
    assert (
        handoff["source_bundle_id"]
        == builder_result["bundle"]["id"]
    )
    assert handoff["source_worker_id"] == "builder"
    assert handoff["qa_worker_id"] == "qa"
    assert created["status"]["status"] == "awaiting_qa"

    snapshot = (
        Path(qa_workspace.path)
        / handoff["snapshot_path"]
    )
    assert snapshot.is_dir()
    assert (snapshot / "manifest.json").is_file()
    assert (snapshot / "task.json").is_file()
    assert (snapshot / "result.json").is_file()

    qa_task = evidence.get_task(
        handoff["qa_task_id"]
    )
    assert qa_task["worker_id"] == "qa"
    assert qa_task["required_evidence"] == [
        "qa_report"
    ]

    qa_report = (
        Path(qa_workspace.path)
        / "qa-report.txt"
    )
    qa_report.write_text(
        (
            "Checks:\n"
            "- source bundle intact\n"
            "- builder tests reported 7 passed\n"
            "Verdict: pass\n"
        ),
        encoding="utf-8",
    )

    qa_result = evidence.submit_result(
        handoff["qa_task_id"],
        status="completed",
        summary="Independent QA checks passed.",
        evidence_files=[
            ("qa_report", "qa-report.txt"),
        ],
    )

    resolved = handoffs.submit_verdict(
        handoff["id"],
        qa_result["result"]["id"],
        verdict="pass",
        summary="QA accepts the handoff evidence.",
    )

    assert resolved["status"]["status"] == "pass"
    assert resolved["verdict"]["verdict"] == "pass"
    assert (
        resolved["verdict"][
            "source_snapshot_sha256"
        ]
        == handoff["snapshot_sha256"]
    )
    assert (
        evidence.get_task(
            "MCC-M0.4-BUILD"
        )["status"]
        == "qa_passed"
    )

    immutable = json.loads(
        (
            tmp_path
            / ".mado"
            / "cockpit"
            / "handoffs"
            / handoff["id"]
            / "handoff.json"
        ).read_text(encoding="utf-8")
    )
    assert immutable == handoff

    events = [
        json.loads(line)
        for line in store.events_file.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]
    event_types = {
        event["type"]
        for event in events
    }
    assert "handoff.created" in event_types
    assert "handoff.materialized" in event_types
    assert "qa.verdict" in event_types
    assert "handoff.resolved" in event_types


def test_handoff_requires_source_ready_for_qa(
    tmp_path,
):
    (
        _,
        _,
        _,
        evidence,
        handoffs,
    ) = setup_team(tmp_path)

    evidence.create_task(
        "MCC-M0.4-INCOMPLETE",
        "builder",
        "Incomplete builder attempt",
        required_evidence=[
            "test_result",
        ],
    )

    with pytest.raises(
        RuntimeError,
        match="not ready_for_qa",
    ):
        handoffs.create(
            "MCC-M0.4-INCOMPLETE",
            "qa",
        )


def test_source_worker_cannot_review_its_own_work(
    tmp_path,
):
    (
        store,
        builder_workspace,
        _,
        evidence,
        handoffs,
    ) = setup_team(tmp_path)
    make_builder_ready(
        builder_workspace,
        evidence,
    )

    store.get_worker("builder")

    with pytest.raises(
        RuntimeError,
        match="cannot QA its own work",
    ):
        handoffs.create(
            "MCC-M0.4-BUILD",
            "builder",
        )


def test_qa_verdict_rejects_modified_source_snapshot(
    tmp_path,
):
    (
        _,
        builder_workspace,
        qa_workspace,
        evidence,
        handoffs,
    ) = setup_team(tmp_path)
    make_builder_ready(
        builder_workspace,
        evidence,
    )

    created = handoffs.create(
        "MCC-M0.4-BUILD",
        "qa",
    )
    handoff = created["handoff"]

    qa_report = (
        Path(qa_workspace.path)
        / "qa-report.txt"
    )
    qa_report.write_text(
        "Verdict candidate: pass\n",
        encoding="utf-8",
    )
    qa_result = evidence.submit_result(
        handoff["qa_task_id"],
        status="completed",
        summary="QA completed.",
        evidence_files=[
            ("qa_report", "qa-report.txt"),
        ],
    )

    snapshot_result = (
        Path(qa_workspace.path)
        / handoff["snapshot_path"]
        / "result.json"
    )
    snapshot_result.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="snapshot was modified",
    ):
        handoffs.submit_verdict(
            handoff["id"],
            qa_result["result"]["id"],
            verdict="pass",
            summary="Should not pass.",
        )

    assert (
        handoffs.inspect(
            handoff["id"]
        )["status"]["status"]
        == "awaiting_qa"
    )


def test_needs_fix_routes_source_task_back_to_builder(
    tmp_path,
):
    (
        _,
        builder_workspace,
        qa_workspace,
        evidence,
        handoffs,
    ) = setup_team(tmp_path)
    make_builder_ready(
        builder_workspace,
        evidence,
    )

    created = handoffs.create(
        "MCC-M0.4-BUILD",
        "qa",
    )
    handoff = created["handoff"]

    (
        Path(qa_workspace.path)
        / "qa-report.txt"
    ).write_text(
        (
            "Finding: missing regression case.\n"
            "Verdict: needs_fix\n"
        ),
        encoding="utf-8",
    )
    qa_result = evidence.submit_result(
        handoff["qa_task_id"],
        status="completed",
        summary="QA found a regression gap.",
        evidence_files=[
            ("qa_report", "qa-report.txt"),
        ],
    )

    resolved = handoffs.submit_verdict(
        handoff["id"],
        qa_result["result"]["id"],
        verdict="needs_fix",
        summary="Add the missing regression case.",
    )

    assert (
        resolved["status"]["status"]
        == "needs_fix"
    )
    assert (
        evidence.get_task(
            "MCC-M0.4-BUILD"
        )["status"]
        == "needs_fix"
    )
