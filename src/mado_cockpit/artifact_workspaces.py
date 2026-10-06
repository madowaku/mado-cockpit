from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit
from uuid import uuid4

from .models import Event, utc_now
from .store import CockpitStore


_SAFE_LOCAL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ALLOWED_KINDS = {"baseline", "mission", "task", "session", "experiment"}
_ALLOWED_SCOPES = {"read", "write"}
_MIN_TOKEN_TTL_SECONDS = 60
_MAX_TOKEN_TTL_SECONDS = 31_536_000


@dataclass(slots=True, frozen=True)
class ArtifactRepoInfo:
    repo_id: str
    name: str
    remote: str
    default_branch: str
    description: str | None = None
    read_only: bool = False
    source: str | None = None


@dataclass(slots=True, frozen=True)
class ArtifactRepoProvision:
    repo: ArtifactRepoInfo
    bootstrap_token: str | None = field(default=None, repr=False)


@dataclass(slots=True, frozen=True)
class ArtifactRepoToken:
    token_id: str
    plaintext: str = field(repr=False)
    scope: str = "write"
    expires_at: str = ""


class ArtifactWorkspaceProvider(Protocol):
    provider_id: str
    namespace: str

    def create_repo(
        self,
        name: str,
        *,
        description: str | None = None,
        default_branch: str = "main",
        read_only: bool = False,
    ) -> ArtifactRepoProvision: ...

    def import_repo(
        self,
        name: str,
        source_url: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        read_only: bool = False,
    ) -> ArtifactRepoProvision: ...

    def get_repo(self, name: str) -> ArtifactRepoInfo: ...

    def fork_repo(
        self,
        source_name: str,
        target_name: str,
        *,
        description: str | None = None,
        read_only: bool = False,
        default_branch_only: bool = True,
    ) -> ArtifactRepoProvision: ...

    def create_token(
        self,
        repo_name: str,
        *,
        scope: str,
        ttl: int,
    ) -> ArtifactRepoToken: ...

    def revoke_token(self, token_id: str) -> None: ...

    def delete_repo(self, repo_name: str) -> None: ...


@dataclass(slots=True)
class ArtifactWorkspace:
    id: str
    provider: str
    namespace: str
    repo_id: str
    repo_name: str
    remote: str
    default_branch: str
    kind: str
    status: str = "ready"
    description: str | None = None
    source_url: str | None = None
    parent_workspace_id: str | None = None
    parent_repo_name: str | None = None
    mission_id: str | None = None
    worker_id: str | None = None
    task_id: str | None = None
    session_id: str | None = None
    bootstrap_token_persisted: bool = False
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: str = "mado.artifact-workspace.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ArtifactLease:
    id: str
    workspace_id: str
    provider: str
    namespace: str
    repo_name: str
    token_id: str
    scope: str
    expires_at: str
    status: str = "active"
    issued_at: str = field(default_factory=utc_now)
    revoked_at: str | None = None
    plaintext_persisted: bool = False
    schema_version: str = "mado.artifact-lease.v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class EphemeralArtifactCredential:
    lease: ArtifactLease
    plaintext: str = field(repr=False)
    authenticated_remote: str = field(repr=False)

    def public_dict(self) -> dict[str, Any]:
        return {
            "lease": self.lease.to_dict(),
            "secret_returned": True,
            "secret_persisted": False,
            "authenticated_remote_persisted": False,
        }


def validate_repo_name(name: str) -> str:
    value = name.strip()
    if not value:
        raise RuntimeError("Artifact repo name must not be empty")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise RuntimeError(
            "Artifact repo name must be a single repository name without path separators"
        )
    if any(ord(char) < 32 for char in value):
        raise RuntimeError("Artifact repo name must not contain control characters")
    return value


def validate_workspace_kind(kind: str) -> str:
    value = kind.strip()
    if value not in _ALLOWED_KINDS:
        raise RuntimeError(
            "Artifact workspace kind must be one of: "
            + ", ".join(sorted(_ALLOWED_KINDS))
        )
    return value


def validate_token_scope(scope: str) -> str:
    value = scope.strip()
    if value not in _ALLOWED_SCOPES:
        raise RuntimeError("Artifact token scope must be read or write")
    return value


def validate_token_ttl(ttl: int) -> int:
    if not isinstance(ttl, int) or isinstance(ttl, bool):
        raise RuntimeError("Artifact token TTL must be an integer number of seconds")
    if ttl < _MIN_TOKEN_TTL_SECONDS or ttl > _MAX_TOKEN_TTL_SECONDS:
        raise RuntimeError(
            "Artifact token TTL must be between "
            f"{_MIN_TOKEN_TTL_SECONDS} and {_MAX_TOKEN_TTL_SECONDS} seconds"
        )
    return ttl


def authenticated_git_remote(remote: str, token: str) -> str:
    if not remote.startswith("https://"):
        raise RuntimeError("Artifact Git remote must use HTTPS")
    secret = token.split("?expires=", 1)[0]
    if not secret:
        raise RuntimeError("Artifact token must not be empty")
    parsed = urlsplit(remote)
    if parsed.username or parsed.password:
        raise RuntimeError("Artifact Git remote must not already contain credentials")
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    userinfo = f"x:{quote(secret, safe='')}"
    return urlunsplit(
        (
            parsed.scheme,
            f"{userinfo}@{host}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


class ArtifactWorkspaceManager:
    def __init__(
        self,
        store: CockpitStore,
        provider: ArtifactWorkspaceProvider | None = None,
    ) -> None:
        self.store = store
        self.provider = provider
        self.base = store.base / "artifacts"
        self.workspaces_dir = self.base / "workspaces"
        self.leases_dir = self.base / "leases"

    def create(
        self,
        repo_name: str,
        *,
        kind: str,
        description: str | None = None,
        default_branch: str = "main",
        read_only: bool = False,
        mission_id: str | None = None,
        worker_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        name = validate_repo_name(repo_name)
        kind = validate_workspace_kind(kind)
        provider = self._require_provider()
        provision = provider.create_repo(
            name,
            description=description,
            default_branch=default_branch,
            read_only=read_only,
        )
        workspace = self._workspace_from_repo(
            provision.repo,
            kind=kind,
            description=description,
            mission_id=mission_id,
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
        )
        self._save_new_workspace(workspace)
        self._event(
            "artifact.workspace.created",
            workspace,
            extra={
                "operation": "create",
                "bootstrap_token_discarded": provision.bootstrap_token is not None,
            },
        )
        return workspace.to_dict()

    def import_baseline(
        self,
        repo_name: str,
        source_url: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        read_only: bool = False,
        description: str | None = None,
        mission_id: str | None = None,
    ) -> dict[str, Any]:
        name = validate_repo_name(repo_name)
        source = source_url.strip()
        if not source.startswith("https://"):
            raise RuntimeError("Artifact import source must be an HTTPS Git remote")
        if depth is not None and (not isinstance(depth, int) or depth < 1):
            raise RuntimeError("Artifact import depth must be a positive integer")

        provider = self._require_provider()
        provision = provider.import_repo(
            name,
            source,
            branch=branch,
            depth=depth,
            read_only=read_only,
        )
        workspace = self._workspace_from_repo(
            provision.repo,
            kind="baseline",
            description=description,
            source_url=source,
            mission_id=mission_id,
        )
        self._save_new_workspace(workspace)
        self._event(
            "artifact.workspace.imported",
            workspace,
            extra={
                "operation": "import",
                "source_url": source,
                "bootstrap_token_discarded": provision.bootstrap_token is not None,
            },
        )
        return workspace.to_dict()

    def fork(
        self,
        parent_workspace_id: str,
        repo_name: str,
        *,
        kind: str,
        description: str | None = None,
        read_only: bool = False,
        default_branch_only: bool = True,
        mission_id: str | None = None,
        worker_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        parent = self.get(parent_workspace_id)
        if parent["status"] != "ready":
            raise RuntimeError(
                f"Parent artifact workspace is not ready: {parent_workspace_id}"
            )
        name = validate_repo_name(repo_name)
        kind = validate_workspace_kind(kind)
        provider = self._require_provider()
        provision = provider.fork_repo(
            str(parent["repo_name"]),
            name,
            description=description,
            read_only=read_only,
            default_branch_only=default_branch_only,
        )
        workspace = self._workspace_from_repo(
            provision.repo,
            kind=kind,
            description=description,
            parent_workspace_id=parent_workspace_id,
            parent_repo_name=str(parent["repo_name"]),
            mission_id=mission_id or self._optional_str(parent.get("mission_id")),
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
        )
        self._save_new_workspace(workspace)
        self._event(
            "artifact.workspace.forked",
            workspace,
            extra={
                "operation": "fork",
                "parent_workspace_id": parent_workspace_id,
                "parent_repo_name": parent["repo_name"],
                "default_branch_only": default_branch_only,
                "bootstrap_token_discarded": provision.bootstrap_token is not None,
            },
        )
        return workspace.to_dict()

    def issue_lease(
        self,
        workspace_id: str,
        *,
        scope: str = "write",
        ttl: int = 3600,
    ) -> EphemeralArtifactCredential:
        workspace = self.get(workspace_id)
        if workspace["status"] != "ready":
            raise RuntimeError(
                f"Artifact workspace is not ready: {workspace_id}"
            )
        scope = validate_token_scope(scope)
        ttl = validate_token_ttl(ttl)
        provider = self._require_provider()
        token = provider.create_token(
            str(workspace["repo_name"]),
            scope=scope,
            ttl=ttl,
        )
        lease = ArtifactLease(
            id=f"artl_{uuid4().hex[:12]}",
            workspace_id=workspace_id,
            provider=provider.provider_id,
            namespace=provider.namespace,
            repo_name=str(workspace["repo_name"]),
            token_id=token.token_id,
            scope=scope,
            expires_at=token.expires_at,
        )
        self._save_lease(lease)
        self._event(
            "artifact.lease.issued",
            workspace,
            extra={
                "lease_id": lease.id,
                "token_id": lease.token_id,
                "scope": scope,
                "expires_at": lease.expires_at,
                "plaintext_persisted": False,
            },
        )
        return EphemeralArtifactCredential(
            lease=lease,
            plaintext=token.plaintext,
            authenticated_remote=authenticated_git_remote(
                str(workspace["remote"]),
                token.plaintext,
            ),
        )

    def revoke_lease(self, lease_id: str) -> dict[str, Any]:
        lease = self.get_lease(lease_id)
        if lease["status"] == "revoked":
            return lease
        provider = self._require_provider()
        provider.revoke_token(str(lease["token_id"]))
        lease["status"] = "revoked"
        lease["revoked_at"] = utc_now()
        self._write_json(self.leases_dir / f"{lease_id}.json", lease)
        workspace = self.get(str(lease["workspace_id"]))
        self._event(
            "artifact.lease.revoked",
            workspace,
            extra={
                "lease_id": lease_id,
                "token_id": lease["token_id"],
            },
        )
        return lease

    def delete(
        self,
        workspace_id: str,
        *,
        confirm_repo_name: str,
    ) -> dict[str, Any]:
        workspace = self.get(workspace_id)
        repo_name = str(workspace["repo_name"])
        if confirm_repo_name != repo_name:
            raise RuntimeError(
                "Artifact workspace deletion requires exact repo-name confirmation"
            )
        active = [
            lease
            for lease in self.list_leases(workspace_id=workspace_id)
            if lease["status"] == "active"
        ]
        if active:
            raise RuntimeError(
                "Artifact workspace has active leases; revoke them before deletion"
            )
        if workspace["status"] == "deleted":
            return workspace
        provider = self._require_provider()
        provider.delete_repo(repo_name)
        workspace["status"] = "deleted"
        workspace["updated_at"] = utc_now()
        self._write_json(
            self.workspaces_dir / f"{workspace_id}.json",
            workspace,
        )
        self._event(
            "artifact.workspace.deleted",
            workspace,
            extra={"operation": "delete"},
        )
        return workspace

    def get(self, workspace_id: str) -> dict[str, Any]:
        self._validate_local_id(workspace_id, "Artifact workspace id")
        path = self.workspaces_dir / f"{workspace_id}.json"
        if not path.exists():
            raise RuntimeError(
                f"Artifact workspace not found: {workspace_id}"
            )
        return self._read_json(path)

    def list(self) -> list[dict[str, Any]]:
        if not self.workspaces_dir.exists():
            return []
        return [
            self._read_json(path)
            for path in sorted(self.workspaces_dir.glob("artw_*.json"))
        ]

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        self._validate_local_id(lease_id, "Artifact lease id")
        path = self.leases_dir / f"{lease_id}.json"
        if not path.exists():
            raise RuntimeError(f"Artifact lease not found: {lease_id}")
        return self._read_json(path)

    def list_leases(
        self,
        *,
        workspace_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.leases_dir.exists():
            return []
        rows = [
            self._read_json(path)
            for path in sorted(self.leases_dir.glob("artl_*.json"))
        ]
        if workspace_id is None:
            return rows
        return [
            row for row in rows if row["workspace_id"] == workspace_id
        ]

    def _workspace_from_repo(
        self,
        repo: ArtifactRepoInfo,
        *,
        kind: str,
        description: str | None = None,
        source_url: str | None = None,
        parent_workspace_id: str | None = None,
        parent_repo_name: str | None = None,
        mission_id: str | None = None,
        worker_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
    ) -> ArtifactWorkspace:
        self._assert_safe_remote(repo.remote)
        return ArtifactWorkspace(
            id=f"artw_{uuid4().hex[:12]}",
            provider=self._require_provider().provider_id,
            namespace=self._require_provider().namespace,
            repo_id=repo.repo_id,
            repo_name=repo.name,
            remote=repo.remote,
            default_branch=repo.default_branch,
            kind=kind,
            description=description or repo.description,
            source_url=source_url,
            parent_workspace_id=parent_workspace_id,
            parent_repo_name=parent_repo_name,
            mission_id=mission_id,
            worker_id=worker_id,
            task_id=task_id,
            session_id=session_id,
        )

    def _save_new_workspace(self, workspace: ArtifactWorkspace) -> None:
        path = self.workspaces_dir / f"{workspace.id}.json"
        if path.exists():
            raise RuntimeError(
                f"Artifact workspace already exists: {workspace.id}"
            )
        self._write_json(path, workspace.to_dict())

    def _save_lease(self, lease: ArtifactLease) -> None:
        path = self.leases_dir / f"{lease.id}.json"
        if path.exists():
            raise RuntimeError(f"Artifact lease already exists: {lease.id}")
        payload = lease.to_dict()
        forbidden = {"plaintext", "token", "authenticated_remote"}
        if forbidden.intersection(payload):
            raise RuntimeError("Artifact lease persistence attempted to include a secret")
        self._write_json(path, payload)

    def _event(
        self,
        event_type: str,
        workspace: ArtifactWorkspace | dict[str, Any],
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        payload = (
            workspace.to_dict()
            if isinstance(workspace, ArtifactWorkspace)
            else workspace
        )
        subject: dict[str, Any] = {
            "artifact_workspace_id": payload["id"],
            "provider": payload["provider"],
            "namespace": payload["namespace"],
            "repo_id": payload["repo_id"],
            "repo_name": payload["repo_name"],
            "kind": payload["kind"],
            "status": payload["status"],
        }
        if extra:
            subject.update(extra)
        serialized = json.dumps(subject)
        if "art_v1_" in serialized or "https://x:" in serialized:
            raise RuntimeError("Artifact event attempted to persist a credential")
        self.store.append_event(
            Event(
                type=event_type,
                mission_id=self._optional_str(payload.get("mission_id")),
                actor="cockpit",
                subject=subject,
            )
        )

    def _require_provider(self) -> ArtifactWorkspaceProvider:
        if self.provider is None:
            raise RuntimeError(
                "Artifact operation requires a configured remote provider"
            )
        return self.provider

    @staticmethod
    def _assert_safe_remote(remote: str) -> None:
        parsed = urlsplit(remote)
        if parsed.scheme != "https":
            raise RuntimeError("Artifact remote must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise RuntimeError(
                "Artifact workspace metadata must not persist credentialed remotes"
            )

    @staticmethod
    def _validate_local_id(value: str, label: str) -> None:
        if not _SAFE_LOCAL_ID.fullmatch(value):
            raise RuntimeError(
                f"{label} contains unsupported characters"
            )

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return str(value) if value is not None else None

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))
