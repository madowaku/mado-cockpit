from __future__ import annotations

from pathlib import Path
from typing import Mapping
from uuid import uuid4

from .models import AgentSession
from .providers import AgentProvider, CodexCLIProvider
from .store import CockpitStore


class SessionManager:
    def __init__(
        self,
        store: CockpitStore,
        *,
        providers: Mapping[str, AgentProvider]
        | None = None,
    ) -> None:
        self.store = store
        self.providers = dict(
            providers
            or {
                "codex": CodexCLIProvider(),
            }
        )

    def start(
        self,
        worker_id: str,
        prompt: str,
        *,
        provider_name: str = "codex",
        model: str | None = None,
    ) -> dict[str, object]:
        worker = self.store.get_worker(worker_id)
        workspace = (
            self.store.get_workspace_for_worker(
                worker_id
            )
        )
        self._require_workspace_ready(workspace)
        self._require_workspace_available(
            str(workspace["id"])
        )

        provider = self._provider(provider_name)
        session_id = (
            f"{workspace['id']}-{provider_name}-"
            f"{uuid4().hex[:8]}"
        )
        session = AgentSession(
            id=session_id,
            worker_id=worker_id,
            workspace_id=str(workspace["id"]),
            provider=provider_name,
            model=model,
        )
        mission_id = worker.get("mission_id")
        self.store.create_session(
            session,
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
        )
        self.store.update_session(
            session_id,
            status="running",
            event_type="session.started",
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
        )

        try:
            result = provider.start(
                workspace=Path(str(workspace["path"])),
                prompt=prompt,
                model=model,
            )
        except Exception as exc:
            self._fail(
                session_id,
                mission_id=mission_id,
                message=str(exc),
            )
            raise

        trace = self.store.save_session_trace(
            session_id,
            1,
            stdout=result.stdout,
            stderr=result.stderr,
        )

        if result.exit_code != 0:
            message = (
                "Provider start failed with exit code "
                f"{result.exit_code}"
            )
            self._fail(
                session_id,
                mission_id=mission_id,
                message=message,
                exit_code=result.exit_code,
                last_trace=trace["stdout"],
            )
            raise RuntimeError(message)

        if not result.external_session_id:
            message = (
                "Provider did not report a durable "
                "session id"
            )
            self._fail(
                session_id,
                mission_id=mission_id,
                message=message,
                exit_code=result.exit_code,
                last_trace=trace["stdout"],
            )
            raise RuntimeError(message)

        return self.store.update_session(
            session_id,
            external_session_id=(
                result.external_session_id
            ),
            status="active",
            turn_count=1,
            last_exit_code=result.exit_code,
            last_message=result.last_message,
            last_trace=trace["stdout"],
            last_error=None,
            event_type="session.turn.completed",
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
        )

    def send(
        self,
        session_id: str,
        prompt: str,
    ) -> dict[str, object]:
        session = self.store.get_session(session_id)
        if session["status"] != "active":
            raise RuntimeError(
                "Session is not active: "
                f"{session_id} ({session['status']})"
            )

        workspace = self.store.get_workspace(
            str(session["workspace_id"])
        )
        self._require_workspace_ready(workspace)

        external_session_id = session.get(
            "external_session_id"
        )
        if not isinstance(
            external_session_id,
            str,
        ):
            raise RuntimeError(
                "Session has no external session id: "
                f"{session_id}"
            )

        provider = self._provider(
            str(session["provider"])
        )
        worker = self.store.get_worker(
            str(session["worker_id"])
        )
        mission_id = worker.get("mission_id")
        next_turn = int(session["turn_count"]) + 1

        self.store.update_session(
            session_id,
            status="running",
            event_type="session.turn.started",
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
        )

        try:
            result = provider.send(
                external_session_id=(
                    external_session_id
                ),
                workspace=Path(
                    str(workspace["path"])
                ),
                prompt=prompt,
                model=(
                    str(session["model"])
                    if session.get("model")
                    is not None
                    else None
                ),
            )
        except Exception as exc:
            self._fail(
                session_id,
                mission_id=mission_id,
                message=str(exc),
            )
            raise

        trace = self.store.save_session_trace(
            session_id,
            next_turn,
            stdout=result.stdout,
            stderr=result.stderr,
        )

        if result.exit_code != 0:
            message = (
                "Provider send failed with exit code "
                f"{result.exit_code}"
            )
            self._fail(
                session_id,
                mission_id=mission_id,
                message=message,
                exit_code=result.exit_code,
                last_trace=trace["stdout"],
            )
            raise RuntimeError(message)

        if not result.external_session_id:
            message = (
                "Provider resume did not report a "
                "session id; continuity cannot be "
                "verified"
            )
            self._fail(
                session_id,
                mission_id=mission_id,
                message=message,
                exit_code=result.exit_code,
                last_trace=trace["stdout"],
            )
            raise RuntimeError(message)

        if (
            result.external_session_id
            != external_session_id
        ):
            message = (
                "Provider resume changed session id "
                f"from {external_session_id} to "
                f"{result.external_session_id}"
            )
            self._fail(
                session_id,
                mission_id=mission_id,
                message=message,
                exit_code=result.exit_code,
                last_trace=trace["stdout"],
            )
            raise RuntimeError(message)

        return self.store.update_session(
            session_id,
            status="active",
            turn_count=next_turn,
            last_exit_code=result.exit_code,
            last_message=result.last_message,
            last_trace=trace["stdout"],
            last_error=None,
            event_type="session.turn.completed",
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
        )

    def status(
        self,
        session_id: str,
    ) -> dict[str, object]:
        session = self.store.get_session(session_id)
        provider = self._provider(
            str(session["provider"])
        )
        return {
            **session,
            "provider_status": provider.status(
                session
            ),
        }

    def stop(
        self,
        session_id: str,
    ) -> dict[str, object]:
        session = self.store.get_session(session_id)
        if session["status"] == "running":
            raise RuntimeError(
                "MCC-M0.2 cannot interrupt a running "
                "turn; wait for the turn to finish"
            )
        if session["status"] == "stopped":
            return session

        provider = self._provider(
            str(session["provider"])
        )
        provider.stop(session)

        worker = self.store.get_worker(
            str(session["worker_id"])
        )
        mission_id = worker.get("mission_id")
        return self.store.update_session(
            session_id,
            status="stopped",
            event_type="session.stopped",
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
        )

    def _provider(
        self,
        name: str,
    ) -> AgentProvider:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise RuntimeError(
                f"Unknown agent provider: {name}"
            ) from exc

    def _require_workspace_available(
        self,
        workspace_id: str,
    ) -> None:
        occupied = [
            session
            for session in self.store.list_sessions()
            if session["workspace_id"] == workspace_id
            and session["status"]
            in {"active", "running"}
        ]
        if occupied:
            raise RuntimeError(
                "Workspace already has an active "
                f"session: {workspace_id}"
            )

    @staticmethod
    def _require_workspace_ready(
        workspace: dict[str, object],
    ) -> None:
        if workspace["status"] != "ready":
            raise RuntimeError(
                "Workspace is not ready: "
                f"{workspace['id']} "
                f"({workspace['status']})"
            )
        path = Path(str(workspace["path"]))
        if not path.exists():
            raise RuntimeError(
                f"Workspace path is missing: {path}"
            )

    def _fail(
        self,
        session_id: str,
        *,
        mission_id: object,
        message: str,
        exit_code: int | None = None,
        last_trace: str | None = None,
    ) -> None:
        changes: dict[str, object] = {
            "status": "failed",
            "last_error": message,
        }
        if exit_code is not None:
            changes["last_exit_code"] = exit_code
        if last_trace is not None:
            changes["last_trace"] = last_trace

        self.store.update_session(
            session_id,
            event_type="session.failed",
            mission_id=(
                str(mission_id)
                if mission_id is not None
                else None
            ),
            **changes,
        )
