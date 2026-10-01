from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Event, Mission, Project, Worker, Workspace


class CockpitStore:
    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root)
        self.base = self.root / ".mado" / "cockpit"
        self.missions_dir = self.base / "missions"
        self.workers_dir = self.base / "workers"
        self.workspaces_dir = self.base / "workspaces"
        self.events_file = self.base / "events.jsonl"
        self.project_file = self.base / "project.json"

    def init(self, project: Project) -> None:
        self.missions_dir.mkdir(parents=True, exist_ok=True)
        self.workers_dir.mkdir(parents=True, exist_ok=True)
        self.workspaces_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.project_file, project.to_dict())
        self.append_event(Event(type="project.opened", subject={"project_id": project.id}))

    def save_mission(self, mission: Mission) -> None:
        self._require_initialized()
        self._write_json(self.missions_dir / f"{mission.id}.json", mission.to_dict())
        self.append_event(
            Event(
                type="mission.created",
                mission_id=mission.id,
                subject={"mission_id": mission.id, "title": mission.title},
            )
        )

    def save_worker(self, worker: Worker) -> None:
        self._require_initialized()
        self._write_json(self.workers_dir / f"{worker.id}.json", worker.to_dict())
        self.append_event(
            Event(
                type="worker.created",
                mission_id=worker.mission_id,
                subject={"worker_id": worker.id, "role": worker.role},
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
            raise RuntimeError(f"Workspace not found: {workspace_id}")
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

    def get_workspace(self, workspace_id: str) -> dict[str, Any]:
        self._require_initialized()
        path = self.workspaces_dir / f"{workspace_id}.json"
        if not path.exists():
            raise RuntimeError(f"Workspace not found: {workspace_id}")
        return self._read_json(path)

    def list_workspaces(self) -> list[dict[str, Any]]:
        self._require_initialized()
        return [
            self._read_json(path)
            for path in sorted(self.workspaces_dir.glob("*.json"))
        ]

    def snapshot(self) -> dict[str, Any]:
        self._require_initialized()
        project = self._read_json(self.project_file)
        missions = [
            self._read_json(path)
            for path in sorted(self.missions_dir.glob("*.json"))
        ]
        workers = [
            self._read_json(path)
            for path in sorted(self.workers_dir.glob("*.json"))
        ]
        return {
            "project": project,
            "missions": missions,
            "workers": workers,
            "workspaces": self.list_workspaces(),
            "event_count": self.event_count(),
        }

    def append_event(self, event: Event) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        with self.events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def event_count(self) -> int:
        if not self.events_file.exists():
            return 0
        return sum(
            1
            for line in self.events_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    def _require_initialized(self) -> None:
        if not self.project_file.exists():
            raise RuntimeError(
                "Cockpit is not initialized. Run: mado-cockpit init"
            )

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))
