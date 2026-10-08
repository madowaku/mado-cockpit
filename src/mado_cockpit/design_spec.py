"""MCC-M2.6: review-gated, replayable Living UI Spec.

No LLM/API dependency. Conversation output enters as explicitly structured
proposals; only an operator-confirmed review can promote a proposal.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from .models import Event, utc_now
from .store import CockpitStore

SPEC_SCHEMA = "mado.living-ui-spec.v1"
CHANGE_SCHEMA = "mado.design-change.v1"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DesignSpecError(RuntimeError):
    """A design contract or promotion invariant was violated."""


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise DesignSpecError(f"{field} must be a safe ID (1-128 characters)")
    return value


def _string(value: Any, field: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise DesignSpecError(f"{field} must be a non-empty string")
    return value.strip()


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise DesignSpecError(f"{field} must be a list of strings")
    return [_string(item, field) for item in value]


def _keys(value: Any, allowed: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - allowed:
        raise DesignSpecError(f"{field} contains unsupported fields")
    return value


def _hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        temp.write_text(content, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_screen(value: Any) -> dict[str, Any]:
    item = _keys(value, {"id", "title", "purpose", "states", "actions", "accessibility"}, "screen")
    _identifier(item.get("id"), "screen.id")
    _string(item.get("title"), "screen.title")
    _string(item.get("purpose"), "screen.purpose")
    _strings(item.get("states", []), "screen.states")
    _strings(item.get("accessibility", []), "screen.accessibility")
    actions = item.get("actions", [])
    if not isinstance(actions, list):
        raise DesignSpecError("screen.actions must be a list")
    ids: set[str] = set()
    for action in actions:
        _keys(action, {"id", "label", "next_screen"}, "screen.action")
        aid = _identifier(action.get("id"), "action.id")
        if aid in ids:
            raise DesignSpecError("duplicate action ID in screen")
        ids.add(aid)
        _string(action.get("label"), "action.label")
        if "next_screen" in action:
            _identifier(action["next_screen"], "action.next_screen")
    return item


def _validate_journey(value: Any) -> dict[str, Any]:
    item = _keys(value, {"id", "title", "steps", "done_when"}, "journey")
    _identifier(item.get("id"), "journey.id")
    _string(item.get("title"), "journey.title")
    steps = item.get("steps")
    if not isinstance(steps, list) or not steps:
        raise DesignSpecError("journey.steps must be non-empty")
    for step in steps:
        _keys(step, {"screen_id", "action_id"}, "journey.step")
        _identifier(step.get("screen_id"), "journey.step.screen_id")
        if "action_id" in step:
            _identifier(step["action_id"], "journey.step.action_id")
    _strings(item.get("done_when", []), "journey.done_when")
    return item


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("schema") != SPEC_SCHEMA:
        raise DesignSpecError("unsupported spec schema")
    _identifier(spec.get("mission_id"), "mission_id")
    if type(spec.get("revision")) is not int or spec["revision"] < 0:
        raise DesignSpecError("revision must be a non-negative integer")
    _string(spec.get("title"), "title")
    _string(spec.get("goal", ""), "goal", empty=True)
    for field in ("audiences", "principles", "constraints", "applied_change_ids"):
        _strings(spec.get(field), field)
    screens = spec.get("screens")
    journeys = spec.get("journeys")
    questions = spec.get("open_questions")
    decisions = spec.get("decisions")
    if not all(isinstance(x, list) for x in (screens, journeys, questions, decisions)):
        raise DesignSpecError("screens, journeys, questions and decisions must be lists")
    screen_map = {}
    for screen in screens:
        _validate_screen(screen)
        if screen["id"] in screen_map:
            raise DesignSpecError("duplicate screen ID")
        screen_map[screen["id"]] = screen
    for screen in screens:
        for action in screen.get("actions", []):
            if action.get("next_screen") and action["next_screen"] not in screen_map:
                raise DesignSpecError("action references an unknown next_screen")
    seen_journeys: set[str] = set()
    for journey in journeys:
        _validate_journey(journey)
        if journey["id"] in seen_journeys:
            raise DesignSpecError("duplicate journey ID")
        seen_journeys.add(journey["id"])
        for step in journey["steps"]:
            screen = screen_map.get(step["screen_id"])
            if screen is None:
                raise DesignSpecError("journey references an unknown screen")
            if "action_id" in step and step["action_id"] not in {
                action["id"] for action in screen.get("actions", [])
            }:
                raise DesignSpecError("journey references an unknown action")
    seen_questions: set[str] = set()
    for question in questions:
        _keys(question, {"id", "question", "choices", "status", "answer"}, "question")
        qid = _identifier(question.get("id"), "question.id")
        if qid in seen_questions:
            raise DesignSpecError("duplicate question ID")
        seen_questions.add(qid)
        _string(question.get("question"), "question.question")
        _strings(question.get("choices", []), "question.choices")
        if question.get("status") not in ("open", "resolved"):
            raise DesignSpecError("invalid question status")
        if question["status"] == "resolved":
            _string(question.get("answer"), "question.answer")
    seen_decisions: set[str] = set()
    for decision in decisions:
        _keys(
            decision,
            {"id", "statement", "rationale", "source_ref", "approved_by", "approved_at"},
            "decision",
        )
        did = _identifier(decision.get("id"), "decision.id")
        if did in seen_decisions:
            raise DesignSpecError("duplicate decision ID")
        seen_decisions.add(did)
        for field in ("statement", "rationale", "source_ref", "approved_by", "approved_at"):
            _string(decision.get(field), "decision." + field)


def apply_operations(
    spec: dict[str, Any],
    operations: list[dict[str, Any]],
    *,
    source_ref: str,
    reviewer: str,
    reviewed_at: str,
) -> dict[str, Any]:
    if not isinstance(operations, list) or not operations:
        raise DesignSpecError("operations must be a non-empty list")
    result = deepcopy(spec)
    for op in operations:
        _keys(op, {"op", "field", "value", "id"}, "operation")
        kind = op.get("op")
        field = op.get("field")
        if kind == "set" and field in ("goal", "audiences", "principles", "constraints"):
            if set(op) != {"op", "field", "value"}:
                raise DesignSpecError("set requires op, field and value")
            result[field] = (
                _string(op["value"], field, empty=True)
                if field == "goal" else _strings(op["value"], field)
            )
        elif kind == "upsert" and field in ("screens", "journeys", "open_questions"):
            if set(op) != {"op", "field", "value"}:
                raise DesignSpecError("upsert requires op, field and value")
            value = deepcopy(op["value"])
            if field == "screens":
                _validate_screen(value)
            elif field == "journeys":
                _validate_journey(value)
            else:
                _keys(value, {"id", "question", "choices"}, "new question")
                _identifier(value.get("id"), "question.id")
                _string(value.get("question"), "question.question")
                _strings(value.get("choices", []), "question.choices")
                value["status"] = "open"
            result[field] = [x for x in result[field] if x["id"] != value["id"]] + [value]
        elif kind == "remove" and field in ("screens", "journeys", "open_questions"):
            if set(op) != {"op", "field", "id"}:
                raise DesignSpecError("remove requires op, field and id")
            ident = _identifier(op["id"], "remove.id")
            if not any(x["id"] == ident for x in result[field]):
                raise DesignSpecError("cannot remove missing item")
            result[field] = [x for x in result[field] if x["id"] != ident]
        elif kind == "resolve_question" and field == "open_questions":
            if set(op) != {"op", "field", "id", "value"}:
                raise DesignSpecError("resolve_question requires id and value")
            ident = _identifier(op["id"], "question.id")
            answer = _string(op["value"], "question.answer")
            question = next((x for x in result[field] if x["id"] == ident), None)
            if question is None or question["status"] != "open":
                raise DesignSpecError("question not found or already resolved")
            question.update(status="resolved", answer=answer)
        elif kind == "record_decision" and field == "decisions":
            if set(op) != {"op", "field", "value"}:
                raise DesignSpecError("record_decision requires value")
            decision = _keys(op["value"], {"id", "statement", "rationale"}, "new decision")
            _identifier(decision.get("id"), "decision.id")
            _string(decision.get("statement"), "decision.statement")
            _string(decision.get("rationale"), "decision.rationale")
            if any(x["id"] == decision["id"] for x in result["decisions"]):
                raise DesignSpecError("decisions are append-only")
            result["decisions"].append({
                **decision, "source_ref": source_ref,
                "approved_by": reviewer, "approved_at": reviewed_at,
            })
        else:
            raise DesignSpecError(f"unsupported operation: {kind}/{field}")
    validate_spec(result)
    return result


def _md(value: str) -> str:
    # Markdown is a projection of data, not an executable input.
    value = html.escape(value.replace("\r", " ").replace("\n", " "))
    return re.sub(r"([\\`*_{}\[\]<>#|])", r"\\\1", value)


def render_markdown(spec: dict[str, Any]) -> str:
    lines = [
        f"# {_md(spec['title'])}",
        "",
        f"> Living UI Spec • {SPEC_SCHEMA} • mission `{spec['mission_id']}` • revision {spec['revision']}",
        "",
        "## Goal",
        "",
        _md(spec["goal"]) if spec["goal"] else "_Not yet defined_",
        "",
    ]
    for key, label in (("audiences", "Audiences"), ("principles", "Principles"), ("constraints", "Constraints")):
        lines.extend([f"## {label}", ""])
        lines.extend(["- " + _md(x) for x in spec[key]] or ["_Not yet defined_"])
        lines.append("")
    lines.extend(["## Screens", ""])
    if not spec["screens"]:
        lines.extend(["_No screens yet_", ""])
    for screen in spec["screens"]:
        lines.extend([f"### {_md(screen['title'])} (`{screen['id']}`)", "", _md(screen["purpose"]), ""])
        for action in screen.get("actions", []):
            target = f" → `{action['next_screen']}`" if action.get("next_screen") else ""
            lines.append(f"- Action `{action['id']}`: {_md(action['label'])}{target}")
        for state in screen.get("states", []):
            lines.append("- State: " + _md(state))
        for check in screen.get("accessibility", []):
            lines.append("- A11y: " + _md(check))
        lines.append("")
    lines.extend(["## Journeys", ""])
    for journey in spec["journeys"]:
        lines.extend([f"### {_md(journey['title'])} (`{journey['id']}`)", ""])
        for step in journey["steps"]:
            suffix = f" / `{step['action_id']}`" if "action_id" in step else ""
            lines.append(f"- `{step['screen_id']}`{suffix}")
        for criterion in journey.get("done_when", []):
            lines.append("- Done when: " + _md(criterion))
        lines.append("")
    lines.extend(["## Human-approved decisions", ""])
    for decision in spec["decisions"]:
        lines.extend([
            f"- **`{decision['id']}`** {_md(decision['statement'])}",
            f"  - Why: {_md(decision['rationale'])}",
            f"  - Approved: {_md(decision['approved_by'])} • Source: {_md(decision['source_ref'])}",
        ])
    lines.extend(["", "## Open questions", ""])
    for question in spec["open_questions"]:
        lines.append(
            f"- `{question['id']}` [{question['status']}]: {_md(question['question'])}"
            + (f" → {_md(question['answer'])}" if question["status"] == "resolved" else "")
        )
    lines.append("")
    return "\n".join(lines)


class DesignSpecManager:
    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.base = store.base / "design_specs"

    def _dir(self, mission_id: str) -> Path:
        _identifier(mission_id, "mission_id")
        return self.base / mission_id

    @contextmanager
    def _lock(self, mission_id: str) -> Iterator[None]:
        folder = self._dir(mission_id)
        folder.mkdir(parents=True, exist_ok=True)
        lock = folder / ".write-lock"
        try:
            lock.mkdir()
        except FileExistsError as exc:
            raise DesignSpecError("design spec is locked by another writer") from exc
        try:
            yield
        finally:
            lock.rmdir()

    def _event(self, mission_id: str, kind: str, **fields: Any) -> None:
        self.store.append_event(Event(
            type="design." + kind, mission_id=mission_id,
            subject={"mission_id": mission_id, **fields},
        ))

    def init(self, mission_id: str) -> dict[str, Any]:
        mission = self.store.get_mission(_identifier(mission_id, "mission_id"))
        with self._lock(mission_id):
            path = self._dir(mission_id) / "spec.json"
            if path.exists():
                return self.show(mission_id)
            now = utc_now()
            spec: dict[str, Any] = {
                "schema": SPEC_SCHEMA, "mission_id": mission_id,
                "title": _string(mission["title"], "mission.title"),
                "revision": 0, "goal": "", "audiences": [],
                "principles": [], "constraints": [],
                "screens": [], "journeys": [], "open_questions": [],
                "decisions": [], "applied_change_ids": [],
                "updated_at": now,
            }
            validate_spec(spec)
            _atomic_json(self._dir(mission_id) / "revisions" / "0000.json", spec)
            _atomic_json(path, spec)
            _atomic_text(self._dir(mission_id) / "spec.md", render_markdown(spec))
            self._event(mission_id, "spec.initialized", revision=0)
            return spec

    def show(self, mission_id: str) -> dict[str, Any]:
        path = self._dir(mission_id) / "spec.json"
        if not path.is_file():
            raise DesignSpecError("living spec is missing; run design-spec init first")
        spec = _read(path)
        validate_spec(spec)
        if spec["mission_id"] != mission_id:
            raise DesignSpecError("mission mismatch in stored spec")
        return spec

    def propose(self, mission_id: str, change: dict[str, Any]) -> dict[str, Any]:
        self.store.get_mission(_identifier(mission_id, "mission_id"))
        _keys(change, {"schema", "base_revision", "source_ref", "initiator", "operations"}, "change")
        if change.get("schema") != CHANGE_SCHEMA:
            raise DesignSpecError("unsupported change schema")
        if type(change.get("base_revision")) is not int or change["base_revision"] < 0:
            raise DesignSpecError("base_revision must be a non-negative integer")
        source_ref = _string(change.get("source_ref"), "source_ref")
        initiator = _string(change.get("initiator"), "initiator")
        operations = change.get("operations")
        with self._lock(mission_id):
            current = self.show(mission_id)
            if current["revision"] != change["base_revision"]:
                raise DesignSpecError("stale base_revision; inspect the current spec")
            preview = apply_operations(
                current, operations, source_ref=source_ref,
                reviewer="pending-human-review", reviewed_at="pending",
            )
            payload = {
                "schema": CHANGE_SCHEMA, "mission_id": mission_id,
                "base_revision": current["revision"],
                "source_ref": source_ref, "initiator": initiator,
                "operations": operations,
            }
            ident = "dchg_" + _hash(payload)[:20]
            path = self._dir(mission_id) / "proposals" / (ident + ".json")
            if path.exists():
                existing = _read(path)
                if existing["status"] != "pending":
                    return existing
                return existing
            proposal = {
                **payload, "id": ident, "status": "pending",
                "created_at": utc_now(), "preview_sha256": _hash(preview),
                "proposed_revision": current["revision"] + 1,
            }
            _atomic_json(path, proposal)
            self._event(mission_id, "change.proposed", proposal_id=ident,
                        base_revision=current["revision"], source_ref=source_ref)
            return proposal

    def review(
        self, mission_id: str, proposal_id: str, *,
        decision: str, reviewer: str, human_confirm: bool,
        note: str = "",
    ) -> dict[str, Any]:
        if not human_confirm:
            raise DesignSpecError("explicit --human-confirm is required for review")
        if decision not in ("approve", "reject"):
            raise DesignSpecError("decision must be approve or reject")
        reviewer = _string(reviewer, "reviewer")
        _identifier(proposal_id, "proposal_id")
        with self._lock(mission_id):
            path = self._dir(mission_id) / "proposals" / (proposal_id + ".json")
            if not path.is_file():
                raise DesignSpecError("proposal not found")
            proposal = _read(path)
            if proposal["mission_id"] != mission_id:
                raise DesignSpecError("proposal mission mismatch")
            if proposal["status"] != "pending":
                if proposal["status"] == ("approved" if decision == "approve" else "rejected"):
                    return proposal
                raise DesignSpecError("proposal already resolved in the opposite direction")
            current = self.show(mission_id)
            now = utc_now()
            if decision == "approve":
                if proposal_id in current["applied_change_ids"]:
                    applied_revision = next(
                        rev["revision"] for rev in self.history(mission_id)
                        if proposal_id in rev["applied_change_ids"]
                    )
                else:
                    if proposal["base_revision"] != current["revision"]:
                        raise DesignSpecError("stale proposal; create a new proposal against current revision")
                    next_spec = apply_operations(
                        current, proposal["operations"],
                        source_ref=proposal["source_ref"],
                        reviewer=reviewer, reviewed_at=now,
                    )
                    next_spec["revision"] = current["revision"] + 1
                    next_spec["applied_change_ids"].append(proposal_id)
                    next_spec["updated_at"] = now
                    validate_spec(next_spec)
                    applied_revision = next_spec["revision"]
                    _atomic_json(
                        self._dir(mission_id) / "revisions" / f"{applied_revision:04d}.json",
                        next_spec,
                    )
                    _atomic_json(self._dir(mission_id) / "spec.json", next_spec)
                    _atomic_text(self._dir(mission_id) / "spec.md", render_markdown(next_spec))
                proposal["applied_revision"] = applied_revision
            proposal.update(
                status="approved" if decision == "approve" else "rejected",
                reviewed_at=now, reviewer=reviewer,
                review_note=_string(note, "note", empty=True),
            )
            _atomic_json(path, proposal)
            self._event(mission_id, "change." + proposal["status"],
                        proposal_id=proposal_id, reviewer=reviewer,
                        revision=proposal.get("applied_revision"))
            return proposal

    def history(self, mission_id: str) -> list[dict[str, Any]]:
        self.show(mission_id)
        return [
            _read(path) for path in sorted((self._dir(mission_id) / "revisions").glob("*.json"))
        ]

    def proposals(self, mission_id: str) -> list[dict[str, Any]]:
        self.show(mission_id)
        return [
            _read(path) for path in sorted((self._dir(mission_id) / "proposals").glob("*.json"))
        ]

    def validate(self, mission_id: str) -> dict[str, Any]:
        spec = self.show(mission_id)
        path = self._dir(mission_id)
        revision_path = path / "revisions" / f"{spec['revision']:04d}.json"
        if not revision_path.exists() or _read(revision_path) != spec:
            raise DesignSpecError("current spec does not match its immutable revision")
        if (path / "spec.md").read_text(encoding="utf-8") != render_markdown(spec):
            raise DesignSpecError("Markdown projection is out of sync")
        revisions = self.history(mission_id)
        if [x["revision"] for x in revisions] != list(range(spec["revision"] + 1)):
            raise DesignSpecError("missing or non-sequential history revisions")
        if len(spec["applied_change_ids"]) != spec["revision"]:
            raise DesignSpecError("revision and applied change count differ")
        return {
            "schema": SPEC_SCHEMA, "mission_id": mission_id,
            "revision": spec["revision"], "valid": True,
            "sha256": _hash(spec), "history_count": len(revisions),
            "open_questions": sum(q["status"] == "open" for q in spec["open_questions"]),
        }
