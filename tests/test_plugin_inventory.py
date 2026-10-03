import json
from pathlib import Path

import pytest

from mado_cockpit.plugin_inventory import (
    PluginInventoryScanner,
    PluginInventorySnapshot,
    PluginRegistrySyncAdapter,
    main,
)
from mado_cockpit.plugin_registry import (
    PluginCapabilityRegistry,
)


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = (
    ROOT
    / "fixtures"
    / "plugins"
    / "mpc-m0.0.json"
)
OBSERVED = (
    ROOT
    / "fixtures"
    / "plugins"
    / "mpc-m0.1-observed.json"
)


def test_search_derived_snapshot_detects_new_without_false_missing():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.load(OBSERVED)

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )

    assert result["summary"] == {
        "observed": 14,
        "registered": 12,
        "new": 2,
        "changed": 0,
        "missing": 0,
        "unchanged": 12,
    }
    assert {
        item["plugin_ref"]
        for item in result["new"]
    } == {"railway", "gitbook"}
    assert result["warnings"] == [
        "snapshot_incomplete_missing_not_evaluated"
    ]


def test_new_plugins_are_candidate_proposals_only():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.load(OBSERVED)

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )
    railway = next(
        item
        for item in result["new"]
        if item["plugin_ref"] == "railway"
    )

    assert railway["suggested_status"] == "candidate"
    assert railway["auto_activate"] is False
    assert "layers" in railway["requires_enrichment"]
    assert "risk_tags" in railway["requires_enrichment"]


def test_incomplete_snapshot_never_marks_registry_entries_missing():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.from_payload(
        {
            "complete": False,
            "plugins": [
                {
                    "name": "github",
                    "display_name": "GitHub",
                    "status": "ENABLED",
                    "installed": True,
                }
            ],
        }
    )

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )

    assert result["missing"] == []
    assert (
        "snapshot_incomplete_missing_not_evaluated"
        in result["warnings"]
    )


def test_complete_snapshot_can_mark_registry_entries_missing():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.from_payload(
        {
            "complete": True,
            "plugins": [
                {
                    "name": "github",
                    "display_name": "GitHub",
                    "status": "ENABLED",
                    "installed": True,
                }
            ],
        }
    )

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )

    missing_refs = {
        item["plugin_ref"]
        for item in result["missing"]
    }
    assert "context7" in missing_refs
    assert "github" not in missing_refs
    assert result["warnings"] == []


def test_active_plugin_not_installed_is_drift_not_auto_disable():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.from_payload(
        {
            "plugins": [
                {
                    "name": "github",
                    "display_name": "GitHub",
                    "status": "ENABLED",
                    "installed": False,
                }
            ],
        }
    )

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )

    assert result["changed"][0]["plugin_ref"] == "github"
    assert (
        "active_but_not_installed"
        in result["changed"][0]["reasons"]
    )
    assert registry.list(status="active")[0].status == "active"


def test_candidate_becoming_installed_requires_promotion():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.from_payload(
        {
            "plugins": [
                {
                    "name": "firecrawl",
                    "display_name": "Firecrawl",
                    "status": "ENABLED",
                    "installed": True,
                }
            ],
        }
    )

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )

    assert (
        "candidate_now_installed"
        in result["changed"][0]["reasons"]
    )
    firecrawl = next(
        item
        for item in registry.entries
        if item.id == "firecrawl"
    )
    assert firecrawl.status == "candidate"


def test_platform_disable_is_reported_as_availability_drift():
    registry = PluginCapabilityRegistry.load(REGISTRY)
    snapshot = PluginInventorySnapshot.from_payload(
        {
            "plugins": [
                {
                    "name": "github",
                    "display_name": "GitHub",
                    "status": "DISABLED_BY_ADMIN",
                    "installed": True,
                }
            ],
        }
    )

    result = PluginInventoryScanner().scan(
        registry,
        snapshot,
    )

    assert (
        "platform_availability_changed"
        in result["changed"][0]["reasons"]
    )


def test_duplicate_observed_refs_fail_closed():
    payload = {
        "plugins": [
            {
                "name": "same",
                "display_name": "Same",
            },
            {
                "name": "same",
                "display_name": "Same Again",
            },
        ]
    }

    with pytest.raises(
        RuntimeError,
        match="Duplicate observed plugin ref",
    ):
        PluginInventorySnapshot.from_payload(payload)


def test_sync_adapter_builds_plan_without_mutating_registry():
    before = REGISTRY.read_text(encoding="utf-8")

    plan = PluginRegistrySyncAdapter().build_plan(
        REGISTRY,
        OBSERVED,
    )

    after = REGISTRY.read_text(encoding="utf-8")
    assert before == after
    assert plan["sync"]["registry_mutated"] is False
    assert plan["sync"]["candidate_proposals"] == 2
    assert plan["sync"]["promotion_required"] is True


def test_cli_can_write_inspectable_sync_plan(tmp_path):
    output = tmp_path / "plugin-sync.json"

    exit_code = main(
        [
            str(REGISTRY),
            str(OBSERVED),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    plan = json.loads(
        output.read_text(encoding="utf-8")
    )
    assert plan["summary"]["new"] == 2
    assert plan["sync"]["registry_mutated"] is False
