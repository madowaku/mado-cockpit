from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from uuid import uuid4

from .agent_reach import AgentReachDoctorSnapshot
from .capabilities import CapabilityManager
from .models import Event, utc_now
from .store import CockpitStore


_MAX_BODY_BYTES = 512 * 1024
_EXCERPT_CHARS = 500

_GITHUB_REPO = "octocat/Hello-World"
_GITHUB_EXPECTED = "octocat/Hello-World"
_RSS_URL = "https://github.com/python/cpython/commits/main.atom"
_WEB_URL = "https://example.com/"
_JINA_URL = f"https://r.jina.ai/{_WEB_URL}"

_GH_READ_ONLY_ENV = {
    "GH_TELEMETRY": "false",
    "DO_NOT_TRACK": "true",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "GH_NO_EXTENSION_UPDATE_NOTIFIER": "1",
}


Runner = Callable[..., subprocess.CompletedProcess[str]]
UrlOpen = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ExternalWebProbeEvidence:
    id: str
    provider: str
    channel: str
    backend: str
    target: str
    probe_mode: str
    status: str
    sha256: str | None
    size_bytes: int | None
    excerpt: str | None
    error: str | None
    checked_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_excerpt(value: str) -> str:
    compact = " ".join(value.split())
    return compact[:_EXCERPT_CHARS]


def _hash_text(value: str) -> tuple[str, int]:
    payload = value.encode("utf-8")
    return (
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )


class AgentReachLiveProbe:
    """Safe public-read probes for selected Agent Reach channels."""

    SUPPORTED_CHANNELS = ("github", "rss", "web")

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        runner: Runner = subprocess.run,
        urlopen: UrlOpen = urllib.request.urlopen,
        python_binary: str | None = None,
    ) -> None:
        if timeout <= 0:
            raise RuntimeError(
                "Live probe timeout must be greater than zero"
            )
        self.timeout = timeout
        self.runner = runner
        self.urlopen = urlopen
        self.python_binary = (
            python_binary or sys.executable
        )

    def probe(
        self,
        snapshot: AgentReachDoctorSnapshot,
        *,
        channels: Sequence[str] | None = None,
    ) -> list[ExternalWebProbeEvidence]:
        requested = (
            list(channels)
            if channels is not None
            else list(self.SUPPORTED_CHANNELS)
        )
        unknown = sorted(
            set(requested)
            - set(self.SUPPORTED_CHANNELS)
        )
        if unknown:
            raise RuntimeError(
                "Unsupported Agent Reach live probe channel(s): "
                + ", ".join(unknown)
            )

        results: list[ExternalWebProbeEvidence] = []
        for channel in requested:
            health = snapshot.channels.get(channel)
            if health is None:
                results.append(
                    self._skipped(
                        channel,
                        "channel missing from doctor snapshot",
                    )
                )
                continue
            if not health.routable:
                results.append(
                    self._skipped(
                        channel,
                        (
                            "doctor did not mark channel routable "
                            f"(status={health.status}, "
                            f"active_backend={health.active_backend!r})"
                        ),
                        backend=(
                            health.active_backend
                            or (
                                health.backends[0]
                                if health.backends
                                else "unknown"
                            )
                        ),
                    )
                )
                continue

            if channel == "github":
                results.append(
                    self._probe_github(
                        health.active_backend
                        or "gh CLI"
                    )
                )
            elif channel == "rss":
                results.append(
                    self._probe_rss(
                        health.active_backend
                        or "feedparser"
                    )
                )
            elif channel == "web":
                results.append(
                    self._probe_web(
                        health.active_backend
                        or "Jina Reader"
                    )
                )
        return results

    def _probe_github(
        self,
        backend: str,
    ) -> ExternalWebProbeEvidence:
        command = [
            "gh",
            "api",
            f"repos/{_GITHUB_REPO}",
            "--method",
            "GET",
            "--jq",
            ".full_name",
        ]
        env = os.environ.copy()
        env.update(_GH_READ_ONLY_ENV)
        try:
            result = self.runner(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return self._failed(
                "github",
                backend,
                _GITHUB_REPO,
                "active_backend",
                str(exc),
            )

        body = result.stdout.strip()
        if result.returncode != 0:
            return self._failed(
                "github",
                backend,
                _GITHUB_REPO,
                "active_backend",
                (
                    result.stderr.strip()
                    or body
                    or f"exit code {result.returncode}"
                ),
            )
        if body != _GITHUB_EXPECTED:
            return self._failed(
                "github",
                backend,
                _GITHUB_REPO,
                "active_backend",
                (
                    "unexpected repository identity: "
                    f"{_safe_excerpt(body)}"
                ),
            )
        return self._passed(
            "github",
            backend,
            _GITHUB_REPO,
            "active_backend",
            body,
        )

    def _probe_rss(
        self,
        backend: str,
    ) -> ExternalWebProbeEvidence:
        # Agent Reach's RSS backend is an in-process feedparser module rather
        # than a standalone CLI. Cockpit therefore performs a protocol-level
        # equivalent public read and XML parse without importing private
        # Agent Reach state or credentials.
        try:
            body = self._read_url(_RSS_URL)
            root = ET.fromstring(body)
        except (
            OSError,
            ValueError,
            ET.ParseError,
        ) as exc:
            return self._failed(
                "rss",
                backend,
                _RSS_URL,
                "protocol_equivalent",
                str(exc),
            )

        tag = root.tag.casefold()
        if "feed" not in tag and "rss" not in tag:
            return self._failed(
                "rss",
                backend,
                _RSS_URL,
                "protocol_equivalent",
                f"unexpected root element: {root.tag}",
            )
        text = body.decode(
            "utf-8",
            errors="replace",
        )
        return self._passed(
            "rss",
            backend,
            _RSS_URL,
            "protocol_equivalent",
            text,
        )

    def _probe_web(
        self,
        backend: str,
    ) -> ExternalWebProbeEvidence:
        try:
            body = self._read_url(
                _JINA_URL,
                accept="text/plain",
            )
        except (OSError, ValueError) as exc:
            return self._failed(
                "web",
                backend,
                _WEB_URL,
                "active_backend",
                str(exc),
            )
        text = body.decode(
            "utf-8",
            errors="replace",
        )
        lowered = text.casefold()
        if "example domain" not in lowered:
            return self._failed(
                "web",
                backend,
                _WEB_URL,
                "active_backend",
                "Jina Reader response did not contain expected fixture text",
            )
        return self._passed(
            "web",
            backend,
            _WEB_URL,
            "active_backend",
            text,
        )

    def _read_url(
        self,
        url: str,
        *,
        accept: str = (
            "application/atom+xml,"
            "application/rss+xml,"
            "application/xml,text/xml"
        ),
    ) -> bytes:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "mado-cockpit-agent-reach-probe/1",
                "Accept": accept,
            },
            method="GET",
        )
        with self.urlopen(
            request,
            timeout=self.timeout,
        ) as response:
            body = response.read(
                _MAX_BODY_BYTES + 1
            )
        if len(body) > _MAX_BODY_BYTES:
            raise ValueError(
                "live probe response exceeds "
                f"{_MAX_BODY_BYTES} byte limit"
            )
        if not body:
            raise ValueError(
                "live probe returned an empty response"
            )
        return body

    def _passed(
        self,
        channel: str,
        backend: str,
        target: str,
        probe_mode: str,
        body: str,
    ) -> ExternalWebProbeEvidence:
        digest, size = _hash_text(body)
        return ExternalWebProbeEvidence(
            id=f"webprb_{uuid4().hex[:12]}",
            provider="agent-reach",
            channel=channel,
            backend=backend,
            target=target,
            probe_mode=probe_mode,
            status="passed",
            sha256=digest,
            size_bytes=size,
            excerpt=_safe_excerpt(body),
            error=None,
            checked_at=utc_now(),
        )

    def _failed(
        self,
        channel: str,
        backend: str,
        target: str,
        probe_mode: str,
        error: str,
    ) -> ExternalWebProbeEvidence:
        return ExternalWebProbeEvidence(
            id=f"webprb_{uuid4().hex[:12]}",
            provider="agent-reach",
            channel=channel,
            backend=backend,
            target=target,
            probe_mode=probe_mode,
            status="failed",
            sha256=None,
            size_bytes=None,
            excerpt=None,
            error=_safe_excerpt(error),
            checked_at=utc_now(),
        )

    def _skipped(
        self,
        channel: str,
        error: str,
        *,
        backend: str = "unknown",
    ) -> ExternalWebProbeEvidence:
        return ExternalWebProbeEvidence(
            id=f"webprb_{uuid4().hex[:12]}",
            provider="agent-reach",
            channel=channel,
            backend=backend,
            target="",
            probe_mode="not_run",
            status="skipped",
            sha256=None,
            size_bytes=None,
            excerpt=None,
            error=error,
            checked_at=utc_now(),
        )


class ExternalWebEvidenceStore:
    def __init__(
        self,
        store: CockpitStore,
    ) -> None:
        self.store = store
        self.root = (
            store.base
            / "external_web_evidence"
            / "agent_reach"
        )

    def record(
        self,
        evidence: Sequence[
            ExternalWebProbeEvidence
        ],
        *,
        capabilities: CapabilityManager,
    ) -> dict[str, Any]:
        self.root.mkdir(
            parents=True,
            exist_ok=True,
        )
        written: list[dict[str, Any]] = []
        for item in evidence:
            path = self.root / f"{item.id}.json"
            if path.exists():
                raise RuntimeError(
                    "External web evidence already exists: "
                    f"{item.id}"
                )
            payload = item.to_dict()
            path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            written.append(payload)
            self.store.append_event(
                Event(
                    type=(
                        "capability."
                        "agent_reach_probe_recorded"
                    ),
                    mission_id=None,
                    actor="cockpit",
                    subject={
                        "probe_id": item.id,
                        "channel": item.channel,
                        "backend": item.backend,
                        "status": item.status,
                        "sha256": item.sha256,
                    },
                )
            )

        self._apply_to_registry(
            capabilities,
            evidence,
        )
        return {
            "provider": "agent-reach",
            "recorded": len(written),
            "passed": sum(
                1
                for item in evidence
                if item.status == "passed"
            ),
            "failed": sum(
                1
                for item in evidence
                if item.status == "failed"
            ),
            "skipped": sum(
                1
                for item in evidence
                if item.status == "skipped"
            ),
            "evidence": written,
        }

    def list(
        self,
        *,
        channel: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        items = [
            json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
            for path in sorted(
                self.root.glob("*.json")
            )
        ]
        if channel is None:
            return items
        return [
            item
            for item in items
            if item["channel"] == channel
        ]

    def latest(
        self,
        channel: str,
    ) -> dict[str, Any] | None:
        items = self.list(
            channel=channel
        )
        if not items:
            return None
        return max(
            items,
            key=lambda item: item["checked_at"],
        )

    def _apply_to_registry(
        self,
        manager: CapabilityManager,
        evidence: Sequence[
            ExternalWebProbeEvidence
        ],
    ) -> None:
        latest = {
            item.channel: item
            for item in evidence
        }
        current = manager.list_capabilities()
        if not current:
            return

        changed = False
        updated = []
        for capability in current:
            channel = capability.metadata.get(
                "channel"
            )
            provider = capability.metadata.get(
                "provider"
            )
            item = latest.get(str(channel))
            if (
                provider != "agent-reach"
                or item is None
            ):
                updated.append(capability)
                continue

            capability.metadata[
                "live_probe_status"
            ] = item.status
            capability.metadata[
                "live_probe_id"
            ] = item.id
            capability.metadata[
                "live_probe_checked_at"
            ] = item.checked_at
            capability.metadata[
                "live_probe_mode"
            ] = item.probe_mode
            capability.metadata[
                "live_probe_sha256"
            ] = item.sha256

            if item.status == "passed":
                capability.metadata[
                    "live_probe_verified"
                ] = True
            else:
                capability.metadata[
                    "live_probe_verified"
                ] = False
                if (
                    capability.availability
                    == "available"
                ):
                    capability.availability = (
                        "unknown"
                    )
            changed = True
            updated.append(capability)

        if changed:
            manager.set_registry(updated)


def run_and_record_live_probes(
    store: CockpitStore,
    snapshot: AgentReachDoctorSnapshot,
    *,
    channels: Sequence[str] | None = None,
    timeout: float = 20.0,
    runner: Runner = subprocess.run,
    urlopen: UrlOpen = urllib.request.urlopen,
) -> dict[str, Any]:
    manager = CapabilityManager(store)
    probe = AgentReachLiveProbe(
        timeout=timeout,
        runner=runner,
        urlopen=urlopen,
    )
    evidence = probe.probe(
        snapshot,
        channels=channels,
    )
    return ExternalWebEvidenceStore(
        store
    ).record(
        evidence,
        capabilities=manager,
    )
