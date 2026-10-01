import subprocess
from pathlib import Path

from mado_cockpit.models import Mission, Project
from mado_cockpit.operator import OperatorManager
from mado_cockpit.providers import ProviderTurnResult
from mado_cockpit.sessions import SessionManager
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


def setup_operator(
    tmp_path: Path,
) -> tuple[
    CockpitStore,
    OperatorManager,
    dict,
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
            id="MCC-M0.5",
            title="Operator",
        )
    )
    manager = OperatorManager(store)
    run = manager.start(
        "MCC-M0.5",
        "Implement the operator fixture",
        required_evidence=[
            "git_diff",
            "test_result",
        ],
    )
    return store, manager, run


def test_operator_runs_builder_to_qa_pass_loop(
    tmp_path,
):
    store, manager, run = setup_operator(
        tmp_path
    )
    operator_id = run["plan"]["id"]

    assert (
        run["state"]["status"]
        == "awaiting_builder"
    )
    assert (
        run["builder_task"]["status"]
        == "assigned"
    )
    assert (
        store.get_worker(
            run["plan"]["builder_worker_id"]
        )["role"]
        == "builder"
    )
    assert (
        store.get_worker(
            run["plan"]["qa_worker_id"]
        )["role"]
        == "qa"
    )

    builder_workspace = Path(
        run["builder_workspace"]["path"]
    )
    (
        builder_workspace
        / "implementation.txt"
    ).write_text(
        "operator implementation\n",
        encoding="utf-8",
    )
    (
        builder_workspace
        / "tests.txt"
    ).write_text(
        "11 passed\n",
        encoding="utf-8",
    )

    builder_submission = (
        manager.submit_result(
            operator_id,
            "builder",
            status="completed",
            summary=(
                "Builder implementation complete."
            ),
            evidence_files=[
                (
                    "test_result",
                    "tests.txt",
                )
            ],
        )
    )
    after_builder = (
        builder_submission["operator"]
    )

    assert (
        after_builder["state"]["status"]
        == "awaiting_qa"
    )
    assert after_builder["handoff"] is not None
    first_handoff_id = (
        after_builder["handoff"][
            "handoff"
        ]["id"]
    )
    assert (
        after_builder["qa_task"][
            "required_evidence"
        ]
        == ["qa_report"]
    )

    repeated = manager.advance(
        operator_id
    )
    assert (
        repeated["handoff"][
            "handoff"
        ]["id"]
        == first_handoff_id
    )
    assert (
        manager.summary()[
            "active_operator_count"
        ]
        == 1
    )

    qa_workspace = Path(
        after_builder[
            "qa_workspace"
        ]["path"]
    )
    (
        qa_workspace
        / "qa-report.txt"
    ).write_text(
        (
            "Checks:\n"
            "- source snapshot reviewed\n"
            "- evidence reviewed\n"
            "Verdict candidate: pass\n"
        ),
        encoding="utf-8",
    )

    qa_submission = (
        manager.submit_result(
            operator_id,
            "qa",
            status="completed",
            summary="Independent QA complete.",
            evidence_files=[
                (
                    "qa_report",
                    "qa-report.txt",
                )
            ],
        )
    )
    assert (
        qa_submission["operator"][
            "state"
        ]["status"]
        == "awaiting_verdict"
    )

    resolved = manager.verdict(
        operator_id,
        verdict="pass",
        summary=(
            "QA accepts the Builder result."
        ),
    )
    final = resolved["operator"]

    assert (
        final["state"]["status"]
        == "completed"
    )
    assert final["next_action"] == "done"
    assert (
        final["builder_task"]["status"]
        == "qa_passed"
    )
    assert (
        manager.summary()[
            "completed_operator_count"
        ]
        == 1
    )


def test_operator_needs_fix_creates_new_handoff_after_revision(
    tmp_path,
):
    _, manager, run = setup_operator(
        tmp_path
    )
    operator_id = run["plan"]["id"]
    builder_workspace = Path(
        run["builder_workspace"]["path"]
    )

    (
        builder_workspace
        / "implementation.txt"
    ).write_text(
        "version one\n",
        encoding="utf-8",
    )
    (
        builder_workspace
        / "tests.txt"
    ).write_text(
        "5 passed\n",
        encoding="utf-8",
    )

    after_builder = (
        manager.submit_result(
            operator_id,
            "builder",
            status="completed",
            summary="First Builder attempt.",
            evidence_files=[
                (
                    "test_result",
                    "tests.txt",
                )
            ],
        )["operator"]
    )
    first_handoff_id = (
        after_builder["handoff"][
            "handoff"
        ]["id"]
    )

    qa_workspace = Path(
        after_builder[
            "qa_workspace"
        ]["path"]
    )
    (
        qa_workspace
        / "qa-report.txt"
    ).write_text(
        "Regression case missing.\n",
        encoding="utf-8",
    )
    manager.submit_result(
        operator_id,
        "qa",
        status="completed",
        summary="QA found a regression gap.",
        evidence_files=[
            (
                "qa_report",
                "qa-report.txt",
            )
        ],
    )
    needs_fix = manager.verdict(
        operator_id,
        verdict="needs_fix",
        summary="Add the regression case.",
    )["operator"]

    assert (
        needs_fix["state"]["status"]
        == "needs_fix"
    )
    assert (
        needs_fix["next_action"]
        == "revise_builder_task"
    )

    (
        builder_workspace
        / "implementation.txt"
    ).write_text(
        "version two\n",
        encoding="utf-8",
    )
    (
        builder_workspace
        / "tests.txt"
    ).write_text(
        "6 passed\n",
        encoding="utf-8",
    )

    revised = manager.submit_result(
        operator_id,
        "builder",
        status="completed",
        summary="Builder revision complete.",
        evidence_files=[
            (
                "test_result",
                "tests.txt",
            )
        ],
    )["operator"]

    second_handoff_id = (
        revised["handoff"][
            "handoff"
        ]["id"]
    )
    assert (
        second_handoff_id
        != first_handoff_id
    )
    assert (
        revised["state"]["status"]
        == "awaiting_qa"
    )


class FakeProvider:
    name = "codex"

    def __init__(self) -> None:
        self.starts = 0
        self.sends = 0

    def start(
        self,
        *,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        self.starts += 1
        thread = (
            f"thread-{workspace.name}"
        )
        return ProviderTurnResult(
            external_session_id=thread,
            exit_code=0,
            stdout=(
                '{"type":"thread.started",'
                f'"thread_id":"{thread}"'
                '}\n'
            ),
            stderr="",
            last_message=prompt,
        )

    def send(
        self,
        *,
        external_session_id: str,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        self.sends += 1
        return ProviderTurnResult(
            external_session_id=(
                external_session_id
            ),
            exit_code=0,
            stdout=(
                '{"type":"thread.started",'
                f'"thread_id":"'
                f'{external_session_id}"'
                '}\n'
            ),
            stderr="",
            last_message=prompt,
        )

    def status(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        return {
            "process_running": False,
        }

    def stop(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        return {
            "stopped": True,
        }


def test_operator_launch_resumes_active_session_and_binds_trace(
    tmp_path,
):
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
            id="MCC-M0.5",
            title="Operator",
        )
    )

    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.5",
        "Exercise the agent session bridge",
        required_evidence=[
            "session_trace",
        ],
    )
    operator_id = run["plan"]["id"]

    provider = FakeProvider()
    sessions = SessionManager(
        store,
        providers={
            "codex": provider,
        },
    )

    first = operator.launch(
        operator_id,
        "builder",
        sessions=sessions,
        model="fixture-model",
    )
    first_session = first[
        "builder_session"
    ]
    assert first_session["turn_count"] == 1
    assert provider.starts == 1

    second = operator.launch(
        operator_id,
        "builder",
        sessions=sessions,
        model="fixture-model",
    )
    second_session = second[
        "builder_session"
    ]
    assert (
        second_session["id"]
        == first_session["id"]
    )
    assert second_session["turn_count"] == 2
    assert provider.starts == 1
    assert provider.sends == 1

    submitted = operator.submit_result(
        operator_id,
        "builder",
        status="completed",
        summary="Session-backed result.",
    )

    result = (
        submitted["submission"]["result"]
    )
    assert (
        result["evidence_status"]
        == "validated"
    )
    assert (
        result["readiness"]
        == "ready_for_qa"
    )
    assert (
        result["session_id"]
        == first_session["id"]
    )
    assert (
        submitted["operator"][
            "state"
        ]["status"]
        == "awaiting_qa"
    )


def test_operator_stop_closes_recorded_session(
    tmp_path,
):
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
            id="MCC-M0.5",
            title="Operator",
        )
    )

    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.5",
        "Stop fixture",
        required_evidence=[
            "session_trace",
        ],
    )
    operator_id = run["plan"]["id"]
    provider = FakeProvider()
    sessions = SessionManager(
        store,
        providers={
            "codex": provider,
        },
    )

    launched = operator.launch(
        operator_id,
        "builder",
        sessions=sessions,
    )
    session_id = launched[
        "builder_session"
    ]["id"]

    stopped = operator.stop(
        operator_id,
        "builder",
        sessions=sessions,
    )

    assert (
        stopped["builder_session"][
            "id"
        ]
        == session_id
    )
    assert (
        stopped["builder_session"][
            "status"
        ]
        == "stopped"
    )
