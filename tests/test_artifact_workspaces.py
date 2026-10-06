import json
from pathlib import Path
from typing import Any

import pytest

from mado_cockpit.artifact_workspaces import (
    ArtifactWorkspaceManager,
    authenticated_git_remote,
)
from mado_cockpit.cloudflare_artifacts import (
    CloudflareArtifactsClient,
    CloudflareArtifactsConfig,
    CloudflareArtifactsError,
)
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


class FakeTransport:
    def __init__(
        self,
        responses: list[tuple[int, dict[str, Any]]],
    ) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
            }
        )
        if not self.responses:
            raise AssertionError("No fake Cloudflare response left")
        return self.responses.pop(0)


def envelope(result: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return (
        200,
        {
            "result": result,
            "success": True,
            "errors": [],
            "messages": [],
        },
    )


def provision(
    name: str,
    *,
    repo_id: str,
    token: str,
) -> tuple[int, dict[str, Any]]:
    return envelope(
        {
            "id": repo_id,
            "name": name,
            "description": None,
            "default_branch": "main",
            "remote": (
                "https://acct.artifacts.cloudflare.net/"
                f"git/mado/{name}.git"
            ),
            "token": token,
        }
    )


def make_manager(
    tmp_path: Path,
    responses: list[tuple[int, dict[str, Any]]],
) -> tuple[
    ArtifactWorkspaceManager,
    FakeTransport,
    CockpitStore,
]:
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    transport = FakeTransport(responses)
    client = CloudflareArtifactsClient(
        CloudflareArtifactsConfig(
            account_id="acct",
            api_token="cf-control-secret",
            namespace="mado",
        ),
        transport=transport,
    )
    return (
        ArtifactWorkspaceManager(store, client),
        transport,
        store,
    )


def test_cloudflare_create_and_fork_persist_no_bootstrap_secret(
    tmp_path: Path,
) -> None:
    bootstrap = "art_v1_bootstrap?expires=1790000000"
    fork_bootstrap = "art_v1_fork?expires=1790000100"
    manager, transport, store = make_manager(
        tmp_path,
        [
            provision(
                "mado-baseline",
                repo_id="repo_base",
                token=bootstrap,
            ),
            provision(
                "mission-123-builder",
                repo_id="repo_fork",
                token=fork_bootstrap,
            ),
        ],
    )

    baseline = manager.create(
        "mado-baseline",
        kind="baseline",
        description="MADO source baseline",
        mission_id="MCC-ART",
    )
    forked = manager.fork(
        baseline["id"],
        "mission-123-builder",
        kind="mission",
        worker_id="builder",
    )

    assert baseline["schema_version"] == "mado.artifact-workspace.v1"
    assert baseline["bootstrap_token_persisted"] is False
    assert forked["parent_workspace_id"] == baseline["id"]
    assert forked["parent_repo_name"] == "mado-baseline"
    assert forked["bootstrap_token_persisted"] is False

    assert transport.calls[0]["method"] == "POST"
    assert transport.calls[0]["url"].endswith(
        "/accounts/acct/artifacts/namespaces/mado/repos"
    )
    assert transport.calls[0]["body"] == {
        "name": "mado-baseline",
        "default_branch": "main",
        "read_only": False,
        "description": "MADO source baseline",
    }
    assert transport.calls[1]["url"].endswith(
        "/repos/mado-baseline/fork"
    )
    assert transport.calls[1]["body"]["name"] == "mission-123-builder"
    assert (
        transport.calls[1]["body"]["default_branch_only"]
        is True
    )

    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / ".mado").rglob("*")
        if path.is_file()
    )
    assert bootstrap not in persisted
    assert fork_bootstrap not in persisted
    assert "cf-control-secret" not in persisted
    assert "https://x:" not in persisted

    events = store.list_events(limit=20)
    event_types = [item["type"] for item in events]
    assert "artifact.workspace.created" in event_types
    assert "artifact.workspace.forked" in event_types


def test_import_baseline_uses_cloudflare_import_route(
    tmp_path: Path,
) -> None:
    manager, transport, _ = make_manager(
        tmp_path,
        [
            provision(
                "mado-cockpit-baseline",
                repo_id="repo_import",
                token="art_v1_import?expires=1790000000",
            )
        ],
    )

    workspace = manager.import_baseline(
        "mado-cockpit-baseline",
        "https://github.com/madowaku/mado-cockpit.git",
        branch="main",
        depth=100,
    )

    assert workspace["kind"] == "baseline"
    assert (
        workspace["source_url"]
        == "https://github.com/madowaku/mado-cockpit.git"
    )
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith(
        "/repos/mado-cockpit-baseline/import"
    )
    assert call["body"] == {
        "url": "https://github.com/madowaku/mado-cockpit.git",
        "read_only": False,
        "branch": "main",
        "depth": 100,
    }


def test_repo_scoped_lease_is_ephemeral_and_revocable(
    tmp_path: Path,
) -> None:
    lease_secret = "art_v1_write_abcdef?expires=1790003600"
    manager, transport, store = make_manager(
        tmp_path,
        [
            provision(
                "task-workspace",
                repo_id="repo_task",
                token="art_v1_boot?expires=1790000000",
            ),
            envelope(
                {
                    "id": "token_123",
                    "plaintext": lease_secret,
                    "scope": "write",
                    "expires_at": "2026-10-07T00:00:00Z",
                }
            ),
            envelope({"id": "token_123"}),
        ],
    )
    workspace = manager.create(
        "task-workspace",
        kind="task",
        task_id="TASK-1",
    )

    credential = manager.issue_lease(
        workspace["id"],
        scope="write",
        ttl=3600,
    )

    assert credential.lease.schema_version == "mado.artifact-lease.v1"
    assert credential.lease.token_id == "token_123"
    assert credential.lease.plaintext_persisted is False
    assert credential.plaintext == lease_secret
    assert credential.authenticated_remote.startswith(
        "https://x:art_v1_write_abcdef@"
    )
    assert "?expires=" not in credential.authenticated_remote
    assert credential.public_dict()["secret_persisted"] is False

    token_call = transport.calls[1]
    assert token_call["url"].endswith(
        "/accounts/acct/artifacts/namespaces/mado/tokens"
    )
    assert token_call["body"] == {
        "repo": "task-workspace",
        "scope": "write",
        "ttl": 3600,
    }

    lease_path = (
        tmp_path
        / ".mado"
        / "cockpit"
        / "artifacts"
        / "leases"
        / f"{credential.lease.id}.json"
    )
    lease_text = lease_path.read_text(encoding="utf-8")
    assert lease_secret not in lease_text
    assert "authenticated_remote" not in lease_text

    events_text = store.events_file.read_text(encoding="utf-8")
    assert lease_secret not in events_text
    assert "https://x:" not in events_text

    revoked = manager.revoke_lease(credential.lease.id)
    assert revoked["status"] == "revoked"
    assert revoked["revoked_at"]
    assert transport.calls[2]["method"] == "DELETE"
    assert transport.calls[2]["url"].endswith("/tokens/token_123")


def test_delete_requires_exact_confirmation_and_no_active_lease(
    tmp_path: Path,
) -> None:
    manager, transport, _ = make_manager(
        tmp_path,
        [
            provision(
                "experiment-a",
                repo_id="repo_exp",
                token="art_v1_boot?expires=1790000000",
            ),
            envelope(
                {
                    "id": "token_exp",
                    "plaintext": "art_v1_exp?expires=1790003600",
                    "scope": "read",
                    "expires_at": "2026-10-07T00:00:00Z",
                }
            ),
            envelope({"id": "token_exp"}),
            (202, {
                "result": {"id": "repo_exp"},
                "success": True,
                "errors": [],
                "messages": [],
            }),
        ],
    )
    workspace = manager.create(
        "experiment-a",
        kind="experiment",
    )
    credential = manager.issue_lease(
        workspace["id"],
        scope="read",
        ttl=60,
    )

    with pytest.raises(
        RuntimeError,
        match="exact repo-name confirmation",
    ):
        manager.delete(
            workspace["id"],
            confirm_repo_name="wrong-name",
        )

    with pytest.raises(
        RuntimeError,
        match="active leases",
    ):
        manager.delete(
            workspace["id"],
            confirm_repo_name="experiment-a",
        )

    manager.revoke_lease(credential.lease.id)
    deleted = manager.delete(
        workspace["id"],
        confirm_repo_name="experiment-a",
    )
    assert deleted["status"] == "deleted"
    assert transport.calls[-1]["method"] == "DELETE"
    assert transport.calls[-1]["url"].endswith("/repos/experiment-a")


def test_authenticated_remote_rejects_credentialed_remote() -> None:
    with pytest.raises(
        RuntimeError,
        match="must not already contain credentials",
    ):
        authenticated_git_remote(
            "https://user:pass@example.invalid/repo.git",
            "art_v1_x?expires=1",
        )


@pytest.mark.parametrize("ttl", [0, 59, 31_536_001])
def test_token_ttl_bounds_fail_closed(
    tmp_path: Path,
    ttl: int,
) -> None:
    manager, _, _ = make_manager(
        tmp_path,
        [
            provision(
                "ttl-test",
                repo_id="repo_ttl",
                token="art_v1_boot?expires=1790000000",
            )
        ],
    )
    workspace = manager.create("ttl-test", kind="task")

    with pytest.raises(
        RuntimeError,
        match="TTL must be between",
    ):
        manager.issue_lease(
            workspace["id"],
            ttl=ttl,
        )


def test_cloudflare_error_envelope_is_not_treated_as_success() -> None:
    transport = FakeTransport(
        [
            (
                409,
                {
                    "result": None,
                    "success": False,
                    "errors": [
                        {
                            "code": 10200,
                            "message": "Repository is still forking",
                        }
                    ],
                    "messages": [],
                },
            )
        ]
    )
    client = CloudflareArtifactsClient(
        CloudflareArtifactsConfig(
            account_id="acct",
            api_token="secret",
            namespace="mado",
        ),
        transport=transport,
    )

    with pytest.raises(
        CloudflareArtifactsError,
        match="10200: Repository is still forking",
    ):
        client.get_repo("repo-a")


def test_config_repr_does_not_expose_control_plane_token() -> None:
    config = CloudflareArtifactsConfig(
        account_id="acct",
        api_token="super-secret",
        namespace="mado",
    )
    assert "super-secret" not in repr(config)
