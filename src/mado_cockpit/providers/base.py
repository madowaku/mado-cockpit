from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence


@dataclass(slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class ProviderTurnResult:
    external_session_id: str | None
    exit_code: int
    stdout: str
    stderr: str
    last_message: str | None


class CommandRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
    ) -> CommandResult:
        ...


class SubprocessRunner:
    def run(
        self,
        args: Sequence[str],
        *,
        cwd: Path,
    ) -> CommandResult:
        try:
            result = subprocess.run(
                list(args),
                cwd=str(cwd),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Executable not found: {args[0]}"
            ) from exc

        return CommandResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )


class AgentProvider(Protocol):
    name: str

    def start(
        self,
        *,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        ...

    def send(
        self,
        *,
        external_session_id: str,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        ...

    def status(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        ...

    def stop(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        ...
