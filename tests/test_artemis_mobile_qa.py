import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.artemis_mobile_qa import (
    MobileQAGateError, android_doctor, codex_mcp_config, intake_mobile_evidence,
)


def session(tmp_path, *, source="synthetic_fixture", status="passed"):
    root = tmp_path / "input"
    root.mkdir()
    (root / "frame.png").write_bytes(b"fake-but-nonempty-png")
    (root / "manifest.json").write_text(json.dumps({
        "schema_version": 1, "run_id": "case-1",
        "device_serial": "emulator-5554", "source": source,
        "status": status, "trace_id": "trace-1",
        "steps": [{"action": "open screen", "result": status}],
        "media": [{"path": "frame.png", "kind": "screenshot"}],
    }), encoding="utf-8")
    return root


def test_fixture_never_passes_live_gate(tmp_path):
    report = intake_mobile_evidence(session(tmp_path), tmp_path / "out")
    assert report["gate"] == "blocked"
    assert report["mgsf_evidence_class"] == "synthetic_capture_fixture"
    assert len(report["media"][0]["sha256"]) == 64


def test_live_emulator_evidence_passes(tmp_path):
    report = intake_mobile_evidence(
        session(tmp_path, source="artemis_live"), tmp_path / "out"
    )
    assert report["gate"] == "passed"
    assert report["live_qualified"] is True
    assert report["mgsf_evidence_class"] == "recorded_gameplay_capture"


def test_failed_step_never_passes(tmp_path):
    root = session(tmp_path, source="artemis_live", status="failed")
    assert intake_mobile_evidence(root, tmp_path / "out")["gate"] == "failed"


def test_path_traversal_rejected(tmp_path):
    root = session(tmp_path)
    data = json.loads((root / "manifest.json").read_text())
    data["media"][0]["path"] = "../elsewhere.png"
    (root / "manifest.json").write_text(json.dumps(data))
    with pytest.raises(MobileQAGateError):
        intake_mobile_evidence(root, tmp_path / "out")


def test_duplicate_run_rejected(tmp_path):
    root = session(tmp_path)
    intake_mobile_evidence(root, tmp_path / "out")
    with pytest.raises(MobileQAGateError):
        intake_mobile_evidence(root, tmp_path / "out")


def test_windows_codex_config_is_generated_not_installed():
    config = codex_mcp_config("C:/artemis")
    assert "[mcp_servers.artemis]" in config
    assert 'args = ["-m", "mcp_server"]' in config
    assert "PYTHONPATH" in config


def test_adb_offline_is_blocked(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        args=["adb"], returncode=0, stdout="List of devices attached\n"
    ))
    assert android_doctor()["status"] == "blocked"


def test_adb_emulator_ready(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        args=["adb"], returncode=0,
        stdout="List of devices attached\nemulator-5554 device product:sdk\n"
    ))
    assert android_doctor()["status"] == "ready"
