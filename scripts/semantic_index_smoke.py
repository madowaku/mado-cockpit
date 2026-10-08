from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mado_cockpit.semantic_index import (
    HashEmbeddingBackend,
    SemanticEvidenceIndex,
)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mcc-m2.7-") as raw:
        root = Path(raw)
        (root / "src").mkdir()
        (root / "src" / "gameplay.py").write_text(
            "def capture_gameplay_evidence():\n"
            "    return 'godot frame test result'\n",
            encoding="utf-8",
        )

        evidence = (
            root
            / ".mado"
            / "cockpit"
            / "evidence"
            / "MCC-M2.7"
            / "evb_smoke"
            / "files"
        )
        evidence.mkdir(parents=True)
        (evidence / "godot-failure.txt").write_text(
            "Effekseer playback failed because the Godot executable was missing.\n",
            encoding="utf-8",
        )
        screenshot = evidence / "godot-error-console.png"
        screenshot.write_bytes(b"offline-screenshot-fixture")

        backend = HashEmbeddingBackend(dimension=128)
        index = SemanticEvidenceIndex(root, backend)

        text_first = index.build()
        visual_first = index.sync_images()
        visual_second = index.sync_images()
        text_second = index.build()

        code_hits = index.search(
            "gameplay evidence test",
            top_k=1,
            scope="repo",
            modality="text",
        )
        evidence_hits = index.search(
            "Effekseer missing executable",
            top_k=1,
            scope="evidence",
            modality="text",
        )
        visual_hits = index.search(
            "godot error console",
            top_k=1,
            scope="evidence",
            modality="image",
        )

        assert text_first["modality_counts"] == {"text": 2}
        assert visual_first["modality_counts"] == {
            "image": 1,
            "text": 2,
        }
        assert visual_second["embedded_count"] == 0
        assert visual_second["reused_count"] == 1
        assert text_second["modality_counts"] == {
            "image": 1,
            "text": 2,
        }
        assert code_hits[0]["source"] == "src/gameplay.py"
        assert evidence_hits[0]["source"].endswith("godot-failure.txt")
        assert visual_hits[0]["source"].endswith("godot-error-console.png")

        result = {
            "milestone": "MCC-M2.7",
            "status": "passed",
            "text_sync": text_first,
            "visual_sync": visual_first,
            "visual_resync": visual_second,
            "text_resync": text_second,
            "visual_top_hit": {
                "source": visual_hits[0]["source"],
                "score": visual_hits[0]["score"],
                "modality": visual_hits[0]["modality"],
            },
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
