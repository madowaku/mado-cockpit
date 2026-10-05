import json
from pathlib import Path

import pytest

from mado_cockpit.plugin_registry import PluginCapabilityRegistry


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "plugins"
    / "mpc-m0.0.json"
)


def test_loads_madowaku_plugin_registry_and_summarizes_layers():
    registry = PluginCapabilityRegistry.load(FIXTURE)
    summary = registry.summary()

    assert summary["total"] == 12
    assert summary["by_status"]["active"] == 10
    assert summary["by_status"]["candidate"] == 2
    assert summary["compiled_active"] == 10
    assert summary["by_layer"]["build"] >= 4
    assert summary["by_layer"]["visual"] >= 4


def test_compiles_only_active_plugins_by_default():
    registry = PluginCapabilityRegistry.load(FIXTURE)
    ids = [item.id for item in registry.compile_descriptors()]

    assert "github" in ids
    assert "context7" in ids
    assert "posthog" in ids
    assert "firecrawl" not in ids
    assert "google-calendar" not in ids


def test_candidate_plugins_can_be_compiled_explicitly():
    registry = PluginCapabilityRegistry.load(FIXTURE)
    ids = [
        item.id
        for item in registry.compile_descriptors(
            include_candidates=True
        )
    ]

    assert "firecrawl" in ids
    assert "google-calendar" in ids


def test_compiled_descriptor_preserves_plugin_provenance():
    registry = PluginCapabilityRegistry.load(FIXTURE)
    descriptor = next(
        item
        for item in registry.compile_descriptors()
        if item.id == "context7"
    )

    assert descriptor.kind == "plugin"
    assert descriptor.availability == "available"
    assert descriptor.metadata["registry"] == "mpc-m0.0"
    assert descriptor.metadata["plugin_ref"] == "context7"
    assert descriptor.metadata["provider"] == "Context7"
    assert descriptor.metadata["layers"] == ["build", "research"]
    assert descriptor.metadata["permissions"] == ["read"]
    assert "mado-cockpit" in descriptor.metadata["consumers"]
    assert "official-docs" in descriptor.metadata["fallbacks"]
    assert "documentation_source" in descriptor.metadata["evidence"]


def test_registry_supports_layer_and_status_views():
    registry = PluginCapabilityRegistry.load(FIXTURE)

    assert [item.id for item in registry.list(layer="growth")] == [
        "posthog"
    ]
    assert {
        item.id for item in registry.list(status="candidate")
    } == {"firecrawl", "google-calendar"}


def test_duplicate_ids_fail_closed():
    payload = {
        "plugins": [
            {
                "id": "same",
                "pluginRef": "one",
                "provider": "One",
                "displayName": "One",
                "capability": "Read one.",
                "layers": ["research"],
                "status": "active",
                "availability": "available",
                "costClass": "free",
            },
            {
                "id": "same",
                "pluginRef": "two",
                "provider": "Two",
                "displayName": "Two",
                "capability": "Read two.",
                "layers": ["research"],
                "status": "active",
                "availability": "available",
                "costClass": "free",
            },
        ]
    }

    with pytest.raises(
        RuntimeError,
        match="Duplicate plugin capability id",
    ):
        PluginCapabilityRegistry.from_payload(payload)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("layers", ["unknown"], "invalid layers"),
        ("status", "mystery", "invalid status"),
        ("availability", "maybe", "invalid availability"),
        ("costClass", "unbounded", "invalid cost class"),
        ("permissions", ["root"], "invalid permissions"),
    ],
)
def test_invalid_contract_values_are_rejected(field, value, error):
    entry = {
        "id": "fixture",
        "pluginRef": "fixture",
        "provider": "Fixture",
        "displayName": "Fixture",
        "capability": "Fixture capability.",
        "layers": ["research"],
        "status": "active",
        "availability": "available",
        "costClass": "free",
        "permissions": ["read"],
    }
    entry[field] = value

    with pytest.raises(RuntimeError, match=error):
        PluginCapabilityRegistry.from_payload({"plugins": [entry]})


def test_fixture_is_plain_json_for_cross_runtime_use():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert isinstance(raw["plugins"], list)
    assert raw["plugins"][0]["id"] == "github"
