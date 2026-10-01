import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.evidence import EvidenceManager
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


def setup_builder(
    tmp_path: Path,
) -> tuple[CockpitStore, object, EvidenceManager]:
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
            id="MCC-M0.3",
            title="Evidence Return",
        )
    )
    store.save_worker(
        Worker(
            id="builder",
            role="builder",
            mission_id="MCC-M0.3",
            provider="codex",
        )
    )
    workspace = WorktreeManager(
        store
    ).create("builder")
    return (
        store,
        workspace,
        EvidenceManager(store),
    )


def test_completed_result_becomes_ready_for_qa_with_required_evidence(
    tmp_path,
):
    store, workspace, manager = setup_builder(
        tmp_path
    )
    manager.create_task(
        "MCC-M0.3-BUILD",
        "builder",
        "Implement the evidence fixture",
        required_evidence=[
            "git_diff",
            "test_result",
        ],
        constraints=[
            "No unrelated refactor",
        ],
        deliverables=[
            "implementation",
            "tests",
        ],
        done_when=[
            "required evidence is present",
        ],
    )

    workspace_path = Path(workspace.path)
    (
        workspace_path
        / "implementation.txt"
    ).write_text(
        "builder change\n",
        encoding="utf-8",
    )
    (
        workspace_path
        / "tests.txt"
    ).write_text(
        "3 passed\n",
        encoding="utf-8",
    )

    submitted = manager.submit_result(
        "MCC-M0.3-BUILD",
        status="completed",
        summary="Fixture implemented and tested.",
        evidence_files=[
            ("test_result", "tests.txt"),
        ],
        changes=[
            "implementation.txt",
        ],
        risks=[],
    )

    result = submitted["result"]
    bundle = submitted["bundle"]

    assert result["status"] == "completed"
    assert result["evidence_status"] == "validated"
    assert result["readiness"] == "ready_for_qa"
    assert result["missing_evidence"] == []

    assert bundle["status"] == "validated"
    assert bundle["missing_evidence"] == []

    kinds = {
        item["kind"]
        for item in bundle["items"]
    }
    assert kinds == {
        "git_diff",
        "test_result",
    }

    for item in bundle["items"]:
        path = tmp_path / item["path"]
        assert path.is_file()
        digest = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        assert digest == item["sha256"]
        assert path.stat().st_size == item["size_bytes"]

    manifest = manager.inspect_bundle(
        bundle["id"]
    )
    assert manifest["id"] == bundle["id"]
    assert manifest["task_id"] == "MCC-M0.3-BUILD"

    stored_task = manager.get_task(
        "MCC-M0.3-BUILD"
    )
    assert (
        stored_task["status"]
        == "ready_for_qa"
    )

    assert store.event_count() == 8


def test_completed_claim_does_not_pass_without_required_evidence(
    tmp_path,
):
    _, _, manager = setup_builder(tmp_path)
    manager.create_task(
        "MCC-M0.3-NO-PROOF",
        "builder",
        "Claim completion without proof",
        required_evidence=[
            "git_diff",
            "test_result",
        ],
    )

    submitted = manager.submit_result(
        "MCC-M0.3-NO-PROOF",
        status="completed",
        summary="Done.",
    )

    result = submitted["result"]
    bundle = submitted["bundle"]

    assert result["status"] == "completed"
    assert result["evidence_status"] == "incomplete"
    assert result["readiness"] == "incomplete"
    assert set(result["missing_evidence"]) == {
        "git_diff",
        "test_result",
    }

    assert bundle["status"] == "incomplete"
    assert bundle["items"] == []

    stored_task = manager.get_task(
        "MCC-M0.3-NO-PROOF"
    )
    assert (
        stored_task["status"]
        == "evidence_incomplete"
    )


def test_evidence_file_cannot_escape_worker_workspace(
    tmp_path,
):
    _, _, manager = setup_builder(tmp_path)
    manager.create_task(
        "MCC-M0.3-BOUNDARY",
        "builder",
        "Keep evidence inside the worker workspace",
        required_evidence=[
            "test_result",
        ],
    )

    outside = tmp_path / "outside.txt"
    outside.write_text(
        "not worker evidence\n",
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="must live inside",
    ):
        manager.submit_result(
            "MCC-M0.3-BOUNDARY",
            status="completed",
            summary="Attempted invalid evidence.",
            evidence_files=[
                ("test_result", str(outside)),
            ],
        )


def test_bundle_contains_task_and_result_snapshots(
    tmp_path,
):
    _, workspace, manager = setup_builder(
        tmp_path
    )
    manager.create_task(
        "MCC-M0.3-SNAPSHOT",
        "builder",
        "Freeze contracts with the evidence bundle",
        required_evidence=[
            "git_diff",
        ],
    )

    Path(
        workspace.path,
        "change.txt",
    ).write_text(
        "changed\n",
        encoding="utf-8",
    )

    submitted = manager.submit_result(
        "MCC-M0.3-SNAPSHOT",
        status="completed",
        summary="Snapshot fixture complete.",
    )
    bundle = submitted["bundle"]

    bundle_root = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "evidence"
        / "MCC-M0.3-SNAPSHOT"
        / bundle["id"]
    )

    task_snapshot = json.loads(
        (bundle_root / "task.json").read_text(
            encoding="utf-8"
        )
    )
    result_snapshot = json.loads(
        (bundle_root / "result.json").read_text(
            encoding="utf-8"
        )
    )

    assert (
        task_snapshot["objective"]
        == "Freeze contracts with the evidence bundle"
    )
    assert (
        result_snapshot["evidence_bundle_id"]
        == bundle["id"]
    )
    assert (
        result_snapshot["readiness"]
        == "ready_for_qa"
    )


def test_task_contract_requires_evidence_policy(
    tmp_path,
):
    _, _, manager = setup_builder(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="requires at least one",
    ):
        manager.create_task(
            "MCC-M0.3-NO-CONTRACT",
            "builder",
            "Do work without evidence policy",
        )


def test_failed_result_never_becomes_ready_for_qa(
    tmp_path,
):
    _, workspace, manager = setup_builder(
        tmp_path
    )
    manager.create_task(
        "MCC-M0.3-FAILED",
        "builder",
        "Capture evidence from a failed attempt",
        required_evidence=[
            "git_diff",
        ],
    )

    Path(
        workspace.path,
        "failed-change.txt",
    ).write_text(
        "partial work\n",
        encoding="utf-8",
    )

    submitted = manager.submit_result(
        "MCC-M0.3-FAILED",
        status="failed",
        summary="Implementation failed after partial changes.",
    )

    assert (
        submitted["bundle"]["status"]
        == "validated"
    )
    assert (
        submitted["result"]["evidence_status"]
        == "validated"
    )
    assert (
        submitted["result"]["readiness"]
        == "not_completed"
    )
    assert (
        manager.get_task(
            "MCC-M0.3-FAILED"
        )["status"]
        == "result_failed"
    )
