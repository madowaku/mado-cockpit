import subprocess
from pathlib import Path

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
    git(
        path,
        "commit",
        "-m",
        "fixture",
    )


def test_two_workers_get_isolated_worktrees(
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
            id="MCC-M0.1",
            title="Worktree Worker",
        )
    )
    store.save_worker(
        Worker(
            id="builder",
            role="builder",
            mission_id="MCC-M0.1",
        )
    )
    store.save_worker(
        Worker(
            id="qa",
            role="qa",
            mission_id="MCC-M0.1",
        )
    )

    manager = WorktreeManager(store)
    builder = manager.create("builder")
    qa = manager.create("qa")

    assert builder.path != qa.path
    assert builder.branch != qa.branch
    assert Path(builder.path).exists()
    assert Path(qa.path).exists()

    Path(
        builder.path,
        "builder.txt",
    ).write_text(
        "builder only\n",
        encoding="utf-8",
    )
    Path(
        qa.path,
        "qa.txt",
    ).write_text(
        "qa only\n",
        encoding="utf-8",
    )

    assert Path(
        builder.path,
        "builder.txt",
    ).exists()
    assert not Path(
        qa.path,
        "builder.txt",
    ).exists()

    assert Path(
        qa.path,
        "qa.txt",
    ).exists()
    assert not Path(
        builder.path,
        "qa.txt",
    ).exists()

    builder_status = manager.status(
        builder.id
    )
    qa_status = manager.status(
        qa.id
    )

    assert (
        "builder.txt"
        in builder_status["git_status"]
    )
    assert (
        "qa.txt"
        in qa_status["git_status"]
    )

    branches = git(
        tmp_path,
        "branch",
        "--format=%(refname:short)",
    ).splitlines()

    assert builder.branch in branches
    assert qa.branch in branches

    manager.remove(
        builder.id,
        force=True,
        delete_branch=True,
    )
    manager.remove(
        qa.id,
        force=True,
        delete_branch=True,
    )

    assert not Path(builder.path).exists()
    assert not Path(qa.path).exists()

    assert (
        store.get_workspace(builder.id)["status"]
        == "removed"
    )
    assert (
        store.get_workspace(qa.id)["status"]
        == "removed"
    )

    assert store.event_count() == 8
