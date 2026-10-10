"""MCC-M2.7.1 local procedural-model dogfood; no API keys or inference."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from mado_cockpit.pydanticai_probe import run_local_provider_probe


def main() -> int:
    fixture_dir = Path(__file__).resolve().parents[1] / "fixtures/substrate"
    baseline = json.loads(
        (fixture_dir / "mcc-m2.7-agent-substrate-parity.json")
        .read_text(encoding="utf-8")
    )
    source = json.loads(
        (fixture_dir / "mcc-m2.7.1-pydanticai-testmodel.json")
        .read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory(prefix="mcc-m2.7.1-") as tmp:
        passing = run_local_provider_probe(baseline, source, root=tmp)
        altered = copy.deepcopy(source)
        altered["model_output"]["result"]["decision"] = "mutated"
        rejected = run_local_provider_probe(baseline, altered, root=tmp)
        receipts = len(list(
            (Path(tmp) / ".mado/cockpit/action_decisions").glob("*.json")
        ))
    result = {
        "schema": "mado.pydanticai-local-probe.smoke.v1",
        "real_pydanticai_agent": passing["agent"]["actual_agent_executed"],
        "local_model": "TestModel",
        "parity": passing["status"],
        "tampered": rejected["status"],
        "tool_admitted": passing["agent"]["admitted_tool_count"],
        "receipts": receipts,
        "paid_provider_requests": 0,
        "production_promotion_allowed": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if (
        passing["status"] == "pass"
        and rejected["status"] == "hold"
        and passing["agent"]["admitted_tool_count"] == 1
        and receipts == 6
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
