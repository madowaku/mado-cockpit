from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .artifact_workspaces import (
    ArtifactRepoInfo,
    ArtifactRepoProvision,
    ArtifactRepoToken,
    validate_repo_name,
    validate_token_scope,
    validate_token_ttl,
)


class CloudflareArtifactsError(RuntimeError):
    pass


class ArtifactHttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]: ...


class UrllibArtifactHttpTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        data = None
        request_headers = dict(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=data,
            method=method,
            headers=request_headers,
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                return response.status, payload
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                payload = {
                    "success": False,
                    "errors": [{"message": raw or str(exc)}],
                }
            return exc.code, payload
        except URLError as exc:
            raise CloudflareArtifactsError(
                f"Cloudflare Artifacts request failed: {exc.reason}"
            ) from exc


@dataclass(slots=True, frozen=True)
class CloudflareArtifactsConfig:
    account_id: str
    api_token: str = field(repr=False)
    namespace: str = "default"
    api_base: str = "https://api.cloudflare.com/client/v4"

    def __post_init__(self) -> None:
        if not self.account_id.strip():
            raise RuntimeError("Cloudflare account id must not be empty")
        if not self.api_token.strip():
            raise RuntimeError("Cloudflare API token must not be empty")
        if not self.namespace.strip():
            raise RuntimeError("Cloudflare Artifacts namespace must not be empty")
        if "/" in self.namespace or "\\" in self.namespace:
            raise RuntimeError(
                "Cloudflare Artifacts namespace must not contain path separators"
            )


class CloudflareArtifactsClient:
    provider_id = "cloudflare_artifacts"

    def __init__(
        self,
        config: CloudflareArtifactsConfig,
        *,
        transport: ArtifactHttpTransport | None = None,
    ) -> None:
        self.config = config
        self.namespace = config.namespace
        self.transport = transport or UrllibArtifactHttpTransport()

    @property
    def base_url(self) -> str:
        namespace = quote(self.config.namespace, safe="")
        return (
            f"{self.config.api_base.rstrip('/')}/accounts/"
            f"{quote(self.config.account_id, safe='')}/artifacts/"
            f"namespaces/{namespace}"
        )

    def create_repo(
        self,
        name: str,
        *,
        description: str | None = None,
        default_branch: str = "main",
        read_only: bool = False,
    ) -> ArtifactRepoProvision:
        repo_name = validate_repo_name(name)
        body: dict[str, Any] = {
            "name": repo_name,
            "default_branch": default_branch,
            "read_only": read_only,
        }
        if description is not None:
            body["description"] = description
        result = self._request("POST", "/repos", body=body)
        return self._provision(result)

    def import_repo(
        self,
        name: str,
        source_url: str,
        *,
        branch: str | None = None,
        depth: int | None = None,
        read_only: bool = False,
    ) -> ArtifactRepoProvision:
        repo_name = validate_repo_name(name)
        body: dict[str, Any] = {
            "url": source_url,
            "read_only": read_only,
        }
        if branch is not None:
            body["branch"] = branch
        if depth is not None:
            body["depth"] = depth
        result = self._request(
            "POST",
            f"/repos/{quote(repo_name, safe='')}/import",
            body=body,
        )
        return self._provision(result)

    def get_repo(self, name: str) -> ArtifactRepoInfo:
        repo_name = validate_repo_name(name)
        result = self._request(
            "GET",
            f"/repos/{quote(repo_name, safe='')}",
        )
        return self._repo_info(result)

    def fork_repo(
        self,
        source_name: str,
        target_name: str,
        *,
        description: str | None = None,
        read_only: bool = False,
        default_branch_only: bool = True,
    ) -> ArtifactRepoProvision:
        source = validate_repo_name(source_name)
        target = validate_repo_name(target_name)
        body: dict[str, Any] = {
            "name": target,
            "read_only": read_only,
            "default_branch_only": default_branch_only,
        }
        if description is not None:
            body["description"] = description
        result = self._request(
            "POST",
            f"/repos/{quote(source, safe='')}/fork",
            body=body,
        )
        return self._provision(result)

    def create_token(
        self,
        repo_name: str,
        *,
        scope: str,
        ttl: int,
    ) -> ArtifactRepoToken:
        repo = validate_repo_name(repo_name)
        scope = validate_token_scope(scope)
        ttl = validate_token_ttl(ttl)
        result = self._request(
            "POST",
            "/tokens",
            body={
                "repo": repo,
                "scope": scope,
                "ttl": ttl,
            },
        )
        token_id = self._required_str(result, "id")
        plaintext = self._required_str(result, "plaintext")
        expires_at = self._required_str(result, "expires_at")
        return ArtifactRepoToken(
            token_id=token_id,
            plaintext=plaintext,
            scope=scope,
            expires_at=expires_at,
        )

    def revoke_token(self, token_id: str) -> None:
        value = token_id.strip()
        if not value:
            raise RuntimeError("Artifact token id must not be empty")
        self._request(
            "DELETE",
            f"/tokens/{quote(value, safe='')}",
        )

    def delete_repo(self, repo_name: str) -> None:
        repo = validate_repo_name(repo_name)
        self._request(
            "DELETE",
            f"/repos/{quote(repo, safe='')}",
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        status, payload = self.transport.request(
            method,
            f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.config.api_token}",
                "Accept": "application/json",
            },
            body=body,
        )
        if not isinstance(payload, dict):
            raise CloudflareArtifactsError(
                "Cloudflare Artifacts returned a non-object response"
            )
        success = payload.get("success")
        result = payload.get("result")
        if 200 <= status < 300 and success is True and result is not None:
            if not isinstance(result, dict):
                raise CloudflareArtifactsError(
                    "Cloudflare Artifacts result must be an object"
                )
            return result

        messages: list[str] = []
        errors = payload.get("errors")
        if isinstance(errors, list):
            for error in errors:
                if isinstance(error, dict):
                    message = error.get("message")
                    code = error.get("code")
                    if message:
                        messages.append(
                            f"{code}: {message}" if code is not None else str(message)
                        )
        detail = "; ".join(messages) or f"HTTP {status}"
        raise CloudflareArtifactsError(
            f"Cloudflare Artifacts API request failed: {detail}"
        )

    def _provision(self, result: dict[str, Any]) -> ArtifactRepoProvision:
        return ArtifactRepoProvision(
            repo=self._repo_info(result),
            bootstrap_token=(
                str(result["token"])
                if isinstance(result.get("token"), str)
                and result["token"]
                else None
            ),
        )

    def _repo_info(self, result: dict[str, Any]) -> ArtifactRepoInfo:
        return ArtifactRepoInfo(
            repo_id=self._required_str(result, "id"),
            name=self._required_str(result, "name"),
            remote=self._required_str(result, "remote"),
            default_branch=self._required_str(result, "default_branch"),
            description=(
                str(result["description"])
                if result.get("description") is not None
                else None
            ),
            read_only=bool(result.get("read_only", False)),
            source=(
                str(result["source"])
                if result.get("source") is not None
                else None
            ),
        )

    @staticmethod
    def _required_str(result: dict[str, Any], key: str) -> str:
        value = result.get(key)
        if not isinstance(value, str) or not value:
            raise CloudflareArtifactsError(
                f"Cloudflare Artifacts result is missing {key}"
            )
        return value
