import json
import subprocess
import sys
from pathlib import Path

import pytest

from mado_cockpit.capabilities import (
    CapabilityManager,
    CapabilityPolicy,
    DeterministicCapabilityPager,
    SystemOnePagerBridge,
)
from mado_cockpit.models import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilitySuggestion,
    Mission,
    Project,
)
from mado_cockpit.operator import OperatorManager
from mado_cockpit.providers import ProviderTurnResult
from mado_cockpit.sessions import SessionManager
from mado_cockpit.store import CockpitStore


FIXTURE_REGISTRY = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "capabilities"
    / "mcc-m0.6.json"
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    git(path, "init", "-b", "main")
    git(
        path,
        "config",
        "user.email",
        "fixture@example.com",
    )
    git(
        path,
        "config",
        "user.name",
        "Fixture",
    )
    (path / ".gitignore").write_text(
        ".mado/\n",
        encoding="utf-8",
    )
    (path / "README.md").write_text(
        "fixture\n",
        encoding="utf-8",
    )
    git(path, "add", ".")
    git(path, "commit", "-m", "fixture")


def setup_store(
    tmp_path: Path,
) -> CockpitStore:
    init_repo(tmp_path)
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    store.save_mission(
        Mission(
            id="MCC-M0.6",
            title="Capability Pager Bridge",
        )
    )
    return store


def test_imports_system_one_registry_and_binds_deterministic_match(
    tmp_path,
):
    store = setup_store(tmp_path)
    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.6",
        "Implement code changes in this repository",
        required_evidence=[
            "git_diff",
        ],
    )

    capabilities = CapabilityManager(
        store
    )
    imported = capabilities.import_registry(
        FIXTURE_REGISTRY
    )
    assert len(imported) == 5
    assert imported[0][
        "short_description"
    ].startswith("Implement code changes")

    resolved = operator.resolve_capability(
        run["plan"]["id"],
        "builder",
        pager=DeterministicCapabilityPager(),
    )

    resolution = resolved[
        "capability"
    ]["resolution"]
    assert (
        resolution["status"]
        == "resolved"
    )
    assert (
        resolution[
            "selected_capability"
        ]
        == "codex-cli"
    )

    binding = resolved[
        "capability"
    ]["binding"]
    assert (
        binding["worker_id"]
        == run["plan"][
            "builder_worker_id"
        ]
    )
    assert (
        binding["capability_id"]
        == "codex-cli"
    )

    bound = resolved[
        "operator"
    ]["builder_capabilities"]
    assert [
        item["id"]
        for item in bound
    ] == ["codex-cli"]


class FixedPager:
    def __init__(
        self,
        suggestion: CapabilitySuggestion,
    ) -> None:
        self.suggestion = suggestion

    def resolve(
        self,
        request,
        capabilities,
    ) -> CapabilitySuggestion:
        return self.suggestion


def test_policy_can_reject_primary_and_bind_safe_alternative(
    tmp_path,
):
    store = setup_store(tmp_path)
    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.6",
        "Review deployment evidence",
        required_evidence=[
            "git_diff",
        ],
    )
    manager = CapabilityManager(store)
    manager.import_registry(
        FIXTURE_REGISTRY
    )

    suggestion = CapabilitySuggestion(
        suggested_capability="prod-deploy",
        confidence=0.95,
        alternatives=[
            "qa-review",
        ],
        reason_codes=[
            "wide_rank",
            "deep_fit",
            "advisory_suggestion",
        ],
        advisory_only=True,
        wide_trace_id="fixture:wide",
        deep_trace_id="fixture:deep",
    )

    result = manager.resolve(
        run["plan"]["builder_worker_id"],
        "Review the deployment evidence safely",
        pager=FixedPager(suggestion),
        policy=CapabilityPolicy(
            min_confidence=0.4,
            max_cost_class="low",
        ),
    )

    resolution = result["resolution"]
    assert (
        resolution[
            "selected_capability"
        ]
        == "qa-review"
    )
    assert (
        "selected_alternative"
        in resolution[
            "policy_reasons"
        ]
    )
    assert any(
        reason.startswith(
            "prod-deploy:"
        )
        for reason in resolution[
            "policy_reasons"
        ]
    )


def test_policy_leaves_dangerous_capability_unresolved(
    tmp_path,
):
    store = setup_store(tmp_path)
    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.6",
        "Deploy production",
        required_evidence=[
            "git_diff",
        ],
    )
    manager = CapabilityManager(store)
    manager.import_registry(
        FIXTURE_REGISTRY
    )

    suggestion = CapabilitySuggestion(
        suggested_capability="prod-deploy",
        confidence=0.99,
        alternatives=[],
        reason_codes=[
            "advisory_suggestion",
        ],
        advisory_only=True,
        wide_trace_id="fixture:wide",
    )

    result = manager.resolve(
        run["plan"]["builder_worker_id"],
        "Deploy production",
        pager=FixedPager(suggestion),
    )

    assert (
        result["resolution"]["status"]
        == "unresolved"
    )
    assert result["binding"] is None
    assert (
        manager.list_bindings(
            run["plan"][
                "builder_worker_id"
            ]
        )
        == []
    )


def test_system_one_bridge_accepts_public_suggestion_contract(
    tmp_path,
):
    bridge = tmp_path / "bridge.py"
    bridge.write_text(
        "\n".join(
            [
                "import json, sys",
                "payload = json.load(sys.stdin)",
                "assert payload['request']['traceId'] == 'capreq-fixture'",
                "assert payload['capabilities'][0]['shortDescription'] == 'Inspect GitHub repositories'",
                "json.dump({",
                "  'suggestedCapability': 'github',",
                "  'confidence': 0.88,",
                "  'alternatives': [],",
                "  'reasonCodes': ['wide_rank', 'deep_fit', 'advisory_suggestion'],",
                "  'advisoryOnly': True,",
                "  'wideTraceId': 'capreq-fixture:wide',",
                "  'deepTraceId': 'capreq-fixture:deep',",
                "}, sys.stdout)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    pager = SystemOnePagerBridge(
        [
            sys.executable,
            str(bridge),
        ]
    )
    suggestion = pager.resolve(
        CapabilityRequest(
            id="capreq-fixture",
            worker_id="builder",
            request="Inspect GitHub repositories",
            trace_id="capreq-fixture",
        ),
        [
            CapabilityDescriptor(
                id="github",
                kind="plugin",
                name="GitHub",
                short_description=(
                    "Inspect GitHub repositories"
                ),
                availability="available",
                cost_class="low",
            )
        ],
    )

    assert (
        suggestion.suggested_capability
        == "github"
    )
    assert suggestion.confidence == 0.88
    assert suggestion.advisory_only is True
    assert (
        suggestion.deep_trace_id
        == "capreq-fixture:deep"
    )


class FakeProvider:
    name = "codex"

    def __init__(self) -> None:
        self.last_prompt = None

    def start(
        self,
        *,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        self.last_prompt = prompt
        return ProviderTurnResult(
            external_session_id=(
                f"thread-{workspace.name}"
            ),
            exit_code=0,
            stdout=(
                '{"type":"thread.started",'
                f'"thread_id":"thread-{workspace.name}"'
                '}\n'
            ),
            stderr="",
            last_message="started",
        )

    def send(
        self,
        *,
        external_session_id: str,
        workspace: Path,
        prompt: str,
        model: str | None = None,
    ) -> ProviderTurnResult:
        self.last_prompt = prompt
        return ProviderTurnResult(
            external_session_id=(
                external_session_id
            ),
            exit_code=0,
            stdout=(
                '{"type":"thread.started",'
                f'"thread_id":"{external_session_id}"'
                '}\n'
            ),
            stderr="",
            last_message="resumed",
        )

    def status(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        return {
            "process_running": False,
        }

    def stop(
        self,
        session: dict[str, object],
    ) -> dict[str, object]:
        return {
            "stopped": True,
        }


def test_operator_launch_requires_binding_when_registry_is_active(
    tmp_path,
):
    store = setup_store(tmp_path)
    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.6",
        "Implement code changes in this repository",
        required_evidence=[
            "session_trace",
        ],
    )
    CapabilityManager(
        store
    ).import_registry(
        FIXTURE_REGISTRY
    )

    provider = FakeProvider()
    sessions = SessionManager(
        store,
        providers={
            "codex": provider,
        },
    )

    with pytest.raises(
        RuntimeError,
        match="no capability binding",
    ):
        operator.launch(
            run["plan"]["id"],
            "builder",
            sessions=sessions,
        )

    operator.resolve_capability(
        run["plan"]["id"],
        "builder",
        pager=DeterministicCapabilityPager(),
    )
    launched = operator.launch(
        run["plan"]["id"],
        "builder",
        sessions=sessions,
    )

    assert (
        launched[
            "builder_capabilities"
        ][0]["id"]
        == "codex-cli"
    )
    assert provider.last_prompt is not None
    assert (
        "[codex-cli] Codex CLI"
        in provider.last_prompt
    )
    assert (
        "Use only capabilities that "
        "Cockpit bound to this worker."
        in provider.last_prompt
    )


def test_capability_events_are_persisted(
    tmp_path,
):
    store = setup_store(tmp_path)
    operator = OperatorManager(store)
    run = operator.start(
        "MCC-M0.6",
        "Implement code changes",
        required_evidence=[
            "git_diff",
        ],
    )
    manager = CapabilityManager(store)
    manager.import_registry(
        FIXTURE_REGISTRY
    )
    manager.resolve(
        run["plan"]["builder_worker_id"],
        "Implement code changes",
        pager=DeterministicCapabilityPager(),
    )

    event_types = [
        json.loads(line)["type"]
        for line in store.events_file.read_text(
            encoding="utf-8"
        ).splitlines()
        if line.strip()
    ]

    assert "capability.requested" in event_types
    assert "capability.resolved" in event_types
    assert "capability.bound" in event_types
