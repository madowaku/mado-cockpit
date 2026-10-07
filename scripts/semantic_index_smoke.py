from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mado_cockpit.semantic_index import (
    HashEmbeddingBackend,
    SemanticEvidenceIndex,
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mcc-m2.6-") as raw:
        root = Path(raw)
        (root / "src").mkdir()
        (root / "src" / "gameplay.py").write_text(
            "def capture_gameplay_evidence():\n"
            "    return 'godot frame test result'\n",
            encoding="utf-8",
        )
        (root / "notes.md").write_text(
            "# Distribution\nmarketing revenue experiment\n",
            encoding="utf-8",
        )

        evidence = (
            root
            / ".mado"
            / "cockpit"
            / "evidence"
            / "MCC-M2.6"
            / "evb_smoke"
            / "files"
        )
        evidence.mkdir(parents=True)
        (evidence / "godot-failure.txt").write_text(
            "Effekseer playback failed because the Godot executable was missing.\n",
            encoding="utf-8",
        )

        backend = HashEmbeddingBackend(dimension=128)
        index = SemanticEvidenceIndex(root, backend)
        first = index.build()
        second = index.build()

        code_hits = index.search(
            "gameplay evidence test",
            top_k=1,
            scope="repo",
        )
        evidence_hits = index.search(
            "Effekseer missing executable",
            top_k=1,
            scope="evidence",
        )

        assert first["embedded_count"] == first["record_count"]
        assert second["embedded_count"] == 0
        assert second["reused_count"] == second["record_count"]
        assert code_hits[0]["source"] == "src/gameplay.py"
        assert evidence_hits[0]["source"].endswith("godot-failure.txt")

        result = {
            "milestone": "MCC-M2.6",
            "status": "passed",
            "first_build": first,
            "second_build": second,
            "repo_top_hit": {
                "source": code_hits[0]["source"],
                "score": code_hits[0]["score"],
            },
            "evidence_top_hit": {
                "source": evidence_hits[0]["source"],
                "score": evidence_hits[0]["score"],
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
