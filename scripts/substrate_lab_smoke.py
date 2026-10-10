"""Zero-cost MCC-M2.7-AS dogfood: accepted replay plus tampered replay."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from mado_cockpit.substrate_lab import run_compatibility_fixture


def main() -> int:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures/substrate/mcc-m2.7-agent-substrate-parity.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="mcc-m2.7-as-") as directory:
        passing = run_compatibility_fixture(fixture, root=directory)
        tampered = copy.deepcopy(fixture)
        tampered["runs"][1]["outcome"]["result"]["decision"] = "different"
        held = run_compatibility_fixture(tampered, root=directory)
        receipt_dir = Path(directory) / ".mado/cockpit/action_decisions"
        receipts = len(list(receipt_dir.glob("*.json")))
    print(json.dumps({
        "schema": "mado.agent-substrate.smoke.v1",
        "offline_parity": passing["status"],
        "tampered_parity": held["status"],
        "audit_receipts": receipts,
        "real_external_adapters_used": False,
        "provider_cost_usd": 0,
    }, sort_keys=True, indent=2))
    return 0 if (passing["status"] == "pass"
                 and held["status"] == "hold"
                 and receipts == 4) else 1


if __name__ == "__main__":
    raise SystemExit(main())
