from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import (
    AgentProvider,
    CommandRunner,
    ProviderTurnResult,
    SubprocessRunner,
)


class CodexCLIProvider(AgentProvider):
    name = "codex"

    def __init__(
        self,
        *,
        executable: str = "codex",
        runner: CommandRunner | None = None,
    ) -> None:
        self.executable = executable
        self.runner = runner or SubprocessRunner()

    def start(
        self,
        *,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        args = self._base_args(model=model)
        args.append(prompt)
        return self._run(args, workspace=workspace)

    def send(
        self,
        *,
        external_session_id: str,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        args = self._base_args(model=model)
        args.extend(
            [
                "resume",
                external_session_id,
                prompt,
            ]
        )
        return self._run(args, workspace=workspace)

    def status(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        process_running: bool | None = False
        if session.get("status") == "running":
            process_running = None

        return {
            "provider": self.name,
            "transport": "turn-based",
            "external_session_id": session.get(
                "external_session_id"
            ),
            "process_running": process_running,
            "note": (
                "MCC-M0.2 records turn state but does not "
                "hold a persistent Codex process between "
                "turns"
            ),
        }

    def stop(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        return {
            "provider": self.name,
            "transport": "turn-based",
            "external_session_id": session.get(
                "external_session_id"
            ),
            "process_running": False,
            "stopped": True,
        }

    def _base_args(
        self,
        *,
        model: str | None,
    ) -> list[str]:
        args = [
            self.executable,
            "exec",
            "--json",
            "-c",
            'sandbox_mode="workspace-write"',
            "-c",
            'approval_policy="never"',
        ]
        if model:
            args.extend(
                [
                    "-c",
                    f"model={json.dumps(model)}",
                ]
            )
        return args

    def _run(
        self,
        args: list[str],
        *,
        workspace: Path,
    ) -> ProviderTurnResult:
        result = self.runner.run(
            args,
            cwd=workspace,
        )
        parsed = self._parse_jsonl(result.stdout)

        thread_id = self._thread_id(parsed)
        last_message = self._last_agent_message(
            parsed
        )

        return ProviderTurnResult(
            external_session_id=thread_id,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            last_message=last_message,
        )

    @staticmethod
    def _parse_jsonl(
        payload: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in payload.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
        return events

    @staticmethod
    def _thread_id(
        events: list[dict[str, Any]],
    ) -> str | None:
        for event in events:
            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id")
                if isinstance(thread_id, str):
                    return thread_id
        return None

    @staticmethod
    def _last_agent_message(
        events: list[dict[str, Any]],
    ) -> str | None:
        result: str | None = None
        for event in events:
            if event.get("type") != "item.completed":
                continue
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            if item.get("type") != "agent_message":
                continue
            text = item.get("text")
            if isinstance(text, str):
                result = text
        return result
