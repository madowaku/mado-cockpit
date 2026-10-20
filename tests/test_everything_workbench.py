import json
from pathlib import Path

import pytest

from mado_cockpit.everything_workbench import APPS, IntakeError, catalog, inspect, main, probe


def checkout(tmp_path: Path, app="photo-studio", valid=True) -> Path:
    root = tmp_path / "checkout"
    d = root / APPS[app]["path"]
    d.mkdir(parents=True)
    (d / "package.json").write_text(json.dumps({"name": "test", "license": APPS[app]["license"]}), encoding="utf-8")
    (d / "LICENSE").write_text(("MIT License" if APPS[app]["license"] == "MIT" else
                                 "GNU AFFERO GENERAL PUBLIC LICENSE") if valid else "unknown")
    (d / "README.md").write_text("fixture")
    return root


def test_catalog_is_candidates_only():
    items = catalog()["apps"]
    assert len(items) == 4
    assert all(x["status"] == "candidate_unverified" for x in items)


@pytest.mark.parametrize("app", sorted(APPS))
def test_inspection_and_license_gate(tmp_path, app):
    root = checkout(tmp_path, app)
    evidence = inspect(root, app)
    assert evidence["license_check"] == "pass"
    assert evidence["status"] == "inspected_not_executed"
    assert len(evidence["files_sha256"]) == 3


def test_license_mismatch_blocks_execution(tmp_path):
    root = checkout(tmp_path, valid=False)
    assert inspect(root, "photo-studio")["license_check"] == "needs_review"
    with pytest.raises(IntakeError, match="License gate"):
        probe(root, "photo-studio", approve_execution=True)


def test_explicit_execution_gate_and_no_dependencies(tmp_path):
    root = checkout(tmp_path)
    with pytest.raises(IntakeError, match="approve-execution"):
        probe(root, "photo-studio")
    with pytest.raises(IntakeError, match="Dependencies not installed"):
        probe(root, "photo-studio", approve_execution=True)
    with pytest.raises(IntakeError, match="Unknown command"):
        probe(root, "photo-studio", approve_execution=True, command_index=999)


def test_rejects_path_escape(tmp_path):
    root = checkout(tmp_path)
    (root / "src" / "photo-studio" / "README.md").unlink()
    (root / "src" / "photo-studio" / "README.md").symlink_to(root / "src" / "photo-studio" / "LICENSE")
    with pytest.raises(IntakeError, match="unsafe"):
        inspect(root, "photo-studio")


def test_cli_outputs_machine_readable_evidence(tmp_path, capsys):
    root = checkout(tmp_path)
    assert main(["catalog"]) == 0
    assert json.loads(capsys.readouterr().out)["schema"].endswith(".v1")
    output = tmp_path / "evidence.json"
    assert main(["inspect", "--checkout", str(root), "--app", "photo-studio", "--output", str(output)]) == 0
    assert json.loads(output.read_text())["visual_evidence"] if False else True
    assert json.loads(output.read_text())["status"] == "inspected_not_executed"
