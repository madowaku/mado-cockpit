from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .models import (
    EvidenceBundle,
    EvidenceItem,
    Event,
    ResultContract,
    TaskContract,
    utc_now,
)
from .store import CockpitStore


_ALLOWED_RESULT_STATUS = {
    "completed",
    "blocked",
    "failed",
}


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    value = value.strip("-._").lower()
    return value or "evidence"


class EvidenceManager:
    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.tasks_dir = store.base / "tasks"
        self.results_dir = store.base / "results"
        self.evidence_dir = store.base / "evidence"

    def create_task(
        self,
        task_id: str,
        worker_id: str,
        objective: str,
        *,
        required_evidence: Iterable[str] = (),
        constraints: Iterable[str] = (),
        deliverables: Iterable[str] = (),
        done_when: Iterable[str] = (),
    ) -> dict[str, Any]:
        worker = self.store.get_worker(worker_id)
        workspace = self.store.get_workspace_for_worker(worker_id)

        if workspace["status"] != "ready":
            raise RuntimeError(
                f"Workspace is not ready: {workspace['id']}"
            )

        path = self.tasks_dir / f"{task_id}.json"
        if path.exists():
            raise RuntimeError(f"Task already exists: {task_id}")

        task = TaskContract(
            id=task_id,
            worker_id=worker_id,
            workspace_id=str(workspace["id"]),
            objective=objective,
            required_evidence=_unique(required_evidence),
            constraints=_unique(constraints),
            deliverables=_unique(deliverables),
            done_when=_unique(done_when),
        )
        self._write_json(path, task.to_dict())
        self.store.append_event(
            Event(
                type="task.assigned",
                mission_id=self._mission_id(worker),
                actor="cockpit",
                subject={
                    "task_id": task.id,
                    "worker_id": task.worker_id,
                    "workspace_id": task.workspace_id,
                    "required_evidence": task.required_evidence,
                },
            )
        )
        return task.to_dict()

    def get_task(self, task_id: str) -> dict[str, Any]:
        path = self.tasks_dir / f"{task_id}.json"
        if not path.exists():
            raise RuntimeError(f"Task not found: {task_id}")
        return self._read_json(path)

    def list_tasks(self) -> list[dict[str, Any]]:
        if not self.tasks_dir.exists():
            return []
        return [
            self._read_json(path)
            for path in sorted(self.tasks_dir.glob("*.json"))
        ]

    def submit_result(
        self,
        task_id: str,
        *,
        status: str,
        summary: str,
        evidence_files: Iterable[tuple[str, str]] = (),
        changes: Iterable[str] = (),
        risks: Iterable[str] = (),
        session_id: str | None = None,
    ) -> dict[str, Any]:
        if status not in _ALLOWED_RESULT_STATUS:
            allowed = ", ".join(sorted(_ALLOWED_RESULT_STATUS))
            raise RuntimeError(
                f"Unsupported result status: {status}. "
                f"Expected one of: {allowed}"
            )

        task = self.get_task(task_id)
        worker = self.store.get_worker(str(task["worker_id"]))
        workspace = self.store.get_workspace(
            str(task["workspace_id"])
        )
        self._require_workspace_ready(workspace)

        bundle_id = f"evb_{uuid4().hex[:12]}"
        result_id = f"res_{uuid4().hex[:12]}"
        bundle_dir = (
            self.evidence_dir
            / task_id
            / bundle_id
        )
        files_dir = bundle_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=False)

        items: list[EvidenceItem] = []

        git_item = self._capture_workspace_changes(
            workspace=workspace,
            files_dir=files_dir,
        )
        if git_item is not None:
            items.append(git_item)

        for index, (kind, raw_path) in enumerate(
            evidence_files,
            start=1,
        ):
            items.append(
                self._capture_workspace_file(
                    workspace=workspace,
                    kind=kind,
                    raw_path=raw_path,
                    files_dir=files_dir,
                    index=index,
                )
            )

        if session_id:
            items.append(
                self._capture_session_trace(
                    session_id=session_id,
                    task=task,
                    files_dir=files_dir,
                )
            )

        present = {item.kind for item in items}
        required = list(task["required_evidence"])
        missing = [
            kind for kind in required if kind not in present
        ]
        evidence_status = (
            "validated"
            if not missing
            else "incomplete"
        )

        if status == "completed" and evidence_status == "validated":
            readiness = "ready_for_qa"
        elif status == "completed":
            readiness = "incomplete"
        else:
            readiness = "not_completed"

        bundle = EvidenceBundle(
            id=bundle_id,
            task_id=task_id,
            worker_id=str(task["worker_id"]),
            workspace_id=str(task["workspace_id"]),
            status=evidence_status,
            required_evidence=required,
            missing_evidence=missing,
            items=items,
        )
        result = ResultContract(
            id=result_id,
            task_id=task_id,
            worker_id=str(task["worker_id"]),
            workspace_id=str(task["workspace_id"]),
            status=status,
            summary=summary,
            evidence_bundle_id=bundle_id,
            evidence_status=evidence_status,
            readiness=readiness,
            missing_evidence=missing,
            changes=_unique(changes),
            risks=_unique(risks),
            session_id=session_id,
        )

        self._write_json(
            bundle_dir / "manifest.json",
            bundle.to_dict(),
        )
        self._write_json(
            bundle_dir / "task.json",
            task,
        )
        self._write_json(
            bundle_dir / "result.json",
            result.to_dict(),
        )

        result_path = (
            self.results_dir
            / task_id
            / f"{result_id}.json"
        )
        self._write_json(
            result_path,
            result.to_dict(),
        )

        task["status"] = (
            "evidence_validated"
            if evidence_status == "validated"
            else "evidence_incomplete"
        )
        task["updated_at"] = utc_now()
        self._write_json(
            self.tasks_dir / f"{task_id}.json",
            task,
        )

        mission_id = self._mission_id(worker)
        self.store.append_event(
            Event(
                type="result.submitted",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "result_id": result.id,
                    "task_id": task_id,
                    "worker_id": result.worker_id,
                    "status": result.status,
                    "readiness": result.readiness,
                },
            )
        )
        self.store.append_event(
            Event(
                type="evidence.created",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "bundle_id": bundle.id,
                    "task_id": task_id,
                    "item_count": len(items),
                    "status": bundle.status,
                },
            )
        )
        self.store.append_event(
            Event(
                type=(
                    "evidence.validated"
                    if evidence_status == "validated"
                    else "evidence.incomplete"
                ),
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "bundle_id": bundle.id,
                    "task_id": task_id,
                    "missing_evidence": missing,
                },
            )
        )

        return {
            "result": result.to_dict(),
            "bundle": bundle.to_dict(),
        }

    def list_results(
        self,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.results_dir.exists():
            return []

        pattern = (
            f"{task_id}/*.json"
            if task_id
            else "*/*.json"
        )
        return [
            self._read_json(path)
            for path in sorted(
                self.results_dir.glob(pattern)
            )
        ]

    def list_bundles(
        self,
        task_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.evidence_dir.exists():
            return []

        pattern = (
            f"{task_id}/*/manifest.json"
            if task_id
            else "*/*/manifest.json"
        )
        return [
            self._read_json(path)
            for path in sorted(
                self.evidence_dir.glob(pattern)
            )
        ]

    def inspect_bundle(
        self,
        bundle_id: str,
    ) -> dict[str, Any]:
        if not self.evidence_dir.exists():
            raise RuntimeError(
                f"Evidence bundle not found: {bundle_id}"
            )

        matches = list(
            self.evidence_dir.glob(
                f"*/{bundle_id}/manifest.json"
            )
        )
        if len(matches) != 1:
            raise RuntimeError(
                f"Evidence bundle not found: {bundle_id}"
            )
        return self._read_json(matches[0])

    def summary(self) -> dict[str, int]:
        return {
            "task_count": len(self.list_tasks()),
            "result_count": len(self.list_results()),
            "evidence_bundle_count": len(
                self.list_bundles()
            ),
        }

    def _capture_workspace_changes(
        self,
        *,
        workspace: dict[str, Any],
        files_dir: Path,
    ) -> EvidenceItem | None:
        cwd = Path(str(workspace["path"]))
        status = self._git(
            cwd,
            "status",
            "--porcelain=v1",
        )
        diff = self._git(
            cwd,
            "diff",
            "--no-ext-diff",
            "HEAD",
            "--",
        )

        if not status.strip() and not diff.strip():
            return None

        path = files_dir / "workspace-changes.txt"
        payload = (
            "# git status --porcelain=v1\n"
            f"{status.rstrip()}\n\n"
            "# git diff --no-ext-diff HEAD --\n"
            f"{diff.rstrip()}\n"
        )
        path.write_text(payload, encoding="utf-8")
        return self._item(
            kind="git_diff",
            path=path,
            source="workspace_snapshot",
            description=(
                "Git status and tracked diff captured "
                "from the assigned worktree"
            ),
        )

    def _capture_workspace_file(
        self,
        *,
        workspace: dict[str, Any],
        kind: str,
        raw_path: str,
        files_dir: Path,
        index: int,
    ) -> EvidenceItem:
        if not kind.strip():
            raise RuntimeError(
                "Evidence kind must not be empty"
            )

        workspace_root = Path(
            str(workspace["path"])
        ).resolve()
        source = Path(raw_path)
        if not source.is_absolute():
            source = workspace_root / source
        source = source.resolve()

        try:
            source.relative_to(workspace_root)
        except ValueError as exc:
            raise RuntimeError(
                "Evidence files must live inside "
                "the assigned workspace"
            ) from exc

        if not source.is_file():
            raise RuntimeError(
                f"Evidence file not found: {source}"
            )

        target = (
            files_dir
            / (
                f"{index:02d}-{_safe_name(kind)}-"
                f"{source.name}"
            )
        )
        shutil.copy2(source, target)
        return self._item(
            kind=kind,
            path=target,
            source="workspace_file",
            description=str(
                source.relative_to(workspace_root)
            ),
        )

    def _capture_session_trace(
        self,
        *,
        session_id: str,
        task: dict[str, Any],
        files_dir: Path,
    ) -> EvidenceItem:
        session = self.store.get_session(session_id)

        if (
            session["worker_id"] != task["worker_id"]
            or session["workspace_id"]
            != task["workspace_id"]
        ):
            raise RuntimeError(
                "Session does not belong to the "
                "task worker/workspace"
            )

        raw_trace = session.get("last_trace")
        if not isinstance(raw_trace, str):
            raise RuntimeError(
                "Session has no completed trace to capture"
            )

        trace = (self.store.root / raw_trace).resolve()
        if not trace.is_file():
            raise RuntimeError(
                f"Session trace not found: {trace}"
            )

        target = files_dir / "session-trace.jsonl"
        shutil.copy2(trace, target)
        return self._item(
            kind="session_trace",
            path=target,
            source="session_trace",
            description=session_id,
        )

    def _item(
        self,
        *,
        kind: str,
        path: Path,
        source: str,
        description: str | None,
    ) -> EvidenceItem:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(
                lambda: handle.read(1024 * 1024),
                b"",
            ):
                size += len(chunk)
                digest.update(chunk)

        return EvidenceItem(
            id=f"evi_{uuid4().hex[:12]}",
            kind=kind,
            path=self._relative(path),
            sha256=digest.hexdigest(),
            size_bytes=size,
            source=source,
            description=description,
        )

    def _require_workspace_ready(
        self,
        workspace: dict[str, Any],
    ) -> None:
        if workspace["status"] != "ready":
            raise RuntimeError(
                "Workspace is not ready: "
                f"{workspace['id']} "
                f"({workspace['status']})"
            )
        if not Path(
            str(workspace["path"])
        ).exists():
            raise RuntimeError(
                "Workspace path is missing: "
                f"{workspace['path']}"
            )

    @staticmethod
    def _git(
        cwd: Path,
        *args: str,
    ) -> str:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
            )
            raise RuntimeError(
                f"git {' '.join(args)} failed: {detail}"
            )
        return result.stdout

    @staticmethod
    def _mission_id(
        worker: dict[str, Any],
    ) -> str | None:
        value = worker.get("mission_id")
        return str(value) if value is not None else None

    def _relative(self, path: Path) -> str:
        return str(
            path.resolve().relative_to(
                self.store.root.resolve()
            )
        )

    @staticmethod
    def _write_json(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
