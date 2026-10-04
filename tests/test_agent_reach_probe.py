import json
import subprocess

from mado_cockpit.agent_reach import (
    AgentReachDoctorSnapshot,
    parse_doctor_payload,
)
from mado_cockpit.agent_reach_probe import (
    AgentReachLiveProbe,
    ExternalWebEvidenceStore,
)
from mado_cockpit.capabilities import CapabilityManager
from mado_cockpit.models import (
    CapabilityDescriptor,
    Project,
)
from mado_cockpit.store import CockpitStore


class FakeResponse:
    def __init__(self, body: bytes):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        traceback,
    ):
        return False

    def read(self, size=-1):
        return self.body[:size]


def snapshot(
    *,
    github="ok",
    rss="ok",
    web="ok",
):
    def health(
        status,
        name,
        backend,
    ):
        return {
            "status": status,
            "name": name,
            "message": "fixture",
            "tier": 0,
            "backends": [backend],
            "active_backend": (
                backend
                if status == "ok"
                else None
            ),
        }

    return AgentReachDoctorSnapshot(
        command=(
            "agent-reach",
            "doctor",
            "--json",
        ),
        channels=parse_doctor_payload(
            {
                "github": health(
                    github,
                    "GitHub",
                    "gh CLI",
                ),
                "rss": health(
                    rss,
                    "RSS",
                    "feedparser",
                ),
                "web": health(
                    web,
                    "Web",
                    "Jina Reader",
                ),
            }
        ),
    )


def test_live_probe_passes_fixed_public_read_fixtures():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            "octocat/Hello-World\n",
            "",
        )

    def fake_urlopen(
        request,
        timeout,
    ):
        if request.full_url.endswith(
            "main.atom"
        ):
            return FakeResponse(
                (
                    "<?xml version='1.0'?>"
                    "<feed xmlns='http://www.w3.org/"
                    "2005/Atom'>"
                    "<title>Recent Commits</title>"
                    "</feed>"
                ).encode()
            )
        assert request.full_url == (
            "https://r.jina.ai/"
            "https://example.com/"
        )
        return FakeResponse(
            b"# Example Domain\nFixture body"
        )

    results = AgentReachLiveProbe(
        runner=fake_run,
        urlopen=fake_urlopen,
        timeout=4,
    ).probe(snapshot())

    assert [
        item.channel
        for item in results
    ] == ["github", "rss", "web"]
    assert all(
        item.status == "passed"
        for item in results
    )
    assert all(
        item.sha256
        for item in results
    )
    assert all(
        item.size_bytes
        for item in results
    )
    assert (
        results[0].probe_mode
        == "active_backend"
    )
    assert (
        results[1].probe_mode
        == "protocol_equivalent"
    )
    assert (
        calls[0][0][:3]
        == [
            "gh",
            "api",
            "repos/octocat/Hello-World",
        ]
    )
    assert (
        calls[0][1]["env"]["GH_TELEMETRY"]
        == "false"
    )


def test_non_routable_channel_is_skipped_without_network():
    def fail_run(*args, **kwargs):
        raise AssertionError(
            "subprocess must not run"
        )

    def fail_urlopen(*args, **kwargs):
        raise AssertionError(
            "network must not run"
        )

    results = AgentReachLiveProbe(
        runner=fail_run,
        urlopen=fail_urlopen,
    ).probe(
        snapshot(
            github="warn",
            rss="off",
            web="error",
        )
    )

    assert all(
        item.status == "skipped"
        for item in results
    )
    assert all(
        item.probe_mode == "not_run"
        for item in results
    )


def test_failed_probe_downgrades_available_capability(
    tmp_path,
):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    manager = CapabilityManager(store)
    manager.set_registry(
        [
            CapabilityDescriptor(
                id="agent-reach.web",
                kind="adapter",
                name="Agent Reach Web",
                short_description=(
                    "Read the public web"
                ),
                availability="available",
                cost_class="free",
                metadata={
                    "provider": "agent-reach",
                    "channel": "web",
                    "active_backend": (
                        "Jina Reader"
                    ),
                },
            )
        ]
    )

    probe = AgentReachLiveProbe(
        runner=(
            lambda *args, **kwargs:
            subprocess.CompletedProcess(
                [],
                0,
                "",
                "",
            )
        ),
        urlopen=(
            lambda *args, **kwargs:
            FakeResponse(
                b"not the expected fixture"
            )
        ),
    )
    evidence = probe.probe(
        snapshot(),
        channels=["web"],
    )

    result = ExternalWebEvidenceStore(
        store
    ).record(
        evidence,
        capabilities=manager,
    )

    capability = (
        manager.list_capabilities()[0]
    )
    assert result["failed"] == 1
    assert (
        capability.availability
        == "unknown"
    )
    assert (
        capability.metadata[
            "live_probe_verified"
        ]
        is False
    )
    assert (
        capability.metadata[
            "live_probe_status"
        ]
        == "failed"
    )


def test_passed_probe_records_hash_and_keeps_available(
    tmp_path,
):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    manager = CapabilityManager(store)
    manager.set_registry(
        [
            CapabilityDescriptor(
                id="agent-reach.web",
                kind="adapter",
                name="Agent Reach Web",
                short_description=(
                    "Read the public web"
                ),
                availability="available",
                cost_class="free",
                metadata={
                    "provider": "agent-reach",
                    "channel": "web",
                    "active_backend": (
                        "Jina Reader"
                    ),
                },
            )
        ]
    )

    probe = AgentReachLiveProbe(
        urlopen=(
            lambda *args, **kwargs:
            FakeResponse(
                b"# Example Domain\nfixture"
            )
        ),
    )
    evidence = probe.probe(
        snapshot(),
        channels=["web"],
    )
    item = evidence[0]

    ExternalWebEvidenceStore(
        store
    ).record(
        evidence,
        capabilities=manager,
    )

    saved = json.loads(
        (
            store.base
            / "external_web_evidence"
            / "agent_reach"
            / f"{item.id}.json"
        ).read_text(
            encoding="utf-8"
        )
    )
    capability = (
        manager.list_capabilities()[0]
    )

    assert saved["status"] == "passed"
    assert len(saved["sha256"]) == 64
    assert saved["size_bytes"] > 0
    assert (
        capability.availability
        == "available"
    )
    assert (
        capability.metadata[
            "live_probe_verified"
        ]
        is True
    )
    assert (
        capability.metadata[
            "live_probe_id"
        ]
        == item.id
    )
