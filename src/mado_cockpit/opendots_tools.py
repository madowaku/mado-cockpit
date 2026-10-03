from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .evidence import EvidenceManager
from .handoffs import HandoffManager
from .opendots import (
    OpenDotsRuntimeAdapter,
    SCHEMA as RUNTIME_SCHEMA,
)
from .operator import OperatorManager
from .store import CockpitStore


TOOL_CALL_SCHEMA = "mado.opendots.tool-call.v1"
TOOL_RESULT_SCHEMA = "mado.opendots.tool-result.v1"
TOOL_SURFACE_VERSION = "MCC-M1.3"

_TOOL_NAMES = {
    "mado_check_mission",
    "mado_advance_mission",
    "mado_answer_human_gate",
    "mado_show_evidence",
    "mado_show_qa_result",
}
_TOOL_CALL_ID = re.compile(r"^[^\r\n]{1,256}$")


class OpenDotsToolError(RuntimeError):
    """Raised when a tool call violates the M1.3 contract."""


def tool_catalog() -> list[dict[str, Any]]:
    operator_id = {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
        "description": "MADO Cockpit Operator ID.",
    }
    return [
        {
            "name": "mado_check_mission",
            "description": (
                "Read the current MADO Cockpit mission state, next action, "
                "and any open Human Question Gate. Read-only."
            ),
            "read_only": True,
            "parameters": {
                "type": "object",
                "properties": {"operator_id": operator_id},
                "required": ["operator_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "mado_advance_mission",
            "description": (
                "Advance only deterministic MADO Cockpit orchestration. "
                "This never launches a model or shell command."
            ),
            "read_only": False,
            "parameters": {
                "type": "object",
                "properties": {"operator_id": operator_id},
                "required": ["operator_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "mado_answer_human_gate",
            "description": (
                "Resolve the Operator's current Human Question Gate only "
                "after the user explicitly chose an option, or explicitly "
                "asked to use the declared safe default."
            ),
            "read_only": False,
            "requires_explicit_user_choice": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "operator_id": operator_id,
                    "choice": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "choose_for_me": {
                        "type": "boolean",
                        "default": False,
                    },
                    "note": {
                        "type": "string",
                        "maxLength": 2000,
                    },
                },
                "required": ["operator_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "mado_show_evidence",
            "description": (
                "Show evidence and result metadata for the Builder, QA, "
                "or both. Read-only and omits Cockpit filesystem paths."
            ),
            "read_only": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "operator_id": operator_id,
                    "scope": {
                        "type": "string",
                        "enum": ["builder", "qa", "all"],
                        "default": "all",
                    },
                },
                "required": ["operator_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "mado_show_qa_result",
            "description": (
                "Show the current QA handoff, latest QA result, and verdict "
                "without changing mission state. Read-only."
            ),
            "read_only": True,
            "parameters": {
                "type": "object",
                "properties": {"operator_id": operator_id},
                "required": ["operator_id"],
                "additionalProperties": False,
            },
        },
    ]


class OpenDotsToolSurface:
    def __init__(
        self,
        store: CockpitStore,
        *,
        runtime_adapter: Any | None = None,
        operator: Any | None = None,
        evidence: Any | None = None,
        handoffs: Any | None = None,
    ) -> None:
        self.store = store
        self.runtime_adapter = (
            runtime_adapter
            or OpenDotsRuntimeAdapter(store)
        )
        self.operator = operator or OperatorManager(store)
        self.evidence = evidence or EvidenceManager(store)
        self.handoffs = handoffs or HandoffManager(store)

    def handle(
        self,
        call: Mapping[str, Any],
    ) -> dict[str, Any]:
        envelope = self._validate_call(call)
        try:
            data, presentation = self._dispatch(envelope)
        except OpenDotsToolError:
            raise
        except RuntimeError as exc:
            return self._result(
                envelope,
                ok=False,
                error={
                    "code": "cockpit_read_error",
                    "message": str(exc),
                },
            )
        return self._result(
            envelope,
            ok=True,
            data=data,
            presentation=presentation,
        )

    def _dispatch(
        self,
        call: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        name = call["tool_name"]
        arguments = call["arguments"]
        operator_id = self._operator_id(arguments)

        if name == "mado_check_mission":
            self._only(arguments, {"operator_id"}, name)
            response = self._runtime(
                call,
                action="operator.status",
                operator_id=operator_id,
                payload={},
            )
            operator = self._runtime_data(response)
            projected = self._project_operator(operator)
            return projected, self._mission_presentation(projected)

        if name == "mado_advance_mission":
            self._only(arguments, {"operator_id"}, name)
            response = self._runtime(
                call,
                action="operator.advance",
                operator_id=operator_id,
                payload={},
            )
            operator = self._runtime_data(response)
            projected = self._project_operator(operator)
            presentation = self._mission_presentation(projected)
            presentation["kind"] = "mission_advanced"
            presentation["title"] = "Mission advanced"
            return projected, presentation

        if name == "mado_answer_human_gate":
            self._only(
                arguments,
                {
                    "operator_id",
                    "choice",
                    "choose_for_me",
                    "note",
                },
                name,
            )
            choice = arguments.get("choice")
            choose_for_me = arguments.get(
                "choose_for_me",
                False,
            )
            note = arguments.get("note")
            if choice is not None and (
                not isinstance(choice, str)
                or not choice.strip()
            ):
                raise OpenDotsToolError(
                    "choice must be a non-empty string"
                )
            if not isinstance(choose_for_me, bool):
                raise OpenDotsToolError(
                    "choose_for_me must be boolean"
                )
            if note is not None and (
                not isinstance(note, str)
                or len(note) > 2000
            ):
                raise OpenDotsToolError(
                    "note must be a string up to 2000 characters"
                )
            if bool(choice) == choose_for_me:
                raise OpenDotsToolError(
                    "exactly one of choice or choose_for_me is required"
                )
            payload: dict[str, Any] = {
                "choose_for_me": choose_for_me,
            }
            if choice:
                payload["choice"] = choice.strip()
            if note:
                payload["note"] = note
            response = self._runtime(
                call,
                action="gate.resolve",
                operator_id=operator_id,
                payload=payload,
            )
            runtime_data = self._runtime_data(response)
            operator = runtime_data.get(
                "operator",
                runtime_data,
            )
            projected = self._project_operator(operator)
            gate = runtime_data.get("gate")
            data = {
                "resolution": (
                    self._project_gate_resolution(gate)
                    if isinstance(gate, Mapping)
                    else None
                ),
                "operator": projected,
            }
            presentation = self._mission_presentation(projected)
            presentation["kind"] = "human_gate_resolved"
            presentation["title"] = "Human decision recorded"
            if data["resolution"]:
                presentation["summary"] = (
                    "Recorded "
                    f"{data['resolution'].get('choice', 'decision')} "
                    "and resumed Cockpit orchestration."
                )
            return data, presentation

        if name == "mado_show_evidence":
            self._only(
                arguments,
                {"operator_id", "scope"},
                name,
            )
            scope = arguments.get("scope", "all")
            if scope not in {"builder", "qa", "all"}:
                raise OpenDotsToolError(
                    "scope must be builder, qa, or all"
                )
            operator = self.operator.inspect(operator_id)
            evidence = self._evidence_view(
                operator,
                scope=scope,
            )
            return evidence, self._evidence_presentation(evidence)

        if name == "mado_show_qa_result":
            self._only(arguments, {"operator_id"}, name)
            operator = self.operator.inspect(operator_id)
            qa = self._qa_view(operator)
            return qa, self._qa_presentation(qa)

        raise OpenDotsToolError(
            f"unsupported tool: {name}"
        )

    def _runtime(
        self,
        call: Mapping[str, Any],
        *,
        action: str,
        operator_id: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        context = call["context"]
        source = {
            "dot_id": context["dot_id"],
        }
        if context.get("space_id"):
            source["space_id"] = context["space_id"]
        if context.get("thread_id"):
            source["thread_id"] = context["thread_id"]

        response = self.runtime_adapter.handle(
            {
                "schema": RUNTIME_SCHEMA,
                "request_id": self._request_id(call),
                "action": action,
                "source": source,
                "target": {
                    "operator_id": operator_id,
                },
                "payload": dict(payload),
            }
        )
        if response.get("status") != "ok":
            error = response.get("error") or {}
            raise RuntimeError(
                str(
                    error.get(
                        "message",
                        "Cockpit runtime request failed",
                    )
                )
            )
        return response

    @staticmethod
    def _runtime_data(
        response: Mapping[str, Any],
    ) -> dict[str, Any]:
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise RuntimeError(
                "Cockpit runtime returned no object data"
            )
        return dict(data)

    def _evidence_view(
        self,
        operator: Mapping[str, Any],
        *,
        scope: str,
    ) -> dict[str, Any]:
        tasks: list[tuple[str, Mapping[str, Any]]] = []
        builder = operator.get("builder_task")
        qa = operator.get("qa_task")
        if (
            scope in {"builder", "all"}
            and isinstance(builder, Mapping)
        ):
            tasks.append(("builder", builder))
        if (
            scope in {"qa", "all"}
            and isinstance(qa, Mapping)
        ):
            tasks.append(("qa", qa))

        task_views = []
        for role, task in tasks:
            task_id = str(task["id"])
            bundles = [
                self._project_bundle(bundle)
                for bundle
                in self.evidence.list_bundles(
                    task_id
                )
            ]
            results = [
                self._project_result(result)
                for result
                in self.evidence.list_results(
                    task_id
                )
            ]
            task_views.append(
                {
                    "role": role,
                    "task_id": task_id,
                    "task_status": task.get("status"),
                    "required_evidence": list(
                        task.get(
                            "required_evidence",
                            [],
                        )
                    ),
                    "bundles": bundles,
                    "results": results,
                }
            )

        return {
            "operator_id": str(
                operator["plan"]["id"]
            ),
            "scope": scope,
            "tasks": task_views,
        }

    def _qa_view(
        self,
        operator: Mapping[str, Any],
    ) -> dict[str, Any]:
        plan = operator["plan"]
        handoff = operator.get("handoff")
        if not isinstance(handoff, Mapping):
            return {
                "operator_id": str(plan["id"]),
                "available": False,
                "status": "not_started",
                "handoff": None,
                "latest_result": None,
                "verdict": None,
            }

        contract = handoff.get("handoff")
        status = handoff.get("status")
        if not isinstance(contract, Mapping):
            raise RuntimeError(
                "Operator handoff is missing its contract"
            )
        qa_task_id = str(contract["qa_task_id"])
        results = self.evidence.list_results(
            qa_task_id
        )
        latest = (
            max(
                results,
                key=lambda item: str(
                    item.get("submitted_at", "")
                ),
            )
            if results
            else None
        )
        verdict = handoff.get("verdict")
        return {
            "operator_id": str(plan["id"]),
            "available": True,
            "status": (
                status.get("status")
                if isinstance(status, Mapping)
                else "unknown"
            ),
            "handoff": {
                "id": contract.get("id"),
                "source_task_id": contract.get(
                    "source_task_id"
                ),
                "source_result_id": contract.get(
                    "source_result_id"
                ),
                "source_bundle_id": contract.get(
                    "source_bundle_id"
                ),
                "qa_task_id": qa_task_id,
                "created_at": contract.get(
                    "created_at"
                ),
            },
            "latest_result": (
                self._project_result(latest)
                if latest
                else None
            ),
            "verdict": (
                self._project_verdict(verdict)
                if isinstance(verdict, Mapping)
                else None
            ),
        }

    @staticmethod
    def _project_operator(
        operator: Mapping[str, Any],
    ) -> dict[str, Any]:
        plan = operator["plan"]
        state = operator["state"]
        builder_task = operator["builder_task"]
        qa_task = operator.get("qa_task")
        handoff = operator.get("handoff")
        projected_handoff = None
        if isinstance(handoff, Mapping):
            contract = handoff.get("handoff")
            status = handoff.get("status")
            if isinstance(contract, Mapping):
                projected_handoff = {
                    "id": contract.get("id"),
                    "qa_task_id": contract.get(
                        "qa_task_id"
                    ),
                    "status": (
                        status.get("status")
                        if isinstance(
                            status,
                            Mapping,
                        )
                        else None
                    ),
                }

        gate = operator.get("human_gate")
        return {
            "operator_id": str(plan["id"]),
            "mission_id": str(plan["mission_id"]),
            "objective": str(plan["objective"]),
            "status": str(state["status"]),
            "next_action": operator.get(
                "next_action"
            ),
            "builder": {
                "task_id": builder_task.get("id"),
                "status": builder_task.get("status"),
                "required_evidence": list(
                    builder_task.get(
                        "required_evidence",
                        [],
                    )
                ),
            },
            "qa": (
                {
                    "task_id": qa_task.get("id"),
                    "status": qa_task.get("status"),
                }
                if isinstance(qa_task, Mapping)
                else None
            ),
            "handoff": projected_handoff,
            "human_gate": (
                OpenDotsToolSurface._project_gate(
                    gate
                )
                if isinstance(gate, Mapping)
                else None
            ),
        }

    @staticmethod
    def _project_gate(
        gate_view: Mapping[str, Any],
    ) -> dict[str, Any]:
        gate = gate_view.get("gate")
        status = gate_view.get("status")
        if not isinstance(gate, Mapping):
            return {}
        return {
            "id": gate.get("id"),
            "status": (
                status.get("status")
                if isinstance(status, Mapping)
                else None
            ),
            "question": gate.get("question"),
            "reason": gate.get("reason"),
            "materiality": gate.get(
                "materiality"
            ),
            "choices": list(
                gate.get("choices", [])
            ),
            "impacts": dict(
                gate.get("impacts", {})
            ),
            "recommendation": gate.get(
                "recommendation"
            ),
            "safe_default": gate.get(
                "safe_default"
            ),
            "allow_choose_for_me": gate.get(
                "allow_choose_for_me",
                False,
            ),
        }

    @staticmethod
    def _project_gate_resolution(
        gate_view: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        resolution = gate_view.get(
            "resolution"
        )
        if not isinstance(resolution, Mapping):
            return None
        return {
            "gate_id": resolution.get("gate_id"),
            "choice": resolution.get("choice"),
            "method": resolution.get("method"),
            "resolved_at": resolution.get(
                "resolved_at"
            ),
        }

    @staticmethod
    def _project_bundle(
        bundle: Mapping[str, Any],
    ) -> dict[str, Any]:
        items = []
        for item in bundle.get("items", []):
            if not isinstance(item, Mapping):
                continue
            items.append(
                {
                    "id": item.get("id"),
                    "kind": item.get("kind"),
                    "sha256": item.get("sha256"),
                    "size_bytes": item.get(
                        "size_bytes"
                    ),
                    "source": item.get("source"),
                    "description": item.get(
                        "description"
                    ),
                }
            )
        return {
            "id": bundle.get("id"),
            "task_id": bundle.get("task_id"),
            "status": bundle.get("status"),
            "required_evidence": list(
                bundle.get(
                    "required_evidence",
                    [],
                )
            ),
            "missing_evidence": list(
                bundle.get(
                    "missing_evidence",
                    [],
                )
            ),
            "items": items,
            "created_at": bundle.get(
                "created_at"
            ),
        }

    @staticmethod
    def _project_result(
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": result.get("id"),
            "task_id": result.get("task_id"),
            "status": result.get("status"),
            "summary": result.get("summary"),
            "evidence_bundle_id": result.get(
                "evidence_bundle_id"
            ),
            "evidence_status": result.get(
                "evidence_status"
            ),
            "readiness": result.get(
                "readiness"
            ),
            "missing_evidence": list(
                result.get(
                    "missing_evidence",
                    [],
                )
            ),
            "risks": list(
                result.get("risks", [])
            ),
            "submitted_at": result.get(
                "submitted_at"
            ),
        }

    @staticmethod
    def _project_verdict(
        verdict: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "id": verdict.get("id"),
            "handoff_id": verdict.get(
                "handoff_id"
            ),
            "qa_result_id": verdict.get(
                "qa_result_id"
            ),
            "verdict": verdict.get("verdict"),
            "summary": verdict.get("summary"),
            "created_at": verdict.get(
                "created_at"
            ),
        }

    @staticmethod
    def _mission_presentation(
        operator: Mapping[str, Any],
    ) -> dict[str, Any]:
        status = str(operator["status"])
        next_action = operator.get(
            "next_action"
        )
        return {
            "kind": "mission_status",
            "title": (
                f"Mission {operator['mission_id']}"
            ),
            "status": status,
            "summary": (
                f"{status}. Next: {next_action}"
                if next_action
                else status
            ),
            "facts": [
                {
                    "label": "Builder",
                    "value": operator[
                        "builder"
                    ]["status"],
                },
                {
                    "label": "QA",
                    "value": (
                        operator["qa"]["status"]
                        if operator.get("qa")
                        else "not started"
                    ),
                },
            ],
            "human_gate": operator.get(
                "human_gate"
            ),
        }

    @staticmethod
    def _evidence_presentation(
        evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        bundles = [
            bundle
            for task in evidence["tasks"]
            for bundle in task["bundles"]
        ]
        missing = sum(
            len(bundle["missing_evidence"])
            for bundle in bundles
        )
        if not bundles:
            status = "empty"
        elif missing:
            status = "incomplete"
        else:
            status = "validated"
        return {
            "kind": "evidence_summary",
            "title": "Mission evidence",
            "status": status,
            "summary": (
                f"{len(bundles)} evidence bundle(s); "
                f"{missing} missing requirement(s)."
            ),
            "facts": [
                {
                    "label": task["role"].title(),
                    "value": (
                        f"{len(task['bundles'])} bundle(s), "
                        f"{len(task['results'])} result(s)"
                    ),
                }
                for task in evidence["tasks"]
            ],
        }

    @staticmethod
    def _qa_presentation(
        qa: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not qa["available"]:
            return {
                "kind": "qa_result",
                "title": "QA",
                "status": "not_started",
                "summary": "No QA handoff exists yet.",
                "facts": [],
            }
        verdict = qa.get("verdict")
        latest = qa.get("latest_result")
        if verdict:
            summary = str(verdict.get("summary"))
            status = str(verdict.get("verdict"))
        elif latest:
            summary = str(latest.get("summary"))
            status = str(qa.get("status"))
        else:
            summary = "QA handoff exists; no QA result has been submitted yet."
            status = str(qa.get("status"))
        return {
            "kind": "qa_result",
            "title": "QA result",
            "status": status,
            "summary": summary,
            "facts": [
                {
                    "label": "Handoff",
                    "value": qa["handoff"]["id"],
                },
                {
                    "label": "QA task",
                    "value": qa["handoff"][
                        "qa_task_id"
                    ],
                },
            ],
        }

    @staticmethod
    def _operator_id(
        arguments: Mapping[str, Any],
    ) -> str:
        value = arguments.get("operator_id")
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > 128
        ):
            raise OpenDotsToolError(
                "operator_id is required"
            )
        return value.strip()

    @staticmethod
    def _only(
        arguments: Mapping[str, Any],
        allowed: set[str],
        tool_name: str,
    ) -> None:
        unknown = set(arguments) - allowed
        if unknown:
            raise OpenDotsToolError(
                f"{tool_name} has unsupported arguments: "
                + ", ".join(sorted(unknown))
            )

    @staticmethod
    def _request_id(
        call: Mapping[str, Any],
    ) -> str:
        context = call["context"]
        payload = "|".join(
            [
                str(call["tool_call_id"]),
                str(call["tool_name"]),
                str(context["dot_id"]),
                str(context.get("thread_id", "")),
            ]
        ).encode("utf-8")
        return (
            "agui_"
            + hashlib.sha256(payload).hexdigest()[:32]
        )

    @staticmethod
    def _result(
        call: Mapping[str, Any],
        *,
        ok: bool,
        data: Mapping[str, Any] | None = None,
        presentation: Mapping[str, Any] | None = None,
        error: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema": TOOL_RESULT_SCHEMA,
            "surface_version": (
                TOOL_SURFACE_VERSION
            ),
            "tool_call_id": call["tool_call_id"],
            "tool_name": call["tool_name"],
            "ok": ok,
        }
        if data is not None:
            result["data"] = dict(data)
        if presentation is not None:
            result["presentation"] = dict(
                presentation
            )
        if error is not None:
            result["error"] = dict(error)
        return result

    @staticmethod
    def _validate_call(
        call: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(call, Mapping):
            raise OpenDotsToolError(
                "tool call must be a JSON object"
            )
        allowed = {
            "schema",
            "tool_call_id",
            "tool_name",
            "context",
            "arguments",
        }
        unknown = set(call) - allowed
        if unknown:
            raise OpenDotsToolError(
                "tool call has unsupported fields: "
                + ", ".join(sorted(unknown))
            )
        if call.get("schema") != TOOL_CALL_SCHEMA:
            raise OpenDotsToolError(
                f"schema must be {TOOL_CALL_SCHEMA}"
            )
        tool_call_id = call.get(
            "tool_call_id"
        )
        if (
            not isinstance(tool_call_id, str)
            or not _TOOL_CALL_ID.fullmatch(
                tool_call_id
            )
        ):
            raise OpenDotsToolError(
                "tool_call_id must be a non-empty single-line string"
            )
        tool_name = call.get("tool_name")
        if tool_name not in _TOOL_NAMES:
            raise OpenDotsToolError(
                f"unsupported tool: {tool_name!r}"
            )

        context = call.get("context")
        if not isinstance(context, Mapping):
            raise OpenDotsToolError(
                "context must be an object"
            )
        context_allowed = {
            "dot_id",
            "space_id",
            "thread_id",
        }
        context_unknown = (
            set(context) - context_allowed
        )
        if context_unknown:
            raise OpenDotsToolError(
                "context has unsupported fields: "
                + ", ".join(
                    sorted(context_unknown)
                )
            )
        dot_id = context.get("dot_id")
        if (
            not isinstance(dot_id, str)
            or not dot_id.strip()
        ):
            raise OpenDotsToolError(
                "context.dot_id is required"
            )
        normalized_context: dict[str, str] = {
            "dot_id": dot_id.strip(),
        }
        for key in ("space_id", "thread_id"):
            value = context.get(key)
            if value is not None:
                if (
                    not isinstance(value, str)
                    or not value.strip()
                ):
                    raise OpenDotsToolError(
                        f"context.{key} must be a non-empty string"
                    )
                normalized_context[key] = (
                    value.strip()
                )

        arguments = call.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise OpenDotsToolError(
                "arguments must be an object"
            )
        return {
            "schema": TOOL_CALL_SCHEMA,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "context": normalized_context,
            "arguments": dict(arguments),
        }


def _load_json(path: str | None) -> dict[str, Any]:
    text = (
        Path(path).read_text(encoding="utf-8")
        if path
        else sys.stdin.read()
    )
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenDotsToolError(
            f"invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise OpenDotsToolError(
            "tool call must be a JSON object"
        )
    return payload


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mado_cockpit.opendots_tools"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="MADO Cockpit repository root",
    )
    parser.add_argument(
        "--file",
        help="Read one tool call from JSON; default is stdin",
    )
    parser.add_argument(
        "--catalog",
        action="store_true",
        help="Print the M1.3 tool catalog",
    )
    args = parser.parse_args(argv)

    if args.catalog:
        print(
            json.dumps(
                {
                    "schema": (
                        "mado.opendots.tool-catalog.v1"
                    ),
                    "surface_version": (
                        TOOL_SURFACE_VERSION
                    ),
                    "tools": tool_catalog(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    store = CockpitStore(
        Path(args.root).resolve()
    )
    surface = OpenDotsToolSurface(store)
    try:
        result = surface.handle(
            _load_json(args.file)
        )
    except OpenDotsToolError as exc:
        print(
            json.dumps(
                {
                    "schema": TOOL_RESULT_SCHEMA,
                    "surface_version": (
                        TOOL_SURFACE_VERSION
                    ),
                    "ok": False,
                    "error": {
                        "code": "invalid_tool_call",
                        "message": str(exc),
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
