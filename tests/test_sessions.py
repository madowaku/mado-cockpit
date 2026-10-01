import json
import subprocess
from pathlib import Path
from typing import Sequence

import pytest

from mado_cockpit.models import Mission, Project, Worker
from mado_cockpit.providers import (
    CodexCLIProvider,
    CommandResult,
)
from mado_cockpit.sessions import SessionManager
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


def event_stream(
    thread_id: str,
    message: str,
) -> str:
    return "\n".join(
        [
            json.dumps(
                {
                    "type": "thread.started",
                    "thread_id": thread_id,
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": message,
                    },
                }
            ),
            json.dumps(
                {
                    "type": "turn.completed",
                }
            ),
        ]
    ) + "\n"


class FakeRunner:
    def __init__(
        self,
        results: list[CommandResult],
    ) -> None:
        self.results = list(results)
        self.calls: list[
            tuple[list[str], Path]
        ] = []

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
    ) -> CommandResult:
        self.calls.append(
            (list(args), cwd)
        )
        if not self.results:
            raise AssertionError(
                "No fake command result left"
            )
        return self.results.pop(0)


def setup_worker(
    tmp_path: Path,
) -> tuple[CockpitStore, object]:
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
            id="MCC-M0.2",
            title="Agent Session Adapter",
        )
    )
    store.save_worker(
        Worker(
            id="builder",
            role="builder",
            mission_id="MCC-M0.2",
            provider="codex",
        )
    )
    workspace = WorktreeManager(
        store
    ).create("builder")
    return store, workspace


def test_codex_session_starts_and_resumes_in_worktree(
    tmp_path,
):
    store, workspace = setup_worker(
        tmp_path
    )
    runner = FakeRunner(
        [
            CommandResult(
                returncode=0,
                stdout=event_stream(
                    "thread-123",
                    "initial complete",
                ),
                stderr="",
            ),
            CommandResult(
                returncode=0,
                stdout=event_stream(
                    "thread-123",
                    "follow-up complete",
                ),
                stderr="",
            ),
        ]
    )
    provider = CodexCLIProvider(
        runner=runner
    )
    manager = SessionManager(
        store,
        providers={"codex": provider},
    )

    session = manager.start(
        "builder",
        "Implement the fixture",
        model="gpt-test",
    )

    assert session["status"] == "active"
    assert (
        session["external_session_id"]
        == "thread-123"
    )
    assert session["turn_count"] == 1
    assert (
        session["last_message"]
        == "initial complete"
    )
    assert Path(
        tmp_path,
        session["last_trace"],
    ).exists()

    first_args, first_cwd = runner.calls[0]
    assert first_cwd == Path(workspace.path)
    assert first_args[:3] == [
        "codex",
        "exec",
        "--json",
    ]
    assert (
        'sandbox_mode="workspace-write"'
        in first_args
    )
    assert (
        'approval_policy="never"'
        in first_args
    )
    assert 'model="gpt-test"' in first_args
    assert (
        first_args[-1]
        == "Implement the fixture"
    )

    resumed = manager.send(
        session["id"],
        "Run the tests too",
    )

    assert resumed["status"] == "active"
    assert resumed["turn_count"] == 2
    assert (
        resumed["last_message"]
        == "follow-up complete"
    )

    second_args, second_cwd = runner.calls[1]
    assert second_cwd == Path(workspace.path)
    resume_index = second_args.index("resume")
    assert second_args[
        resume_index : resume_index + 3
    ] == [
        "resume",
        "thread-123",
        "Run the tests too",
    ]

    status = manager.status(
        session["id"]
    )
    assert (
        status["provider_status"][
            "transport"
        ]
        == "turn-based"
    )
    assert (
        status["provider_status"][
            "process_running"
        ]
        is False
    )

    stopped = manager.stop(
        session["id"]
    )
    assert stopped["status"] == "stopped"
    assert store.event_count() == 10


def test_codex_resume_rejects_thread_drift(
    tmp_path,
):
    store, _ = setup_worker(tmp_path)
    runner = FakeRunner(
        [
            CommandResult(
                returncode=0,
                stdout=event_stream(
                    "thread-good",
                    "first",
                ),
                stderr="",
            ),
            CommandResult(
                returncode=0,
                stdout=event_stream(
                    "thread-wrong",
                    "second",
                ),
                stderr="",
            ),
        ]
    )
    manager = SessionManager(
        store,
        providers={
            "codex": CodexCLIProvider(
                runner=runner
            )
        },
    )

    session = manager.start(
        "builder",
        "First turn",
    )

    with pytest.raises(
        RuntimeError,
        match="changed session id",
    ):
        manager.send(
            session["id"],
            "Second turn",
        )

    failed = store.get_session(
        session["id"]
    )
    assert failed["status"] == "failed"
    assert failed["turn_count"] == 1
    assert "thread-good" in failed["last_error"]
    assert "thread-wrong" in failed["last_error"]
    assert Path(
        tmp_path,
        failed["last_trace"],
    ).exists()


def test_codex_start_requires_reported_thread_id(
    tmp_path,
):
    store, _ = setup_worker(tmp_path)
    runner = FakeRunner(
        [
            CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "type": "turn.completed",
                    }
                )
                + "\n",
                stderr="",
            )
        ]
    )
    manager = SessionManager(
        store,
        providers={
            "codex": CodexCLIProvider(
                runner=runner
            )
        },
    )

    with pytest.raises(
        RuntimeError,
        match="durable session id",
    ):
        manager.start(
            "builder",
            "First turn",
        )

    session = store.list_sessions()[0]
    assert session["status"] == "failed"


def test_workspace_rejects_second_active_session(
    tmp_path,
):
    store, _ = setup_worker(tmp_path)
    runner = FakeRunner(
        [
            CommandResult(
                returncode=0,
                stdout=event_stream(
                    "thread-one",
                    "first",
                ),
                stderr="",
            )
        ]
    )
    manager = SessionManager(
        store,
        providers={
            "codex": CodexCLIProvider(
                runner=runner
            )
        },
    )

    manager.start(
        "builder",
        "First session",
    )

    with pytest.raises(
        RuntimeError,
        match="already has an active session",
    ):
        manager.start(
            "builder",
            "Second session",
        )

    assert len(runner.calls) == 1


def test_failed_session_can_be_replaced(
    tmp_path,
):
    store, _ = setup_worker(tmp_path)
    runner = FakeRunner(
        [
            CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "type": "turn.completed",
                    }
                )
                + "\n",
                stderr="",
            ),
            CommandResult(
                returncode=0,
                stdout=event_stream(
                    "thread-retry",
                    "recovered",
                ),
                stderr="",
            ),
        ]
    )
    manager = SessionManager(
        store,
        providers={
            "codex": CodexCLIProvider(
                runner=runner
            )
        },
    )

    with pytest.raises(RuntimeError):
        manager.start(
            "builder",
            "Broken first session",
        )

    failed = store.list_sessions()[0]
    assert failed["status"] == "failed"

    recovered = manager.start(
        "builder",
        "Retry session",
    )

    assert recovered["status"] == "active"
    assert recovered["id"] != failed["id"]
    assert (
        recovered["external_session_id"]
        == "thread-retry"
    )
