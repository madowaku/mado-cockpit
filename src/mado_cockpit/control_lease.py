from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from .models import Event, utc_now
from .store import CockpitStore


CONTROL_LEASE_VERSION = "MCC-M2.4"
LeaseStatus = Literal[
    "active",
    "released",
    "expired",
]


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )
    return parsed.astimezone(
        timezone.utc
    )


def _iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _resource_digest(
    kind: str,
    resource_id: str,
) -> str:
    return hashlib.sha256(
        f"{kind}\0{resource_id}".encode(
            "utf-8"
        )
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ControlScope:
    kind: str
    resource_id: str

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise RuntimeError(
                "Control scope kind must not be empty"
            )
        if not self.resource_id.strip():
            raise RuntimeError(
                "Control scope resource_id must not be empty"
            )

    @property
    def digest(self) -> str:
        return _resource_digest(
            self.kind,
            self.resource_id,
        )

    def to_dict(
        self,
    ) -> dict[str, str]:
        return {
            "kind": self.kind,
            "resource_id": self.resource_id,
        }


class ControlLeaseError(
    RuntimeError
):
    pass


class ControlLeaseConflict(
    ControlLeaseError
):
    pass


class ControlLeaseManager:
    def __init__(
        self,
        store: CockpitStore,
        *,
        now: Callable[
            [],
            datetime,
        ]
        | None = None,
    ) -> None:
        self.store = store
        self.leases_dir = (
            store.base
            / "control_leases"
        )
        self._now = (
            now
            or (
                lambda: datetime.now(
                    timezone.utc
                )
            )
        )

    def acquire(
        self,
        scope: ControlScope,
        *,
        holder: str,
        ttl_seconds: int = 300,
        reason: str | None = None,
    ) -> dict[str, Any]:
        holder = holder.strip()
        if not holder:
            raise ControlLeaseError(
                "Control lease holder must not be empty"
            )
        if (
            ttl_seconds < 15
            or ttl_seconds > 3600
        ):
            raise ControlLeaseError(
                "Control lease ttl_seconds must be between 15 and 3600"
            )
        active = self.current(
            scope,
            expire=True,
        )
        if active is not None:
            raise ControlLeaseConflict(
                "Human control is already held "
                f"by {active['holder']} "
                f"under lease {active['id']}."
            )

        now = self._now()
        lease_id = (
            "hctrl_"
            f"{uuid4().hex[:12]}"
        )
        payload: dict[str, Any] = {
            "schema": (
                "mado.human-control-lease.v1"
            ),
            "version": (
                CONTROL_LEASE_VERSION
            ),
            "id": lease_id,
            "status": "active",
            "scope": scope.to_dict(),
            "scope_digest": scope.digest,
            "holder": holder,
            "reason": (
                reason.strip()
                if isinstance(reason, str)
                and reason.strip()
                else None
            ),
            "acquired_at": _iso(now),
            "heartbeat_at": _iso(now),
            "expires_at": _iso(
                now
                + timedelta(
                    seconds=ttl_seconds
                )
            ),
            "released_at": None,
            "expired_at": None,
        }
        self._write(payload)
        self._event(
            "control.lease.acquired",
            payload,
        )
        return payload

    def heartbeat(
        self,
        lease_id: str,
        *,
        holder: str,
        ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        if (
            ttl_seconds < 15
            or ttl_seconds > 3600
        ):
            raise ControlLeaseError(
                "Control lease ttl_seconds must be between 15 and 3600"
            )
        payload = self.inspect(
            lease_id,
            expire=True,
        )
        if payload["status"] != "active":
            raise ControlLeaseError(
                "Control lease is not active."
            )
        if (
            payload["holder"]
            != holder.strip()
        ):
            raise ControlLeaseError(
                "Control lease holder does not match."
            )

        now = self._now()
        payload["heartbeat_at"] = (
            _iso(now)
        )
        payload["expires_at"] = _iso(
            now
            + timedelta(
                seconds=ttl_seconds
            )
        )
        self._write(payload)
        self._event(
            "control.lease.heartbeat",
            payload,
        )
        return payload

    def release(
        self,
        lease_id: str,
        *,
        holder: str,
    ) -> dict[str, Any]:
        payload = self.inspect(
            lease_id,
            expire=True,
        )
        if payload["status"] != "active":
            raise ControlLeaseError(
                "Control lease is not active."
            )
        if (
            payload["holder"]
            != holder.strip()
        ):
            raise ControlLeaseError(
                "Control lease holder does not match."
            )

        now = self._now()
        payload["status"] = "released"
        payload["released_at"] = _iso(
            now
        )
        self._write(payload)
        self._event(
            "control.lease.released",
            payload,
        )
        return payload

    def inspect(
        self,
        lease_id: str,
        *,
        expire: bool = True,
    ) -> dict[str, Any]:
        path = (
            self.leases_dir
            / f"{lease_id}.json"
        )
        if not path.exists():
            raise ControlLeaseError(
                "Control lease not found: "
                f"{lease_id}"
            )
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
        if expire:
            payload = self._expire_if_needed(
                payload
            )
        return payload

    def current(
        self,
        scope: ControlScope,
        *,
        expire: bool = True,
    ) -> dict[str, Any] | None:
        if not self.leases_dir.exists():
            return None

        candidates: list[
            dict[str, Any]
        ] = []
        for path in sorted(
            self.leases_dir.glob(
                "*.json"
            )
        ):
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
            if (
                payload.get(
                    "scope_digest"
                )
                != scope.digest
            ):
                continue
            if expire:
                payload = (
                    self._expire_if_needed(
                        payload
                    )
                )
            if (
                payload.get("status")
                == "active"
            ):
                candidates.append(
                    payload
                )

        if not candidates:
            return None
        candidates.sort(
            key=lambda item: str(
                item["acquired_at"]
            ),
            reverse=True,
        )
        if len(candidates) > 1:
            raise ControlLeaseError(
                "Multiple active Human Control "
                "leases exist for one resource."
            )
        return candidates[0]

    def _expire_if_needed(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            payload.get("status")
            != "active"
        ):
            return payload
        now = self._now()
        expires = _parse_utc(
            str(
                payload["expires_at"]
            )
        )
        if now < expires:
            return payload

        payload["status"] = "expired"
        payload["expired_at"] = _iso(
            now
        )
        self._write(payload)
        self._event(
            "control.lease.expired",
            payload,
        )
        return payload

    def _write(
        self,
        payload: dict[str, Any],
    ) -> None:
        self.leases_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        path = (
            self.leases_dir
            / f"{payload['id']}.json"
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

    def _event(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        self.store.append_event(
            Event(
                type=event_type,
                actor="human_control",
                subject={
                    "lease_id": (
                        payload["id"]
                    ),
                    "status": (
                        payload["status"]
                    ),
                    "scope": (
                        payload["scope"]
                    ),
                    "holder": (
                        payload["holder"]
                    ),
                    "expires_at": (
                        payload["expires_at"]
                    ),
                },
            )
        )
