from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .models import utc_now
from .store import CockpitStore


RunCommand = Callable[
    [Sequence[str], Mapping[str, str], Path],
    subprocess.CompletedProcess[str],
]


def _default_runner(
    args: Sequence[str],
    env: Mapping[str, str],
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=str(cwd),
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


def _safe_name(value: str, *, label: str) -> str:
    value = value.strip()
    if (
        not value
        or "/" in value
        or "\\" in value
        or ".." in value
    ):
        raise RuntimeError(f"Invalid {label}")
    return value


def _sha256_text(value: str) -> str:
    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


@dataclass(slots=True)
class TunnelProfilePlan:
    profile: str
    tunnel_id: str
    mcp_command: str
    init_command: list[str]
    doctor_command: list[str]
    run_command: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "tunnel_id": self.tunnel_id,
            "mcp_command": self.mcp_command,
            "init_command": self.init_command,
            "doctor_command": self.doctor_command,
            "run_command": self.run_command,
        }


class SecureTunnelManager:
    """Local wrapper for OpenAI Secure MCP Tunnel.

    Secrets are read from the process environment and are never
    persisted into Cockpit state or returned in command previews.
    """

    def __init__(
        self,
        store: CockpitStore,
        *,
        runner: RunCommand = _default_runner,
    ) -> None:
        self.store = store
        self.runner = runner
        self.base = (
            store.base
            / "control"
            / "secure-tunnel"
        )
        self.profiles_dir = self.base / "profiles"
        self.evidence_dir = self.base / "evidence"

    def plan(
        self,
        *,
        tunnel_id: str,
        profile: str = "mado-cockpit-space",
        tunnel_client: str = "tunnel-client",
    ) -> TunnelProfilePlan:
        self._require_initialized()
        profile = _safe_name(
            profile,
            label="tunnel profile",
        )
        tunnel_id = tunnel_id.strip()
        if not tunnel_id.startswith("tunnel_"):
            raise RuntimeError(
                "tunnel_id must start with tunnel_"
            )

        mcp_args = [
            sys.executable,
            "-m",
            "mado_cockpit.space_mcp",
            "--root",
            str(self.store.root.resolve()),
            "--transport",
            "stdio",
        ]
        mcp_command = (
            subprocess.list2cmdline(mcp_args)
            if os.name == "nt"
            else shlex.join(mcp_args)
        )

        return TunnelProfilePlan(
            profile=profile,
            tunnel_id=tunnel_id,
            mcp_command=mcp_command,
            init_command=[
                tunnel_client,
                "init",
                "--sample",
                "sample_mcp_stdio_local",
                "--profile",
                profile,
                "--tunnel-id",
                tunnel_id,
                "--mcp-command",
                mcp_command,
            ],
            doctor_command=[
                tunnel_client,
                "doctor",
                "--profile",
                profile,
                "--explain",
            ],
            run_command=[
                tunnel_client,
                "run",
                "--profile",
                profile,
            ],
        )

    def init_profile(
        self,
        *,
        tunnel_id: str,
        profile: str = "mado-cockpit-space",
        tunnel_client: str = "tunnel-client",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        plan = self.plan(
            tunnel_id=tunnel_id,
            profile=profile,
            tunnel_client=tunnel_client,
        )
        runtime_env = self._runtime_env(env)
        completed = self.runner(
            plan.init_command,
            runtime_env,
            self.store.root.resolve(),
        )
        result = self._record_result(
            operation="init",
            profile=plan.profile,
            tunnel_id=plan.tunnel_id,
            command=plan.init_command,
            completed=completed,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "tunnel-client init failed; inspect "
                f"{result['evidence_path']}"
            )

        profile_path = (
            self.profiles_dir
            / f"{plan.profile}.json"
        )
        self._write_json(
            profile_path,
            {
                "profile": plan.profile,
                "tunnel_id": plan.tunnel_id,
                "mcp_command": plan.mcp_command,
                "initialized_at": utc_now(),
                "last_init_evidence": (
                    result["evidence_path"]
                ),
            },
        )
        return {
            "profile": plan.profile,
            "tunnel_id": plan.tunnel_id,
            "status": "initialized",
            "evidence_path": (
                result["evidence_path"]
            ),
        }

    def doctor(
        self,
        *,
        profile: str = "mado-cockpit-space",
        tunnel_client: str = "tunnel-client",
        env: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        profile = _safe_name(
            profile,
            label="tunnel profile",
        )
        metadata = self._profile(profile)
        runtime_env = self._runtime_env(env)
        command = [
            tunnel_client,
            "doctor",
            "--profile",
            profile,
            "--explain",
        ]
        completed = self.runner(
            command,
            runtime_env,
            self.store.root.resolve(),
        )
        result = self._record_result(
            operation="doctor",
            profile=profile,
            tunnel_id=str(
                metadata["tunnel_id"]
            ),
            command=command,
            completed=completed,
        )
        return {
            "profile": profile,
            "tunnel_id": metadata["tunnel_id"],
            "healthy": completed.returncode == 0,
            "exit_code": completed.returncode,
            "evidence_path": (
                result["evidence_path"]
            ),
            "stdout_sha256": result[
                "stdout_sha256"
            ],
            "stderr_sha256": result[
                "stderr_sha256"
            ],
        }

    def run(
        self,
        *,
        profile: str = "mado-cockpit-space",
        tunnel_client: str = "tunnel-client",
        env: Mapping[str, str] | None = None,
    ) -> int:
        profile = _safe_name(
            profile,
            label="tunnel profile",
        )
        self._profile(profile)
        runtime_env = self._runtime_env(env)
        completed = subprocess.run(
            [
                tunnel_client,
                "run",
                "--profile",
                profile,
            ],
            cwd=str(self.store.root.resolve()),
            env=runtime_env,
            check=False,
        )
        return int(completed.returncode)

    def inspect_profile(
        self,
        profile: str = "mado-cockpit-space",
    ) -> dict[str, Any]:
        profile = _safe_name(
            profile,
            label="tunnel profile",
        )
        return self._profile(profile)

    def _runtime_env(
        self,
        env: Mapping[str, str] | None,
    ) -> dict[str, str]:
        runtime_env = dict(
            os.environ if env is None else env
        )
        key = runtime_env.get(
            "CONTROL_PLANE_API_KEY",
            "",
        ).strip()
        if not key:
            raise RuntimeError(
                "CONTROL_PLANE_API_KEY is required "
                "for Secure MCP Tunnel and is never "
                "persisted by MADO Cockpit"
            )
        return runtime_env

    def _profile(
        self,
        profile: str,
    ) -> dict[str, Any]:
        path = (
            self.profiles_dir
            / f"{profile}.json"
        )
        if not path.exists():
            raise RuntimeError(
                "Tunnel profile metadata not found: "
                f"{profile}"
            )
        return self._read_json(path)

    def _record_result(
        self,
        *,
        operation: str,
        profile: str,
        tunnel_id: str,
        command: Sequence[str],
        completed: subprocess.CompletedProcess[str],
    ) -> dict[str, Any]:
        timestamp = utc_now()
        token = timestamp.replace(
            ":",
            "",
        ).replace(
            "+",
            "_",
        )
        path = (
            self.evidence_dir
            / profile
            / f"{token}-{operation}.json"
        )
        payload = {
            "operation": operation,
            "profile": profile,
            "tunnel_id": tunnel_id,
            "command": list(command),
            "exit_code": int(
                completed.returncode
            ),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "stdout_sha256": _sha256_text(
                completed.stdout
            ),
            "stderr_sha256": _sha256_text(
                completed.stderr
            ),
            "recorded_at": timestamp,
        }
        self._write_json(path, payload)
        return {
            **payload,
            "evidence_path": str(
                path.resolve().relative_to(
                    self.store.root.resolve()
                )
            ),
        }

    def _require_initialized(self) -> None:
        if not self.store.project_file.exists():
            raise RuntimeError(
                "Cockpit is not initialized"
            )

    @staticmethod
    def _write_json(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            json.dumps(
                dict(payload),
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
