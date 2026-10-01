from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import Workspace
from .store import CockpitStore


def _slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = value.strip("-._").lower()
    return value or "worker"


@dataclass(slots=True)
class GitResult:
    stdout: str
    stderr: str


class WorktreeManager:
    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.repo_root = store.root.resolve()

    def create(
        self,
        worker_id: str,
        *,
        base_ref: str = "HEAD",
    ) -> Workspace:
        worker = self.store.get_worker(worker_id)
        self._assert_git_repo()

        mission_part = _slug(worker.get("mission_id") or "mission")
        worker_part = _slug(worker_id)
        workspace_id = f"{mission_part}-{worker_part}"
        branch = f"cockpit/{workspace_id}"
        path = (
            self.repo_root
            / ".mado"
            / "worktrees"
            / workspace_id
        )

        if path.exists():
            raise RuntimeError(
                f"Workspace path already exists: {path}"
            )
        if self._branch_exists(branch):
            raise RuntimeError(
                f"Workspace branch already exists: {branch}"
            )

        path.parent.mkdir(parents=True, exist_ok=True)
        self._git(
            "worktree",
            "add",
            "-b",
            branch,
            str(path),
            base_ref,
        )

        workspace = Workspace(
            id=workspace_id,
            worker_id=worker_id,
            mission_id=worker.get("mission_id"),
            repo_root=str(self.repo_root),
            path=str(path),
            branch=branch,
            base_ref=base_ref,
        )
        self.store.save_workspace(workspace)
        return workspace

    def status(self, workspace_id: str) -> dict[str, object]:
        workspace = self.store.get_workspace(workspace_id)
        path = Path(workspace["path"])
        exists = path.exists()
        porcelain = ""
        if exists:
            porcelain = self._git(
                "-C",
                str(path),
                "status",
                "--porcelain",
                "--branch",
            ).stdout.strip()
        return {
            **workspace,
            "exists": exists,
            "git_status": porcelain,
        }

    def remove(
        self,
        workspace_id: str,
        *,
        delete_branch: bool = False,
        force: bool = False,
    ) -> dict[str, object]:
        workspace = self.store.get_workspace(workspace_id)
        path = Path(workspace["path"])

        if path.exists():
            args = ["worktree", "remove"]
            if force:
                args.append("--force")
            args.append(str(path))
            self._git(*args)

        self._git("worktree", "prune")

        if (
            delete_branch
            and self._branch_exists(workspace["branch"])
        ):
            self._git(
                "branch",
                "-D" if force else "-d",
                workspace["branch"],
            )

        payload = self.store.update_workspace_status(
            workspace_id,
            "removed",
            event_type="workspace.removed",
        )
        return {
            **payload,
            "exists": path.exists(),
        }

    def _assert_git_repo(self) -> None:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_root),
                "rev-parse",
                "--show-toplevel",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Not a Git repository: {self.repo_root}"
            )

        actual = Path(result.stdout.strip()).resolve()
        if actual != self.repo_root:
            raise RuntimeError(
                "Cockpit root must be the Git repository root: "
                f"{actual}"
            )

    def _branch_exists(self, branch: str) -> bool:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.repo_root),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{branch}",
            ]
        )
        return result.returncode == 0

    def _git(self, *args: str) -> GitResult:
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(
                f"git {' '.join(args)} failed: {detail}"
            )
        return GitResult(
            stdout=result.stdout,
            stderr=result.stderr,
        )
