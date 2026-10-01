from __future__ import annotations

import shutil
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
        requested = str(args[0])
        executable = shutil.which(requested) or requested
        command = [executable, *list(args[1:])]

        try:
            result = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Executable not found: {requested}"
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
