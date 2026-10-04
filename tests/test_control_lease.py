from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest

from mado_cockpit.control_lease import (
    ControlLeaseConflict,
    ControlLeaseError,
    ControlLeaseManager,
    ControlScope,
)
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


class Clock:
    def __init__(self):
        self.value = datetime(
            2026,
            10,
            4,
            7,
            0,
            tzinfo=timezone.utc,
        )

    def now(self):
        return self.value

    def advance(self, seconds):
        self.value += timedelta(
            seconds=seconds
        )


def _manager(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="m2.4-fixture",
            name="M2.4 Fixture",
            root=str(tmp_path),
        )
    )
    clock = Clock()
    return (
        store,
        clock,
        ControlLeaseManager(
            store,
            now=clock.now,
        ),
    )


def test_acquire_persists_active_human_control(tmp_path):
    store, _, manager = _manager(
        tmp_path
    )
    scope = ControlScope(
        "browser",
        "session-1",
    )

    lease = manager.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=120,
        reason="Take over login.",
    )

    assert lease["status"] == "active"
    assert lease["scope"] == {
        "kind": "browser",
        "resource_id": "session-1",
    }
    assert (
        manager.current(scope)["id"]
        == lease["id"]
    )
    assert any(
        event["type"]
        == "control.lease.acquired"
        for event in store.list_events()
    )


def test_second_active_lease_is_refused(tmp_path):
    _, _, manager = _manager(
        tmp_path
    )
    scope = ControlScope(
        "computer",
        "computer-1",
    )
    manager.acquire(
        scope,
        holder="human:a",
        ttl_seconds=60,
    )

    with pytest.raises(
        ControlLeaseConflict,
        match="already held",
    ):
        manager.acquire(
            scope,
            holder="human:b",
            ttl_seconds=60,
        )


def test_heartbeat_extends_only_matching_holder(tmp_path):
    _, clock, manager = _manager(
        tmp_path
    )
    scope = ControlScope(
        "browser",
        "session-1",
    )
    lease = manager.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=60,
    )
    first_expiry = lease[
        "expires_at"
    ]
    clock.advance(30)

    renewed = manager.heartbeat(
        lease["id"],
        holder="human:owner",
        ttl_seconds=120,
    )

    assert (
        renewed["expires_at"]
        != first_expiry
    )
    with pytest.raises(
        ControlLeaseError,
        match="holder",
    ):
        manager.heartbeat(
            lease["id"],
            holder="human:other",
            ttl_seconds=120,
        )


def test_release_clears_active_fence(tmp_path):
    _, _, manager = _manager(
        tmp_path
    )
    scope = ControlScope(
        "browser",
        "session-1",
    )
    lease = manager.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=60,
    )

    released = manager.release(
        lease["id"],
        holder="human:owner",
    )

    assert (
        released["status"]
        == "released"
    )
    assert (
        manager.current(scope)
        is None
    )


def test_expired_lease_fails_open_for_automation(tmp_path):
    store, clock, manager = _manager(
        tmp_path
    )
    scope = ControlScope(
        "computer",
        "computer-1",
    )
    lease = manager.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=15,
    )
    clock.advance(16)

    assert (
        manager.current(scope)
        is None
    )
    expired = manager.inspect(
        lease["id"]
    )
    assert (
        expired["status"]
        == "expired"
    )
    assert any(
        event["type"]
        == "control.lease.expired"
        for event in store.list_events()
    )


def test_scope_digest_does_not_expose_resource_in_filename(
    tmp_path,
):
    _, _, manager = _manager(
        tmp_path
    )
    scope = ControlScope(
        "browser",
        "https://private.example/path",
    )
    lease = manager.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=60,
    )

    paths = list(
        manager.leases_dir.glob(
            "*.json"
        )
    )
    assert len(paths) == 1
    assert (
        "private.example"
        not in paths[0].name
    )
    assert (
        paths[0].stem
        == lease["id"]
    )
