from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .capabilities import CapabilityManager
from .models import CapabilityDescriptor, Event


_AGENT_REACH_MANAGED_BY = "mado-cockpit.agent-reach"
_ALLOWED_STATUSES = {"ok", "warn", "off", "error"}
_SAFE_CHANNEL = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_URL_CREDENTIALS = re.compile(r"(https?://)([^/@\s]+)@", re.IGNORECASE)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(access_token|api_key|token|password|cookie|authorization)"
    r"=([^&\s]+)"
)
_BEARER = re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]+")


def _redact(value: str, *, limit: int = 2000) -> str:
    value = _URL_CREDENTIALS.sub(r"\1***@", value)
    value = _SECRET_ASSIGNMENT.sub(r"\1=***", value)
    value = _BEARER.sub(r"\1 ***", value)
    if len(value) > limit:
        return value[:limit] + "...[truncated]"
    return value


@dataclass(frozen=True, slots=True)
class AgentReachChannelHealth:
    channel: str
    status: str
    name: str
    message: str
    tier: int
    backends: tuple[str, ...]
    active_backend: str | None

    @property
    def routable(self) -> bool:
        return self.status == "ok" and bool(self.active_backend)

    @property
    def availability(self) -> str:
        if self.routable:
            return "available"
        if self.status == "error":
            return "unknown"
        return "unavailable"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["backends"] = list(self.backends)
        payload["routable"] = self.routable
        payload["availability"] = self.availability
        return payload


@dataclass(frozen=True, slots=True)
class AgentReachDoctorSnapshot:
    command: tuple[str, ...]
    channels: dict[str, AgentReachChannelHealth]

    def to_dict(self) -> dict[str, Any]:
        statuses = {
            status: sum(
                1
                for health in self.channels.values()
                if health.status == status
            )
            for status in sorted(_ALLOWED_STATUSES)
        }
        return {
            "provider": "agent-reach",
            "command": list(self.command),
            "summary": {
                "total": len(self.channels),
                "routable": sum(
                    1
                    for health in self.channels.values()
                    if health.routable
                ),
                "statuses": statuses,
            },
            "channels": {
                channel: health.to_dict()
                for channel, health in sorted(self.channels.items())
            },
        }


Runner = Callable[..., subprocess.CompletedProcess[str]]


class AgentReachDoctorClient:
    """Read-only bridge to agent-reach doctor --json."""

    def __init__(
        self,
        command: Sequence[str] | str = "agent-reach",
        *,
        timeout: float = 20.0,
        cwd: Path | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        if isinstance(command, str):
            self.command = [command]
        else:
            self.command = [str(item) for item in command]
        if not self.command or not self.command[0].strip():
            raise RuntimeError("Agent Reach command must not be empty")
        if timeout <= 0:
            raise RuntimeError("Agent Reach timeout must be greater than zero")
        self.timeout = timeout
        self.cwd = cwd
        self.runner = runner

    def doctor(self) -> AgentReachDoctorSnapshot:
        argv = [*self.command, "doctor", "--json"]
        env = os.environ.copy()
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("NO_COLOR", "1")

        try:
            result = self.runner(
                argv,
                cwd=str(self.cwd) if self.cwd else None,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Agent Reach executable not found: {self.command[0]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Agent Reach doctor timed out after {self.timeout:g}s"
            ) from exc

        if result.returncode != 0:
            detail = _redact(
                (
                    result.stderr
                    or result.stdout
                    or "no diagnostic output"
                ).strip()
            )
            raise RuntimeError(
                "Agent Reach doctor failed with exit code "
                f"{result.returncode}: {detail}"
            )

        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Agent Reach doctor returned invalid JSON"
            ) from exc

        channels = parse_doctor_payload(raw)
        return AgentReachDoctorSnapshot(
            command=tuple(argv),
            channels=channels,
        )


def parse_doctor_payload(
    raw: object,
) -> dict[str, AgentReachChannelHealth]:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "Agent Reach doctor payload must be an object"
        )

    channels: dict[str, AgentReachChannelHealth] = {}
    for raw_channel, raw_health in raw.items():
        channel = str(raw_channel)
        if not _SAFE_CHANNEL.fullmatch(channel):
            raise RuntimeError(
                f"Invalid Agent Reach channel name: {channel}"
            )
        if not isinstance(raw_health, Mapping):
            raise RuntimeError(
                f"Agent Reach channel {channel} must be an object"
            )

        status = raw_health.get("status")
        if status not in _ALLOWED_STATUSES:
            raise RuntimeError(
                "Agent Reach channel "
                f"{channel} has unsupported status: {status}"
            )

        name = raw_health.get("name")
        message = raw_health.get("message")
        tier = raw_health.get("tier")
        backends = raw_health.get("backends")
        active_backend = raw_health.get("active_backend")

        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                f"Agent Reach channel {channel} has invalid name"
            )
        if not isinstance(message, str):
            raise RuntimeError(
                f"Agent Reach channel {channel} has invalid message"
            )
        if (
            isinstance(tier, bool)
            or not isinstance(tier, int)
            or tier < 0
        ):
            raise RuntimeError(
                f"Agent Reach channel {channel} has invalid tier"
            )
        if not isinstance(backends, list) or not all(
            isinstance(item, str) and item.strip()
            for item in backends
        ):
            raise RuntimeError(
                f"Agent Reach channel {channel} has invalid backends"
            )
        if active_backend is not None and (
            not isinstance(active_backend, str)
            or not active_backend.strip()
        ):
            raise RuntimeError(
                "Agent Reach channel "
                f"{channel} has invalid active_backend"
            )

        channels[channel] = AgentReachChannelHealth(
            channel=channel,
            status=status,
            name=name.strip(),
            message=_redact(message.strip()),
            tier=tier,
            backends=tuple(backends),
            active_backend=active_backend,
        )

    if not channels:
        raise RuntimeError(
            "Agent Reach doctor returned no channels"
        )
    return channels


def channel_to_descriptor(
    health: AgentReachChannelHealth,
) -> CapabilityDescriptor:
    backend_text = (
        health.active_backend
        or "no healthy backend"
    )
    return CapabilityDescriptor(
        id=f"agent-reach.{health.channel}",
        kind="adapter",
        name=f"Agent Reach · {health.name}",
        short_description=(
            f"Read {health.name} through Agent Reach channel "
            f"'{health.channel}' using {backend_text}."
        ),
        availability=health.availability,
        full_description=health.message or None,
        instructions_ref=(
            "docs/MCC-M1.7_AGENT_REACH_ADAPTER.md"
            "#execution-contract"
        ),
        prerequisites=[],
        risk_tags=["external_network"],
        cost_class=(
            "free"
            if health.tier == 0
            else "low"
        ),
        metadata={
            "provider": "agent-reach",
            "managed_by": _AGENT_REACH_MANAGED_BY,
            "channel": health.channel,
            "tier": health.tier,
            "upstream_status": health.status,
            "backend_order": list(health.backends),
            "active_backend": health.active_backend,
            "routable": health.routable,
            "health_message": health.message,
        },
    )


def sync_agent_reach_capabilities(
    manager: CapabilityManager,
    snapshot: AgentReachDoctorSnapshot,
) -> dict[str, Any]:
    generated = [
        channel_to_descriptor(health)
        for _, health in sorted(
            snapshot.channels.items()
        )
    ]
    generated_ids = {
        capability.id
        for capability in generated
    }

    current = manager.list_capabilities()
    managed = [
        capability
        for capability in current
        if capability.metadata.get("managed_by")
        == _AGENT_REACH_MANAGED_BY
    ]
    preserved = [
        capability
        for capability in current
        if capability.metadata.get("managed_by")
        != _AGENT_REACH_MANAGED_BY
    ]

    collisions = sorted(
        generated_ids
        & {
            capability.id
            for capability in preserved
        }
    )
    if collisions:
        raise RuntimeError(
            "Agent Reach sync would overwrite "
            "unmanaged capabilities: "
            + ", ".join(collisions)
        )

    manager.set_registry(
        [*preserved, *generated]
    )
    manager.store.append_event(
        Event(
            type="capability.agent_reach_synced",
            mission_id=None,
            actor="cockpit",
            subject={
                "provider": "agent-reach",
                "channels": len(generated),
                "routable": sum(
                    1
                    for capability in generated
                    if capability.availability
                    == "available"
                ),
                "replaced_managed": len(managed),
                "preserved": len(preserved),
            },
        )
    )

    return {
        "provider": "agent-reach",
        "channels": len(generated),
        "routable": sum(
            1
            for capability in generated
            if capability.availability
            == "available"
        ),
        "replaced_managed": len(managed),
        "preserved": len(preserved),
        "capability_ids": sorted(
            generated_ids
        ),
        "doctor": snapshot.to_dict(),
    }
