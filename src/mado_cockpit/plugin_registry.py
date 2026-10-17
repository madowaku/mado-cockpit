from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .models import CapabilityDescriptor


PLUGIN_LAYERS = {
    "build", "research", "visual", "qa", "growth", "publish", "operations",
}
PLUGIN_STATUSES = {"active", "candidate", "disabled"}
PLUGIN_AVAILABILITY = {"available", "unavailable", "unknown"}
PLUGIN_COST_CLASSES = {"free", "low", "medium", "high"}
PLUGIN_PERMISSIONS = {"read", "write", "external_action"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(slots=True)
class PluginCapabilityEntry:
    id: str
    plugin_ref: str
    provider: str
    display_name: str
    capability: str
    layers: list[str]
    status: str
    availability: str
    cost_class: str
    permissions: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
    consumers: list[str] = field(default_factory=list)
    fallbacks: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    instructions_ref: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PluginCapabilityEntry":
        def value(snake: str, camel: str | None = None, default: Any = None) -> Any:
            if snake in raw:
                return raw[snake]
            if camel and camel in raw:
                return raw[camel]
            return default

        entry = cls(
            id=str(value("id", default="")).strip(),
            plugin_ref=str(value("plugin_ref", "pluginRef", "")).strip(),
            provider=str(value("provider", default="")).strip(),
            display_name=str(value("display_name", "displayName", "")).strip(),
            capability=str(value("capability", default="")).strip(),
            layers=list(value("layers", default=[]) or []),
            status=str(value("status", default="")).strip(),
            availability=str(value("availability", default="")).strip(),
            cost_class=str(value("cost_class", "costClass", "")).strip(),
            permissions=list(value("permissions", default=[]) or []),
            prerequisites=list(value("prerequisites", default=[]) or []),
            risk_tags=list(value("risk_tags", "riskTags", []) or []),
            consumers=list(value("consumers", default=[]) or []),
            fallbacks=list(value("fallbacks", default=[]) or []),
            evidence=list(value("evidence", default=[]) or []),
            instructions_ref=value("instructions_ref", "instructionsRef"),
            metadata=dict(value("metadata", default={}) or {}),
        )
        entry.validate()
        return entry

    def validate(self) -> None:
        if not self.id or not _SAFE_ID.fullmatch(self.id):
            raise RuntimeError(f"Invalid plugin capability id: {self.id!r}")
        required = {
            "plugin_ref": self.plugin_ref,
            "provider": self.provider,
            "display_name": self.display_name,
            "capability": self.capability,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError("Plugin capability entry is missing: " + ", ".join(missing))
        if not self.layers:
            raise RuntimeError(f"Plugin capability {self.id} needs at least one layer")
        invalid_layers = sorted(set(self.layers) - PLUGIN_LAYERS)
        if invalid_layers:
            raise RuntimeError(
                f"Plugin capability {self.id} has invalid layers: " + ", ".join(invalid_layers)
            )
        if self.status not in PLUGIN_STATUSES:
            raise RuntimeError(
                f"Plugin capability {self.id} has invalid status: {self.status}"
            )
        if self.availability not in PLUGIN_AVAILABILITY:
            raise RuntimeError(
                f"Plugin capability {self.id} has invalid availability: {self.availability}"
            )
        if self.cost_class not in PLUGIN_COST_CLASSES:
            raise RuntimeError(
                f"Plugin capability {self.id} has invalid cost class: {self.cost_class}"
            )
        invalid_permissions = sorted(set(self.permissions) - PLUGIN_PERMISSIONS)
        if invalid_permissions:
            raise RuntimeError(
                f"Plugin capability {self.id} has invalid permissions: "
                + ", ".join(invalid_permissions)
            )

    def to_descriptor(self) -> CapabilityDescriptor:
        metadata = {
            **self.metadata,
            "registry": "mpc-m0.0",
            "plugin_ref": self.plugin_ref,
            "provider": self.provider,
            "layers": list(self.layers),
            "plugin_status": self.status,
            "permissions": list(self.permissions),
            "consumers": list(self.consumers),
            "fallbacks": list(self.fallbacks),
            "evidence": list(self.evidence),
        }
        return CapabilityDescriptor(
            id=self.id,
            kind="plugin",
            name=self.display_name,
            short_description=self.capability,
            full_description=(
                f"{self.display_name} plugin capability provided by {self.provider}."
            ),
            instructions_ref=self.instructions_ref,
            availability=self.availability,
            prerequisites=list(self.prerequisites),
            risk_tags=list(self.risk_tags),
            cost_class=self.cost_class,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plugin_ref": self.plugin_ref,
            "provider": self.provider,
            "display_name": self.display_name,
            "capability": self.capability,
            "layers": list(self.layers),
            "status": self.status,
            "availability": self.availability,
            "cost_class": self.cost_class,
            "permissions": list(self.permissions),
            "prerequisites": list(self.prerequisites),
            "risk_tags": list(self.risk_tags),
            "consumers": list(self.consumers),
            "fallbacks": list(self.fallbacks),
            "evidence": list(self.evidence),
            "instructions_ref": self.instructions_ref,
            "metadata": dict(self.metadata),
        }


class PluginCapabilityRegistry:
    def __init__(self, entries: Iterable[PluginCapabilityEntry]) -> None:
        self.entries = list(entries)
        self._validate_unique_ids()

    @classmethod
    def load(cls, path: Path | str) -> "PluginCapabilityRegistry":
        source = Path(path)
        raw = json.loads(source.read_text(encoding="utf-8"))
        return cls.from_payload(raw)

    @classmethod
    def from_payload(cls, raw: Any) -> "PluginCapabilityRegistry":
        values = raw.get("plugins") if isinstance(raw, dict) else raw
        if not isinstance(values, list):
            raise RuntimeError('Plugin registry must be a JSON list or {"plugins": [...]}')
        entries = []
        for item in values:
            if not isinstance(item, dict):
                raise RuntimeError("Every plugin registry entry must be an object")
            entries.append(PluginCapabilityEntry.from_dict(item))
        return cls(entries)

    def _validate_unique_ids(self) -> None:
        seen: set[str] = set()
        for entry in self.entries:
            if entry.id in seen:
                raise RuntimeError(f"Duplicate plugin capability id: {entry.id}")
            seen.add(entry.id)

    def list(
        self,
        *,
        status: str | None = None,
        layer: str | None = None,
    ) -> list[PluginCapabilityEntry]:
        if status is not None and status not in PLUGIN_STATUSES:
            raise RuntimeError(f"Unknown plugin status filter: {status}")
        if layer is not None and layer not in PLUGIN_LAYERS:
            raise RuntimeError(f"Unknown plugin layer filter: {layer}")
        result = self.entries
        if status is not None:
            result = [item for item in result if item.status == status]
        if layer is not None:
            result = [item for item in result if layer in item.layers]
        return list(result)

    def compile_descriptors(
        self,
        *,
        include_candidates: bool = False,
    ) -> list[CapabilityDescriptor]:
        allowed_statuses = {"active"}
        if include_candidates:
            allowed_statuses.add("candidate")
        return [
            entry.to_descriptor()
            for entry in self.entries
            if entry.status in allowed_statuses
            and entry.availability != "unavailable"
        ]

    def summary(self) -> dict[str, Any]:
        by_status = {
            status: len([entry for entry in self.entries if entry.status == status])
            for status in sorted(PLUGIN_STATUSES)
        }
        by_layer = {
            layer: len([entry for entry in self.entries if layer in entry.layers])
            for layer in sorted(PLUGIN_LAYERS)
        }
        return {
            "total": len(self.entries),
            "by_status": by_status,
            "by_layer": by_layer,
            "compiled_active": len(self.compile_descriptors()),
        }
