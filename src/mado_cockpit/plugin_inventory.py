from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .plugin_registry import PluginCapabilityRegistry


_PLATFORM_AVAILABILITY = {
    "ENABLED": "available",
    "DISABLED": "unavailable",
    "DISABLED_BY_ADMIN": "unavailable",
    "UNAVAILABLE": "unavailable",
}


@dataclass(slots=True)
class ObservedPlugin:
    plugin_ref: str
    display_name: str
    description: str = ""
    plugin_id: str | None = None
    installed: bool | None = None
    platform_status: str = "UNKNOWN"
    installation_policy: str = "UNKNOWN"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ObservedPlugin":
        plugin_ref = str(
            raw.get("plugin_ref")
            or raw.get("pluginRef")
            or raw.get("name")
            or ""
        ).strip()
        display_name = str(
            raw.get("display_name")
            or raw.get("displayName")
            or plugin_ref
        ).strip()
        if not plugin_ref:
            raise RuntimeError(
                "Observed plugin is missing plugin_ref/name"
            )
        if not display_name:
            raise RuntimeError(
                f"Observed plugin {plugin_ref} is missing display name"
            )

        installed = raw.get("installed")
        if installed is not None and not isinstance(installed, bool):
            raise RuntimeError(
                f"Observed plugin {plugin_ref} installed must be boolean"
            )

        return cls(
            plugin_ref=plugin_ref,
            display_name=display_name,
            description=str(raw.get("description") or "").strip(),
            plugin_id=(
                str(raw.get("id")).strip()
                if raw.get("id") is not None
                else None
            ),
            installed=installed,
            platform_status=str(
                raw.get("status")
                or raw.get("platform_status")
                or "UNKNOWN"
            ).strip().upper(),
            installation_policy=str(
                raw.get("installation_policy")
                or raw.get("installationPolicy")
                or "UNKNOWN"
            ).strip().upper(),
            metadata=dict(raw.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PluginInventorySnapshot:
    plugins: list[ObservedPlugin]
    source: str = "chatgpt_plugin_inventory"
    complete: bool = False
    observed_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(
        cls,
        path: Path | str,
    ) -> "PluginInventorySnapshot":
        raw = json.loads(
            Path(path).read_text(encoding="utf-8")
        )
        return cls.from_payload(raw)

    @classmethod
    def from_payload(
        cls,
        raw: Any,
    ) -> "PluginInventorySnapshot":
        if isinstance(raw, list):
            values = raw
            source = "chatgpt_plugin_inventory"
            complete = False
            observed_at = None
            metadata: dict[str, Any] = {}
        elif isinstance(raw, dict):
            values = raw.get("plugins")
            source = str(
                raw.get("source")
                or "chatgpt_plugin_inventory"
            )
            complete = bool(raw.get("complete", False))
            observed_at = raw.get("observed_at")
            metadata = dict(raw.get("metadata") or {})
        else:
            values = None
            source = "chatgpt_plugin_inventory"
            complete = False
            observed_at = None
            metadata = {}

        if not isinstance(values, list):
            raise RuntimeError(
                "Plugin inventory snapshot must be a JSON list "
                'or {"plugins": [...]}'
            )

        plugins = []
        seen: set[str] = set()
        for item in values:
            if not isinstance(item, dict):
                raise RuntimeError(
                    "Every observed plugin must be an object"
                )
            plugin = ObservedPlugin.from_dict(item)
            if plugin.plugin_ref in seen:
                raise RuntimeError(
                    "Duplicate observed plugin ref: "
                    f"{plugin.plugin_ref}"
                )
            seen.add(plugin.plugin_ref)
            plugins.append(plugin)

        return cls(
            plugins=plugins,
            source=source,
            complete=complete,
            observed_at=(
                str(observed_at)
                if observed_at is not None
                else None
            ),
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "complete": self.complete,
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata),
            "plugins": [
                plugin.to_dict()
                for plugin in self.plugins
            ],
        }


class PluginInventoryScanner:
    def scan(
        self,
        registry: PluginCapabilityRegistry,
        snapshot: PluginInventorySnapshot,
    ) -> dict[str, Any]:
        registry_by_ref = {
            entry.plugin_ref: entry
            for entry in registry.entries
        }
        observed_by_ref = {
            plugin.plugin_ref: plugin
            for plugin in snapshot.plugins
        }

        new: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        unchanged: list[dict[str, Any]] = []

        for plugin_ref in sorted(observed_by_ref):
            observed = observed_by_ref[plugin_ref]
            registered = registry_by_ref.get(plugin_ref)
            if registered is None:
                new.append(
                    self._candidate_proposal(observed)
                )
                continue

            reasons = self._change_reasons(
                registered,
                observed,
            )
            item = {
                "plugin_ref": plugin_ref,
                "registry_id": registered.id,
                "display_name": observed.display_name,
                "installed": observed.installed,
                "platform_status": observed.platform_status,
            }
            if reasons:
                item["reasons"] = reasons
                item["registry_status"] = registered.status
                changed.append(item)
            else:
                unchanged.append(item)

        missing: list[dict[str, Any]] = []
        warnings: list[str] = []
        if snapshot.complete:
            for plugin_ref in sorted(registry_by_ref):
                if plugin_ref not in observed_by_ref:
                    entry = registry_by_ref[plugin_ref]
                    missing.append(
                        {
                            "plugin_ref": plugin_ref,
                            "registry_id": entry.id,
                            "registry_status": entry.status,
                        }
                    )
        else:
            warnings.append(
                "snapshot_incomplete_missing_not_evaluated"
            )

        return {
            "source": snapshot.source,
            "snapshot_complete": snapshot.complete,
            "observed_at": snapshot.observed_at,
            "summary": {
                "observed": len(snapshot.plugins),
                "registered": len(registry.entries),
                "new": len(new),
                "changed": len(changed),
                "missing": len(missing),
                "unchanged": len(unchanged),
            },
            "new": new,
            "changed": changed,
            "missing": missing,
            "unchanged": unchanged,
            "warnings": warnings,
        }

    def _change_reasons(
        self,
        registered,
        observed: ObservedPlugin,
    ) -> list[str]:
        reasons: list[str] = []

        if (
            registered.display_name.strip().casefold()
            != observed.display_name.strip().casefold()
        ):
            reasons.append("display_name_changed")

        observed_availability = _PLATFORM_AVAILABILITY.get(
            observed.platform_status
        )
        if (
            observed_availability is not None
            and registered.availability
            != observed_availability
        ):
            reasons.append("platform_availability_changed")

        if (
            registered.status == "active"
            and observed.installed is False
        ):
            reasons.append("active_but_not_installed")

        if (
            registered.status == "candidate"
            and observed.installed is True
        ):
            reasons.append("candidate_now_installed")

        return reasons

    def _candidate_proposal(
        self,
        observed: ObservedPlugin,
    ) -> dict[str, Any]:
        return {
            "plugin_ref": observed.plugin_ref,
            "plugin_id": observed.plugin_id,
            "display_name": observed.display_name,
            "description": observed.description,
            "installed": observed.installed,
            "platform_status": observed.platform_status,
            "installation_policy": (
                observed.installation_policy
            ),
            "suggested_status": "candidate",
            "auto_activate": False,
            "requires_enrichment": [
                "provider",
                "capability",
                "layers",
                "cost_class",
                "permissions",
                "risk_tags",
                "consumers",
                "fallbacks",
                "evidence",
            ],
        }


class PluginRegistrySyncAdapter:
    def __init__(
        self,
        scanner: PluginInventoryScanner | None = None,
    ) -> None:
        self.scanner = scanner or PluginInventoryScanner()

    def build_plan(
        self,
        registry_path: Path | str,
        snapshot_path: Path | str,
    ) -> dict[str, Any]:
        registry = PluginCapabilityRegistry.load(
            registry_path
        )
        snapshot = PluginInventorySnapshot.load(
            snapshot_path
        )
        result = self.scanner.scan(
            registry,
            snapshot,
        )
        result["sync"] = {
            "registry_mutated": False,
            "candidate_proposals": len(
                result["new"]
            ),
            "promotion_required": any(
                item.get("suggested_status")
                == "candidate"
                for item in result["new"]
            ),
        }
        return result


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="mado-plugin-inventory"
    )
    parser.add_argument("registry")
    parser.add_argument("snapshot")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    plan = PluginRegistrySyncAdapter().build_plan(
        args.registry,
        args.snapshot,
    )
    payload = json.dumps(
        plan,
        ensure_ascii=False,
        indent=2,
    )
    if args.output:
        Path(args.output).write_text(
            payload + "\n",
            encoding="utf-8",
        )
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
