"""MCC-M2.6.4b: reference-only motion recipes and sampled temporal PNG QA.

No tools or third-party code are installed, fetched, executed, or published here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .component_foundry import ComponentGateError, _decode_png, _delta_png
from .motion_foundry import MotionFoundry, MotionFoundryError

SELECTION_SCHEMA = "mado.motion-recipe-selection.v1"
QA_SCHEMA = "mado.motion-temporal-qa.v1"
REVIEW_SCHEMA = "mado.motion-temporal-review.v1"
RECIPES = (
    {"id": "remotion-title-reveal", "title": "Title Reveal", "engine": "remotion",
     "source": "https://github.com/studio-yebisu/awesome-claude-motion-design-ja/tree/main/examples/remotion",
     "use_case": "editable branded typography and short launch videos"},
    {"id": "motion-reel-card-morph", "title": "Card Morph", "engine": "html-canvas",
     "source": "https://github.com/studio-yebisu/motion-reel/tree/main/examples",
     "use_case": "frame-addressable HTML Canvas UI transformations"},
    {"id": "hyperframes-promo", "title": "HTML Promo", "engine": "hyperframes",
     "source": "https://github.com/studio-yebisu/awesome-claude-motion-design-ja/tree/main/examples/hyperframes",
     "use_case": "browser-generated product clips"},
    {"id": "motion-canvas-explainer", "title": "Technical Explainer", "engine": "motion-canvas",
     "source": "https://github.com/studio-yebisu/awesome-claude-motion-design-ja/tree/main/examples/motion-canvas",
     "use_case": "technical explanations and diagrams"},
)


class MotionRecipeError(ValueError):
    pass


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.is_symlink():
        raise MotionRecipeError("Refusing symlink evidence")
    if path.exists():
        if _read_json(path) != payload:
            raise MotionRecipeError("Existing receipt differs from computed evidence")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as f:
        f.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MotionRecipeError("Receipt missing or is a symlink")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MotionRecipeError("Receipt is not valid JSON") from exc
    if not isinstance(data, dict):
        raise MotionRecipeError("Receipt must be a JSON object")
    return data


def _default_frames(scenes: list[dict[str, Any]]) -> list[int]:
    frames: set[int] = set()
    cursor = 0
    for scene in scenes:
        end = cursor + scene["duration_frames"]
        frames.update((cursor, min(end - 1, cursor + 12), (cursor + end - 1) // 2,
                       max(cursor, end - 13), end - 1))
        cursor = end
    return sorted(frames)


def _threshold(value: float, upper: float, label: str) -> float:
    if not math.isfinite(value) or not 0 <= value <= upper:
        raise MotionRecipeError(f"{label} must be finite within 0..{upper}")
    return value


class MotionRecipeRegistry:
    def __init__(self, root: Path | str = ".") -> None:
        self.foundry = MotionFoundry(root)
        self.base = self.foundry.store.base / "motion_recipe"

    @staticmethod
    def list_recipes(engine: str | None = None) -> list[dict[str, Any]]:
        return [{**recipe, "adapter": "m2.6.3-native" if recipe["engine"] == "remotion"
                 else "reference-only", "license_status": "operator_review_required"}
                for recipe in RECIPES if engine is None or recipe["engine"] == engine]

    def _selection(self, selection_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"recipe_[0-9a-f]{16}", selection_id):
            raise MotionRecipeError("Invalid selection ID")
        payload = _read_json(self.base / "selections" / f"{selection_id}.json")
        if payload.get("schema") != SELECTION_SCHEMA or payload.get("selection_id") != selection_id:
            raise MotionRecipeError("Selection schema mismatch")
        unsigned = dict(payload)
        unsigned.pop("selection_id")
        if "recipe_" + _sha(_canonical(unsigned))[:16] != selection_id:
            raise MotionRecipeError("Selection digest mismatch")
        recipe = next((r for r in RECIPES if r["id"] == payload.get("recipe_id")), None)
        if recipe is None or payload.get("recipe") != recipe:
            raise MotionRecipeError("Recipe provenance changed")
        project = Path(payload["project_path"])
        verified = self.foundry.verify(project)
        if verified["project_id"] != payload["project_id"] or _sha(
            (project / "manifest.json").read_bytes()) != payload["manifest_sha256"]:
            raise MotionRecipeError("Motion project changed since recipe selection")
        return payload

    def select(self, project_path: Path | str, recipe_id: str) -> dict[str, Any]:
        recipe = next((r for r in RECIPES if r["id"] == recipe_id), None)
        if recipe is None:
            raise MotionRecipeError("Unknown recipe")
        project = Path(project_path).resolve()
        verified = self.foundry.verify(project)
        record = {"schema": SELECTION_SCHEMA, "recipe_id": recipe_id, "recipe": recipe,
                  "project_id": verified["project_id"], "project_path": str(project),
                  "manifest_sha256": _sha((project / "manifest.json").read_bytes()),
                  "license_status": "operator_review_required",
                  "source_handling": "reference_link_only_no_code_import",
                  "adapter": "m2.6.3-native" if recipe["engine"] == "remotion" else "reference-only"}
        selection_id = "recipe_" + _sha(_canonical(record))[:16]
        record["selection_id"] = selection_id
        _write_once(self.base / "selections" / f"{selection_id}.json", record)
        return record

    @staticmethod
    def _frame(folder: Path, frame: int) -> tuple[bytes, tuple[int, int, bytes]]:
        if folder.is_symlink() or not folder.is_dir():
            raise MotionRecipeError("Frame folder must be a real directory")
        path = folder / f"frame_{frame:06d}.png"
        if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
            raise MotionRecipeError(f"Missing or unsafe frame: {path.name}")
        raw = path.read_bytes()
        return raw, _decode_png(raw)

    def qa(self, selection_id: str, baseline_dir: Path | str, actual_dir: Path | str,
           frames: list[int] | None = None, *, max_changed_fraction: float = 0.0,
           max_mae: float = 0.0) -> dict[str, Any]:
        selection = self._selection(selection_id)
        fraction_limit = _threshold(float(max_changed_fraction), 1.0, "max_changed_fraction")
        mae_limit = _threshold(float(max_mae), 255.0, "max_mae")
        project = Path(selection["project_path"])
        manifest = _read_json(project / "manifest.json")
        brief = _read_json(project / "src" / "brief.json")
        if frames is None:
            frames = _default_frames(brief["scenes"])
        if not isinstance(frames, list) or not 1 <= len(frames) <= 72 or any(
            type(i) is not int or not 0 <= i < manifest["duration_frames"] for i in frames
        ) or len(frames) != len(set(frames)):
            raise MotionRecipeError("Expected 1..72 unique in-range frame indices")
        if Path(baseline_dir).is_symlink() or Path(actual_dir).is_symlink():
            raise MotionRecipeError("Refusing symlink frame directories")
        before_dir, after_dir = Path(baseline_dir).resolve(), Path(actual_dir).resolve()
        expected = (manifest["width"], manifest["height"])
        samples = []
        for frame in sorted(frames):
            a_raw, (aw, ah, a) = self._frame(before_dir, frame)
            b_raw, (bw, bh, b) = self._frame(after_dir, frame)
            equal_size = (aw, ah) == (bw, bh) == expected
            if (aw, ah) == (bw, bh):
                _, changed, mae = _delta_png(aw, ah, a, b)
                fraction = changed / (aw * ah)
            else:
                changed, mae, fraction = -1, 255.0, 1.0
            samples.append({"frame": frame, "time_seconds": frame / manifest["fps"],
                            "baseline_sha256": _sha(a_raw), "actual_sha256": _sha(b_raw),
                            "baseline_size": [aw, ah], "actual_size": [bw, bh],
                            "changed_pixels": changed, "changed_fraction": fraction,
                            "mae": mae,
                            "pass": equal_size and fraction <= fraction_limit and mae <= mae_limit})
        status = "passed_pending_human" if all(s["pass"] for s in samples) else "failed"
        record = {"schema": QA_SCHEMA, "selection_id": selection_id, "project_id": selection["project_id"],
                  "manifest_sha256": selection["manifest_sha256"],
                  "baseline_dir": str(before_dir), "actual_dir": str(after_dir),
                  "frames": sorted(frames), "max_changed_fraction": fraction_limit,
                  "max_mae": mae_limit, "samples": samples, "status": status,
                  "coverage": "sampled_png_pixels_only",
                  "not_verified": ["mp4_decode", "audio_sync", "motion_semantics",
                                   "font_portability", "license", "human_review"]}
        receipt_id = "tqa_" + _sha(_canonical(record))[:16]
        record["receipt_id"] = receipt_id
        _write_once(self.base / "qa" / f"{receipt_id}.json", record)
        return record

    def review(self, receipt_id: str, *, actor: str, note: str) -> dict[str, Any]:
        if not re.fullmatch(r"tqa_[0-9a-f]{16}", receipt_id):
            raise MotionRecipeError("Invalid QA receipt ID")
        receipt = _read_json(self.base / "qa" / f"{receipt_id}.json")
        if receipt.get("schema") != QA_SCHEMA or receipt.get("receipt_id") != receipt_id:
            raise MotionRecipeError("Invalid QA receipt")
        unsigned = dict(receipt)
        unsigned.pop("receipt_id")
        if "tqa_" + _sha(_canonical(unsigned))[:16] != receipt_id:
            raise MotionRecipeError("QA receipt digest mismatch")
        if receipt["status"] != "passed_pending_human":
            raise MotionRecipeError("Failed QA cannot be approved")
        self._selection(receipt["selection_id"])
        if not re.fullmatch(r"human:[a-zA-Z0-9_.-]{2,80}", actor) or not note.strip() or len(note) > 500:
            raise MotionRecipeError("Require a human:<id> audit assertion and a review note")
        for sample in receipt["samples"]:
            for name, folder in (("baseline", receipt["baseline_dir"]),
                                 ("actual", receipt["actual_dir"])):
                raw, _ = self._frame(Path(folder), sample["frame"])
                if _sha(raw) != sample[f"{name}_sha256"]:
                    raise MotionRecipeError("Screenshots changed after QA")
        result = {"schema": REVIEW_SCHEMA, "receipt_id": receipt_id,
                  "selection_id": receipt["selection_id"], "actor_assertion": actor,
                  "note": note.strip(), "decision": "visual_approved_not_release_cleared"}
        result["review_id"] = "treview_" + _sha(_canonical(result))[:16]
        _write_once(self.base / "reviews" / f"{result['review_id']}.json", result)
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCC-M2.6.4b Motion Recipe / Temporal PNG QA")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("list", help="Show curated links; never imports source code")
    catalog.add_argument("--engine")
    select = sub.add_parser("select", help="Bind reference to a verified M2.6.3 project")
    select.add_argument("project", type=Path)
    select.add_argument("recipe_id")
    qa = sub.add_parser("qa", help="Compare externally captured frame_NNNNNN.png sequences")
    qa.add_argument("selection_id")
    qa.add_argument("baseline_dir", type=Path)
    qa.add_argument("actual_dir", type=Path)
    qa.add_argument("--frames", help="Comma-separated zero-based frame indices")
    qa.add_argument("--max-changed-fraction", type=float, default=0.0)
    qa.add_argument("--max-mae", type=float, default=0.0)
    review = sub.add_parser("review", help="Assert human visual approval, not publication clearance")
    review.add_argument("receipt_id")
    review.add_argument("--actor", required=True)
    review.add_argument("--note", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            result: Any = MotionRecipeRegistry.list_recipes(args.engine)
        else:
            registry = MotionRecipeRegistry(args.root)
            if args.command == "select":
                result = registry.select(args.project, args.recipe_id)
            elif args.command == "qa":
                frames = None if args.frames is None else [int(s) for s in args.frames.split(",")]
                result = registry.qa(args.selection_id, args.baseline_dir, args.actual_dir, frames,
                                     max_changed_fraction=args.max_changed_fraction,
                                     max_mae=args.max_mae)
            else:
                result = registry.review(args.receipt_id, actor=args.actor, note=args.note)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and result.get("status") == "failed" else 0
    except (MotionRecipeError, MotionFoundryError, ComponentGateError, ValueError,
            KeyError, TypeError, OSError) as exc:
        parser.exit(2, f"motion recipe: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
