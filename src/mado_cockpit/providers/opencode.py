from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentProvider, CommandRunner, ProviderTurnResult, SubprocessRunner

MINIMAX_FREE_MODEL = "opencode/minimax-m3.1-flash-free"


class OpenCodeCLIProvider(AgentProvider):
    """Explicit-model OpenCode adapter. Never automatically switches to paid models."""

    name = "opencode"

    def __init__(self, *, executable: str = "opencode",
                 runner: CommandRunner | None = None) -> None:
        self.executable = executable
        self.runner = runner or SubprocessRunner()

    def start(self, *, workspace: Path, prompt: str,
              model: str | None = None) -> ProviderTurnResult:
        return self._run(workspace, prompt, model or MINIMAX_FREE_MODEL)

    def send(self, *, external_session_id: str, workspace: Path,
             prompt: str, model: str | None = None) -> ProviderTurnResult:
        if not external_session_id.startswith("ses_"):
            raise ValueError("Invalid OpenCode session ID")
        return self._run(workspace, prompt, model or MINIMAX_FREE_MODEL,
                         external_session_id)

    def _run(self, workspace: Path, prompt: str, model: str,
             session_id: str | None = None) -> ProviderTurnResult:
        if not model.startswith("opencode/") or not model.endswith("-free"):
            raise ValueError(
                "OpenCode fallback requires an explicitly free OpenCode model"
            )
        args = [self.executable, "run", "--format", "json",
                "--model", model]
        if session_id:
            args.extend(["--session", session_id])
        args.append(prompt)
        result = self.runner.run(args, cwd=workspace)
        events: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
        ids = {
            value for event in events
            for value in (event.get("sessionID"),
                          (event.get("properties") or {}).get("sessionID")
                          if isinstance(event.get("properties"), dict) else None)
            if isinstance(value, str) and value.startswith("ses_")
        }
        # A conflicting ID is not safe to persist or resume.
        if len(ids) > 1:
            raise RuntimeError("OpenCode reported conflicting session IDs")
        observed_id = next(iter(ids), None)
        messages = []
        for event in events:
            if event.get("type") != "text":
                continue
            part = event.get("part")
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                messages.append(part["text"])
        return ProviderTurnResult(
            external_session_id=observed_id,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            last_message="".join(messages) or None,
        )

    def status(self, session: dict[str, object]) -> dict[str, object]:
        return {"provider": self.name, "transport": "turn-based",
                "external_session_id": session.get("external_session_id"),
                "process_running": None if session.get("status") == "running" else False}

    def stop(self, session: dict[str, object]) -> dict[str, object]:
        return {"provider": self.name, "transport": "turn-based",
                "external_session_id": session.get("external_session_id"),
                "process_running": False, "stopped": True}
