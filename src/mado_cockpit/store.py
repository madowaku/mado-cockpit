from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import (
    AgentSession,
    Event,
    Mission,
    Project,
    Worker,
    Workspace,
    utc_now,
)


class CockpitStore:
    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root)
        self.base = self.root / ".mado" / "cockpit"
        self.missions_dir = self.base / "missions"
        self.workers_dir = self.base / "workers"
        self.workspaces_dir = self.base / "workspaces"
        self.sessions_dir = self.base / "sessions"
        self.events_file = self.base / "events.jsonl"
        self.project_file = self.base / "project.json"

    def init(self, project: Project) -> None:
        self.missions_dir.mkdir(parents=True, exist_ok=True)
        self.workers_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.project_file, project.to_dict())
        self.append_event(
            Event(
                type="project.opened",
                subject={"project_id": project.id},
            )
        )

    def save_mission(self, mission: Mission) -> None:
        self._require_initialized()
        self._write_json(
            self.missions_dir / f"{mission.id}.json",
            mission.to_dict(),
        )
        self.append_event(
            Event(
                type="mission.created",
                mission_id=mission.id,
                subject={
                    "mission_id": mission.id,
                    "title": mission.title,
                },
            )
        )

    def save_worker(self, worker: Worker) -> None:
        self._require_initialized()
        self._write_json(
            self.workers_dir / f"{worker.id}.json",
            worker.to_dict(),
        )
        self.append_event(
            Event(
                type="worker.created",
                mission_id=worker.mission_id,
                subject={
                    "worker_id": worker.id,
                    "role": worker.role,
                },
            )
        )

    def get_worker(self, worker_id: str) -> dict[str, Any]:
        self._require_initialized()
        path = self.workers_dir / f"{worker_id}.json"
        if not path.exists():
            raise RuntimeError(f"Worker not found: {worker_id}")
        return self._read_json(path)

    def save_workspace(self, workspace: Workspace) -> None:
        self._require_initialized()
        self._write_json(
            self.workspaces_dir / f"{workspace.id}.json",
            workspace.to_dict(),
        )
        self.append_event(
            Event(
                type="workspace.created",
                mission_id=workspace.mission_id,
                subject={
                    "workspace_id": workspace.id,
                    "worker_id": workspace.worker_id,
                    "branch": workspace.branch,
                    "path": workspace.path,
                },
            )
        )

    def update_workspace_status(
        self,
        workspace_id: str,
        status: str,
        *,
        event_type: str | None = None,
    ) -> dict[str, Any]:
        self._require_initialized()
        path = self.workspaces_dir / f"{workspace_id}.json"
        if not path.exists():
            raise RuntimeError(
                f"Workspace not found: {workspace_id}"
            )
        payload = self._read_json(path)
        payload["status"] = status
        self._write_json(path, payload)
        if event_type:
            self.append_event(
                Event(
                    type=event_type,
                    mission_id=payload.get("mission_id"),
                    subject={
                        "workspace_id": workspace_id,
                        "worker_id": payload["worker_id"],
                        "branch": payload["branch"],
                    },
                )
            )
        return payload

    def get_workspace(
        self,
        workspace_id: str,
    ) -> dict[str, Any]:
        self._require_initialized()
        path = self.workspaces_dir / f"{workspace_id}.json"
        if not path.exists():
            raise RuntimeError(
                f"Workspace not found: {workspace_id}"
            )
        return self._read_json(path)

    def list_workspaces(self) -> list[dict[str, Any]]:
        self._require_initialized()
        return [
            self._read_json(path)
            for path in sorted(
                self.workspaces_dir.glob("*.json")
            )
        ]

    def get_workspace_for_worker(
        self,
        worker_id: str,
    ) -> dict[str, Any]:
        active = [
            workspace
            for workspace in self.list_workspaces()
            if workspace["worker_id"] == worker_id
            and workspace["status"] != "removed"
        ]
        if not active:
            raise RuntimeError(
                "No active workspace for worker: "
                f"{worker_id}"
            )
        if len(active) > 1:
            raise RuntimeError(
                "Multiple active workspaces for worker: "
                f"{worker_id}"
            )
        return active[0]

    def create_session(
        self,
        session: AgentSession,
        *,
        mission_id: str | None = None,
    ) -> None:
        self._require_initialized()
        session_dir = self.sessions_dir / session.id
        session_file = session_dir / "session.json"
        if session_file.exists():
            raise RuntimeError(
                f"Session already exists: {session.id}"
            )
        session_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(
            session_file,
            session.to_dict(),
        )
        self.append_event(
            Event(
                type="session.created",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "session_id": session.id,
                    "worker_id": session.worker_id,
                    "workspace_id": session.workspace_id,
                    "provider": session.provider,
                },
            )
        )

    def get_session(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        self._require_initialized()
        path = (
            self.sessions_dir
            / session_id
            / "session.json"
        )
        if not path.exists():
            raise RuntimeError(
                f"Session not found: {session_id}"
            )
        return self._read_json(path)

    def list_sessions(self) -> list[dict[str, Any]]:
        self._require_initialized()
        return [
            self._read_json(path)
            for path in sorted(
                self.sessions_dir.glob("*/session.json")
            )
        ]

    def update_session(
        self,
        session_id: str,
        *,
        event_type: str | None = None,
        mission_id: str | None = None,
        **changes: Any,
    ) -> dict[str, Any]:
        payload = self.get_session(session_id)
        payload.update(changes)
        payload["updated_at"] = utc_now()
        path = (
            self.sessions_dir
            / session_id
            / "session.json"
        )
        self._write_json(path, payload)

        if event_type:
            self.append_event(
                Event(
                    type=event_type,
                    mission_id=mission_id,
                    actor="cockpit",
                    subject={
                        "session_id": session_id,
                        "worker_id": payload["worker_id"],
                        "workspace_id": payload["workspace_id"],
                        "provider": payload["provider"],
                        "status": payload["status"],
                        "turn_count": payload["turn_count"],
                    },
                )
            )
        return payload

    def save_session_trace(
        self,
        session_id: str,
        turn_number: int,
        *,
        stdout: str,
        stderr: str,
    ) -> dict[str, str | None]:
        self.get_session(session_id)
        traces = (
            self.sessions_dir
            / session_id
            / "traces"
        )
        traces.mkdir(parents=True, exist_ok=True)

        trace_path = traces / f"turn-{turn_number:04d}.jsonl"
        trace_path.write_text(
            stdout,
            encoding="utf-8",
        )
        result: dict[str, str | None] = {
            "stdout": self._relative(trace_path),
            "stderr": None,
        }

        if stderr:
            stderr_path = (
                traces
                / f"turn-{turn_number:04d}.stderr.txt"
            )
            stderr_path.write_text(
                stderr,
                encoding="utf-8",
            )
            result["stderr"] = self._relative(
                stderr_path
            )
        return result

    def snapshot(self) -> dict[str, Any]:
        self._require_initialized()
        project = self._read_json(self.project_file)
        missions = [
            self._read_json(path)
            for path in sorted(
                self.missions_dir.glob("*.json")
            )
        ]
        workers = [
            self._read_json(path)
            for path in sorted(
                self.workers_dir.glob("*.json")
            )
        ]
        return {
            "project": project,
            "missions": missions,
            "workers": workers,
            "workspaces": self.list_workspaces(),
            "sessions": self.list_sessions(),
            "event_count": self.event_count(),
        }

    def append_event(self, event: Event) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        with self.events_file.open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                json.dumps(
                    event.to_dict(),
                    ensure_ascii=False,
                )
                + "\n"
            )

    def event_count(self) -> int:
        if not self.events_file.exists():
            return 0
        return sum(
            1
            for line in self.events_file.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        )

    def _relative(self, path: Path) -> str:
        return str(
            path.resolve().relative_to(
                self.root.resolve()
            )
        )

    def _require_initialized(self) -> None:
        if not self.project_file.exists():
            raise RuntimeError(
                "Cockpit is not initialized. "
                "Run: mado-cockpit init"
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
