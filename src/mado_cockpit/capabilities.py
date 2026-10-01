from __future__ import annotations

import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, Sequence
from uuid import uuid4

from .models import (
    CapabilityBinding,
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResolution,
    CapabilitySuggestion,
    Event,
)
from .store import CockpitStore


_CAPABILITY_KINDS = {
    "skill",
    "native_tool",
    "plugin",
    "mcp",
    "cli",
    "harness",
    "adapter",
    "browser",
    "computer_use",
}
_AVAILABILITY = {
    "available",
    "unavailable",
    "unknown",
}
_COST_CLASSES = {
    "free",
    "low",
    "medium",
    "high",
}
_COST_RANK = {
    "free": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}
_SAFE_ID = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*$"
)


@dataclass(slots=True)
class CapabilityPolicy:
    min_confidence: float = 0.4
    max_cost_class: str = "low"
    denied_risk_tags: tuple[str, ...] = (
        "billing",
        "production",
        "publish",
        "delete",
        "external_message",
    )

    def __post_init__(self) -> None:
        if (
            not 0
            <= self.min_confidence
            <= 1
        ):
            raise RuntimeError(
                "min_confidence must be within [0, 1]"
            )
        if (
            self.max_cost_class
            not in _COST_CLASSES
        ):
            raise RuntimeError(
                "max_cost_class must be one of: "
                "free, low, medium, high"
            )


class CapabilityPager(Protocol):
    def resolve(
        self,
        request: CapabilityRequest,
        capabilities: Sequence[
            CapabilityDescriptor
        ],
    ) -> CapabilitySuggestion:
        ...


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(
            r"[a-z0-9_+-]+",
            value.lower(),
        )
        if len(token) > 1
    }


class DeterministicCapabilityPager:
    """
    Zero-quota fixture/default pager.

    This is not System One itself. It implements the same
    suggestion contract so Cockpit policy/binding can be
    tested without a model or external service.
    """

    def resolve(
        self,
        request: CapabilityRequest,
        capabilities: Sequence[
            CapabilityDescriptor
        ],
    ) -> CapabilitySuggestion:
        available = [
            capability
            for capability in capabilities
            if capability.availability
            == "available"
        ]
        wide_trace_id = (
            f"{request.trace_id}:wide"
        )

        if not available:
            return CapabilitySuggestion(
                suggested_capability=None,
                confidence=1.0,
                alternatives=[],
                reason_codes=[
                    "no_available_capabilities"
                ],
                advisory_only=True,
                wide_trace_id=wide_trace_id,
            )

        request_tokens = _tokens(
            request.request
        )
        scored: list[
            tuple[int, CapabilityDescriptor]
        ] = []

        for capability in available:
            searchable = " ".join(
                [
                    capability.id,
                    capability.name,
                    capability.short_description,
                    (
                        capability.full_description
                        or ""
                    ),
                    " ".join(
                        str(value)
                        for value
                        in capability.metadata.values()
                    ),
                ]
            )
            score = len(
                request_tokens
                & _tokens(searchable)
            )
            scored.append(
                (score, capability)
            )

        scored.sort(
            key=lambda item: (
                -item[0],
                item[1].id,
            )
        )
        top_score = scored[0][0]
        if top_score <= 0:
            return CapabilitySuggestion(
                suggested_capability=None,
                confidence=0.5,
                alternatives=[],
                reason_codes=[
                    "deterministic_no_match"
                ],
                advisory_only=True,
                wide_trace_id=wide_trace_id,
                deep_trace_id=(
                    f"{request.trace_id}:deep"
                ),
            )

        best = scored[0][1]
        alternatives = [
            capability.id
            for score, capability
            in scored[1:]
            if score > 0
        ]
        confidence = min(
            0.99,
            0.55
            + 0.1 * top_score,
        )

        return CapabilitySuggestion(
            suggested_capability=best.id,
            confidence=confidence,
            alternatives=alternatives,
            reason_codes=[
                "deterministic_keyword_match",
                "advisory_suggestion",
            ],
            advisory_only=True,
            wide_trace_id=wide_trace_id,
            deep_trace_id=(
                f"{request.trace_id}:deep"
            ),
        )


class SystemOnePagerBridge:
    """
    Calls a JSON stdin/stdout bridge that returns the public
    MADO System One CapabilitySuggestion shape.
    """

    def __init__(
        self,
        command: Sequence[str] | str,
        *,
        cwd: Path | None = None,
    ) -> None:
        if isinstance(command, str):
            self.command = shlex.split(
                command
            )
        else:
            self.command = list(command)
        if not self.command:
            raise RuntimeError(
                "System One bridge command "
                "must not be empty"
            )
        self.cwd = cwd

    def resolve(
        self,
        request: CapabilityRequest,
        capabilities: Sequence[
            CapabilityDescriptor
        ],
    ) -> CapabilitySuggestion:
        payload = {
            "request": {
                "traceId": request.trace_id,
                "request": request.request,
                "metadata": request.metadata,
            },
            "capabilities": [
                descriptor_to_system_one(
                    capability
                )
                for capability
                in capabilities
            ],
        }
        try:
            result = subprocess.run(
                self.command,
                cwd=(
                    str(self.cwd)
                    if self.cwd
                    else None
                ),
                input=json.dumps(
                    payload,
                    ensure_ascii=False,
                ),
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "System One bridge executable "
                f"not found: {self.command[0]}"
            ) from exc

        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
            )
            raise RuntimeError(
                "System One bridge failed: "
                f"{detail}"
            )

        try:
            raw = json.loads(
                result.stdout
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "System One bridge returned "
                "invalid JSON"
            ) from exc

        return parse_system_one_suggestion(
            raw
        )


class CapabilityManager:
    def __init__(
        self,
        store: CockpitStore,
    ) -> None:
        self.store = store
        self.root = (
            store.base / "capabilities"
        )
        self.registry_file = (
            self.root / "registry.json"
        )
        self.requests_dir = (
            self.root / "requests"
        )
        self.resolutions_dir = (
            self.root / "resolutions"
        )
        self.bindings_dir = (
            self.root / "bindings"
        )

    def import_registry(
        self,
        path: Path | str,
    ) -> list[dict[str, Any]]:
        source = Path(path)
        raw = json.loads(
            source.read_text(
                encoding="utf-8"
            )
        )
        if isinstance(raw, dict):
            values = raw.get(
                "capabilities"
            )
        else:
            values = raw

        if not isinstance(
            values,
            list,
        ):
            raise RuntimeError(
                "Capability registry must be "
                "a JSON list or "
                '{"capabilities": [...]}'
            )

        capabilities = [
            parse_descriptor(item)
            for item in values
        ]
        self.set_registry(
            capabilities
        )
        return [
            capability.to_dict()
            for capability
            in capabilities
        ]

    def set_registry(
        self,
        capabilities: Sequence[
            CapabilityDescriptor
        ],
    ) -> None:
        seen: set[str] = set()
        payload: list[
            dict[str, Any]
        ] = []
        for capability in capabilities:
            self._validate_descriptor(
                capability
            )
            if capability.id in seen:
                raise RuntimeError(
                    "Duplicate capability id: "
                    f"{capability.id}"
                )
            seen.add(
                capability.id
            )
            payload.append(
                capability.to_dict()
            )

        self._write_json(
            self.registry_file,
            {
                "capabilities": payload,
            },
        )

    def list_capabilities(
        self,
    ) -> list[CapabilityDescriptor]:
        if not self.registry_file.exists():
            return []
        raw = self._read_json(
            self.registry_file
        )
        return [
            CapabilityDescriptor(
                **item
            )
            for item in raw[
                "capabilities"
            ]
        ]

    def resolve(
        self,
        worker_id: str,
        request_text: str,
        *,
        pager: CapabilityPager,
        policy: CapabilityPolicy
        | None = None,
        metadata: dict[
            str, Any
        ] | None = None,
    ) -> dict[str, Any]:
        worker = self.store.get_worker(
            worker_id
        )
        capabilities = (
            self.list_capabilities()
        )
        if not capabilities:
            raise RuntimeError(
                "Capability registry is empty"
            )
        if not request_text.strip():
            raise RuntimeError(
                "Capability request must "
                "not be empty"
            )

        request_id = (
            f"capreq_{uuid4().hex[:12]}"
        )
        request = CapabilityRequest(
            id=request_id,
            worker_id=worker_id,
            request=request_text.strip(),
            trace_id=request_id,
            metadata=(
                metadata or {}
            ),
        )
        self._write_json(
            self.requests_dir
            / f"{request_id}.json",
            request.to_dict(),
        )
        mission_id = (
            str(
                worker.get(
                    "mission_id"
                )
            )
            if worker.get(
                "mission_id"
            )
            is not None
            else None
        )
        self.store.append_event(
            Event(
                type="capability.requested",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "request_id": request_id,
                    "worker_id": worker_id,
                    "request": (
                        request.request
                    ),
                },
            )
        )

        try:
            suggestion = pager.resolve(
                request,
                capabilities,
            )
        except Exception as exc:
            resolution = self._record_resolution(
                request=request,
                suggestion=CapabilitySuggestion(
                    suggested_capability=None,
                    confidence=0.0,
                    alternatives=[],
                    reason_codes=[
                        "pager_error"
                    ],
                    advisory_only=True,
                    wide_trace_id=(
                        f"{request.trace_id}:wide"
                    ),
                ),
                status="pager_error",
                selected_capability=None,
                policy_reasons=[
                    str(exc)
                ],
                mission_id=mission_id,
            )
            raise RuntimeError(
                "Capability pager failed: "
                f"{exc}"
            ) from exc

        chosen, reasons = (
            self._apply_policy(
                suggestion,
                capabilities,
                policy
                or CapabilityPolicy(),
            )
        )
        status = (
            "resolved"
            if chosen is not None
            else "unresolved"
        )
        resolution = (
            self._record_resolution(
                request=request,
                suggestion=suggestion,
                status=status,
                selected_capability=(
                    chosen.id
                    if chosen
                    else None
                ),
                policy_reasons=reasons,
                mission_id=mission_id,
            )
        )

        binding = None
        if chosen is not None:
            binding = self._bind(
                worker_id=worker_id,
                capability=chosen,
                resolution_id=(
                    resolution["id"]
                ),
                mission_id=mission_id,
            )

        return {
            "request": request.to_dict(),
            "suggestion": (
                suggestion.to_dict()
            ),
            "resolution": resolution,
            "binding": binding,
        }

    def list_bindings(
        self,
        worker_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.bindings_dir.exists():
            return []
        bindings = [
            self._read_json(path)
            for path in sorted(
                self.bindings_dir.glob(
                    "*.json"
                )
            )
        ]
        if worker_id is None:
            return bindings
        return [
            binding
            for binding in bindings
            if binding[
                "worker_id"
            ] == worker_id
        ]

    def get_bound_capabilities(
        self,
        worker_id: str,
    ) -> list[CapabilityDescriptor]:
        by_id = {
            capability.id: capability
            for capability
            in self.list_capabilities()
        }
        result: list[
            CapabilityDescriptor
        ] = []
        for binding in self.list_bindings(
            worker_id
        ):
            capability = by_id.get(
                binding[
                    "capability_id"
                ]
            )
            if capability is not None:
                result.append(
                    capability
                )
        return result

    def summary(
        self,
    ) -> dict[str, int]:
        resolutions = (
            list(
                self.resolutions_dir.glob(
                    "*.json"
                )
            )
            if self.resolutions_dir.exists()
            else []
        )
        return {
            "registry_count": len(
                self.list_capabilities()
            ),
            "resolution_count": len(
                resolutions
            ),
            "binding_count": len(
                self.list_bindings()
            ),
        }

    def _record_resolution(
        self,
        *,
        request: CapabilityRequest,
        suggestion: CapabilitySuggestion,
        status: str,
        selected_capability: str | None,
        policy_reasons: list[str],
        mission_id: str | None,
    ) -> dict[str, Any]:
        resolution = (
            CapabilityResolution(
                id=(
                    "capres_"
                    f"{uuid4().hex[:12]}"
                ),
                request_id=request.id,
                worker_id=request.worker_id,
                status=status,
                selected_capability=(
                    selected_capability
                ),
                suggestion=suggestion,
                policy_reasons=(
                    policy_reasons
                ),
            )
        )
        payload = resolution.to_dict()
        self._write_json(
            self.resolutions_dir
            / f"{resolution.id}.json",
            payload,
        )
        self.store.append_event(
            Event(
                type=(
                    "capability.resolved"
                    if status == "resolved"
                    else "capability.rejected"
                ),
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "resolution_id": (
                        resolution.id
                    ),
                    "request_id": (
                        request.id
                    ),
                    "worker_id": (
                        request.worker_id
                    ),
                    "status": status,
                    "selected_capability": (
                        selected_capability
                    ),
                    "policy_reasons": (
                        policy_reasons
                    ),
                },
            )
        )
        return payload

    def _bind(
        self,
        *,
        worker_id: str,
        capability: CapabilityDescriptor,
        resolution_id: str,
        mission_id: str | None,
    ) -> dict[str, Any]:
        for existing in self.list_bindings(
            worker_id
        ):
            if (
                existing[
                    "capability_id"
                ]
                == capability.id
                and existing["status"]
                == "bound"
            ):
                return existing

        binding = CapabilityBinding(
            id=(
                f"capbind_"
                f"{uuid4().hex[:12]}"
            ),
            worker_id=worker_id,
            capability_id=(
                capability.id
            ),
            resolution_id=resolution_id,
        )
        payload = binding.to_dict()
        self._write_json(
            self.bindings_dir
            / f"{binding.id}.json",
            payload,
        )
        self.store.append_event(
            Event(
                type="capability.bound",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "binding_id": (
                        binding.id
                    ),
                    "worker_id": worker_id,
                    "capability_id": (
                        capability.id
                    ),
                    "resolution_id": (
                        resolution_id
                    ),
                },
            )
        )
        return payload

    def _apply_policy(
        self,
        suggestion: CapabilitySuggestion,
        capabilities: Sequence[
            CapabilityDescriptor
        ],
        policy: CapabilityPolicy,
    ) -> tuple[
        CapabilityDescriptor | None,
        list[str],
    ]:
        if (
            suggestion.advisory_only
            is not True
        ):
            return (
                None,
                [
                    "suggestion_not_advisory"
                ],
            )

        if (
            suggestion.confidence
            < policy.min_confidence
        ):
            return (
                None,
                [
                    "confidence_below_policy"
                ],
            )

        by_id = {
            capability.id: capability
            for capability
            in capabilities
        }
        ordered = [
            capability_id
            for capability_id
            in [
                suggestion.suggested_capability,
                *suggestion.alternatives,
            ]
            if capability_id
        ]

        rejected: list[str] = []
        for index, capability_id in enumerate(
            ordered
        ):
            capability = by_id.get(
                capability_id
            )
            if capability is None:
                rejected.append(
                    f"{capability_id}:"
                    "unknown_capability"
                )
                continue

            reasons = (
                self._capability_policy_reasons(
                    capability,
                    by_id,
                    policy,
                )
            )
            if reasons:
                rejected.extend(
                    f"{capability.id}:{reason}"
                    for reason in reasons
                )
                continue

            selected_reason = (
                "selected_primary"
                if index == 0
                else "selected_alternative"
            )
            return (
                capability,
                [
                    selected_reason,
                    *rejected,
                ],
            )

        return (
            None,
            rejected
            or [
                "no_suggested_capability"
            ],
        )

    @staticmethod
    def _capability_policy_reasons(
        capability: CapabilityDescriptor,
        by_id: dict[
            str, CapabilityDescriptor
        ],
        policy: CapabilityPolicy,
    ) -> list[str]:
        reasons: list[str] = []

        if (
            capability.availability
            != "available"
        ):
            reasons.append(
                "not_available"
            )

        cost = capability.cost_class
        if cost is None:
            reasons.append(
                "cost_unknown"
            )
        elif (
            _COST_RANK[cost]
            > _COST_RANK[
                policy.max_cost_class
            ]
        ):
            reasons.append(
                "cost_exceeds_policy"
            )

        denied = (
            set(
                capability.risk_tags
            )
            & set(
                policy.denied_risk_tags
            )
        )
        if denied:
            reasons.append(
                "denied_risk:"
                + ",".join(
                    sorted(denied)
                )
            )

        missing = [
            prerequisite
            for prerequisite
            in capability.prerequisites
            if (
                prerequisite
                not in by_id
                or by_id[
                    prerequisite
                ].availability
                != "available"
            )
        ]
        if missing:
            reasons.append(
                "missing_prerequisite:"
                + ",".join(missing)
            )

        return reasons

    @staticmethod
    def _validate_descriptor(
        capability: CapabilityDescriptor,
    ) -> None:
        if not _SAFE_ID.fullmatch(
            capability.id
        ):
            raise RuntimeError(
                "Invalid capability id: "
                f"{capability.id}"
            )
        if (
            capability.kind
            not in _CAPABILITY_KINDS
        ):
            raise RuntimeError(
                "Unsupported capability kind: "
                f"{capability.kind}"
            )
        if (
            capability.availability
            not in _AVAILABILITY
        ):
            raise RuntimeError(
                "Unsupported availability: "
                f"{capability.availability}"
            )
        if (
            capability.cost_class
            is not None
            and capability.cost_class
            not in _COST_CLASSES
        ):
            raise RuntimeError(
                "Unsupported cost class: "
                f"{capability.cost_class}"
            )
        if not capability.name.strip():
            raise RuntimeError(
                "Capability name must "
                "not be empty"
            )
        if not (
            capability.short_description.strip()
        ):
            raise RuntimeError(
                "Capability short description "
                "must not be empty"
            )

    @staticmethod
    def _write_json(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
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

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )


def parse_descriptor(
    raw: object,
) -> CapabilityDescriptor:
    if not isinstance(raw, dict):
        raise RuntimeError(
            "Capability descriptor must "
            "be an object"
        )

    return CapabilityDescriptor(
        id=str(raw["id"]),
        kind=str(raw["kind"]),
        name=str(raw["name"]),
        short_description=str(
            raw.get(
                "short_description",
                raw.get(
                    "shortDescription",
                    "",
                ),
            )
        ),
        availability=str(
            raw["availability"]
        ),
        full_description=(
            str(
                raw.get(
                    "full_description",
                    raw.get(
                        "fullDescription",
                    ),
                )
            )
            if raw.get(
                "full_description",
                raw.get(
                    "fullDescription",
                ),
            )
            is not None
            else None
        ),
        instructions_ref=(
            str(
                raw.get(
                    "instructions_ref",
                    raw.get(
                        "instructionsRef",
                    ),
                )
            )
            if raw.get(
                "instructions_ref",
                raw.get(
                    "instructionsRef",
                ),
            )
            is not None
            else None
        ),
        prerequisites=[
            str(item)
            for item in raw.get(
                "prerequisites",
                [],
            )
        ],
        risk_tags=[
            str(item)
            for item in raw.get(
                "risk_tags",
                raw.get(
                    "riskTags",
                    [],
                ),
            )
        ],
        cost_class=(
            str(
                raw.get(
                    "cost_class",
                    raw.get(
                        "costClass",
                    ),
                )
            )
            if raw.get(
                "cost_class",
                raw.get(
                    "costClass",
                ),
            )
            is not None
            else None
        ),
        metadata=dict(
            raw.get(
                "metadata",
                {},
            )
        ),
    )


def descriptor_to_system_one(
    capability: CapabilityDescriptor,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": capability.id,
        "kind": capability.kind,
        "name": capability.name,
        "shortDescription": (
            capability.short_description
        ),
        "availability": (
            capability.availability
        ),
    }
    if capability.full_description:
        payload["fullDescription"] = (
            capability.full_description
        )
    if capability.instructions_ref:
        payload["instructionsRef"] = (
            capability.instructions_ref
        )
    if capability.prerequisites:
        payload["prerequisites"] = (
            capability.prerequisites
        )
    if capability.risk_tags:
        payload["riskTags"] = (
            capability.risk_tags
        )
    if capability.cost_class:
        payload["costClass"] = (
            capability.cost_class
        )
    if capability.metadata:
        payload["metadata"] = (
            capability.metadata
        )
    return payload


def parse_system_one_suggestion(
    raw: object,
) -> CapabilitySuggestion:
    if not isinstance(raw, dict):
        raise RuntimeError(
            "CapabilitySuggestion must "
            "be an object"
        )

    suggested = raw.get(
        "suggestedCapability",
        raw.get(
            "suggested_capability",
        ),
    )
    confidence = raw.get(
        "confidence"
    )
    advisory = raw.get(
        "advisoryOnly",
        raw.get(
            "advisory_only",
        ),
    )
    wide = raw.get(
        "wideTraceId",
        raw.get(
            "wide_trace_id",
        ),
    )

    if not isinstance(
        confidence,
        (int, float),
    ) or not 0 <= float(
        confidence
    ) <= 1:
        raise RuntimeError(
            "CapabilitySuggestion confidence "
            "must be within [0, 1]"
        )
    if advisory is not True:
        raise RuntimeError(
            "System One suggestion must be "
            "advisoryOnly=true"
        )
    if not isinstance(
        wide,
        str,
    ) or not wide:
        raise RuntimeError(
            "CapabilitySuggestion requires "
            "wideTraceId"
        )

    alternatives = raw.get(
        "alternatives",
        [],
    )
    reasons = raw.get(
        "reasonCodes",
        raw.get(
            "reason_codes",
            [],
        ),
    )
    if not isinstance(
        alternatives,
        list,
    ) or not isinstance(
        reasons,
        list,
    ):
        raise RuntimeError(
            "CapabilitySuggestion alternatives "
            "and reasonCodes must be lists"
        )

    deep = raw.get(
        "deepTraceId",
        raw.get(
            "deep_trace_id",
        ),
    )

    return CapabilitySuggestion(
        suggested_capability=(
            str(suggested)
            if suggested is not None
            else None
        ),
        confidence=float(
            confidence
        ),
        alternatives=[
            str(item)
            for item in alternatives
        ],
        reason_codes=[
            str(item)
            for item in reasons
        ],
        advisory_only=True,
        wide_trace_id=wide,
        deep_trace_id=(
            str(deep)
            if deep is not None
            else None
        ),
    )
