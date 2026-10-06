from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from mado_cockpit.artifact_workspaces import (
    ArtifactRepoInfo,
    ArtifactRepoProvision,
    ArtifactRepoToken,
    ArtifactWorkspaceManager,
)
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


class FixtureProvider:
    provider_id = "fixture_artifacts"
    namespace = "fixture"

    def __init__(self) -> None:
        self.revoked: list[str] = []
        self.deleted: list[str] = []

    def _repo(self, name: str) -> ArtifactRepoInfo:
        return ArtifactRepoInfo(
            repo_id=f"repo_{name}",
            name=name,
            remote=f"https://fixture.invalid/git/{name}.git",
            default_branch="main",
        )

    def create_repo(
        self,
        name: str,
        *,
        description: str | None = None,
        default_branch: str = "main",
        read_only: bool = False,
    ) -> ArtifactRepoProvision:
        return ArtifactRepoProvision(
            repo=self._repo(name),
            bootstrap_token="art_v1_bootstrap?expires=1790000000",
        )

    def import_repo(
        self,
        name: str,
        source_url: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        read_only: bool = False,
    ) -> ArtifactRepoProvision:
        return self.create_repo(name)

    def get_repo(self, name: str) -> ArtifactRepoInfo:
        return self._repo(name)

    def fork_repo(
        self,
        source_name: str,
        target_name: str,
        *,
        description: str | None = None,
        read_only: bool = False,
        default_branch_only: bool = True,
    ) -> ArtifactRepoProvision:
        return ArtifactRepoProvision(
            repo=self._repo(target_name),
            bootstrap_token="art_v1_fork?expires=1790000000",
        )

    def create_token(
        self,
        repo_name: str,
        *,
        scope: str,
        ttl: int,
    ) -> ArtifactRepoToken:
        return ArtifactRepoToken(
            token_id="token_fixture",
            plaintext="art_v1_fixture_secret?expires=1790003600",
            scope=scope,
            expires_at="2026-10-07T00:00:00Z",
        )

    def revoke_token(self, token_id: str) -> None:
        self.revoked.append(token_id)

    def delete_repo(self, repo_name: str) -> None:
        self.deleted.append(repo_name)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    store = CockpitStore(root)
    store.init(
        Project(
            id="artifact-smoke",
            name="Artifact Smoke",
            root=str(root),
        )
    )
    provider = FixtureProvider()
    manager = ArtifactWorkspaceManager(store, provider)

    baseline = manager.create(
        "baseline",
        kind="baseline",
        mission_id="MCC-ART-M0.0",
    )
    task = manager.fork(
        baseline["id"],
        "task-builder",
        kind="task",
        task_id="ART-TASK-1",
        worker_id="builder",
    )
    credential = manager.issue_lease(
        task["id"],
        scope="write",
        ttl=3600,
    )
    manager.revoke_lease(credential.lease.id)

    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / ".mado").rglob("*")
        if path.is_file()
    )
    secret_absent = (
        credential.plaintext not in persisted
        and "art_v1_bootstrap" not in persisted
        and "art_v1_fork" not in persisted
        and "https://x:" not in persisted
    )
    if not secret_absent:
        raise RuntimeError("artifact secret leaked into durable cockpit state")

    output = {
        "schema_version": "mado.artifact-workspace-smoke.v1",
        "baseline_workspace_id": baseline["id"],
        "task_workspace_id": task["id"],
        "lease_id": credential.lease.id,
        "lease_status": manager.get_lease(
            credential.lease.id
        )["status"],
        "secret_absent_from_durable_state": secret_absent,
        "event_types": [
            event["type"]
            for event in store.list_events(limit=50)
            if event["type"].startswith("artifact.")
        ],
    }
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
