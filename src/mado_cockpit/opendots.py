from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Protocol

from .models import Event, utc_now
from .operator import OperatorManager
from .store import CockpitStore


SCHEMA = "mado.opendots.runtime.v1"
ADAPTER_VERSION = "MCC-M1.2"
_ALLOWED_ACTIONS = {
    "operator.status",
    "operator.advance",
    "gate.resolve",
}
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class OpenDotsAdapterError(RuntimeError):
    """Raised when an OpenDots envelope violates the adapter contract."""


class CockpitRuntime(Protocol):
    def inspect(self, operator_id: str) -> dict[str, Any]: ...

    def advance(self, operator_id: str) -> dict[str, Any]: ...

    def resolve_gate(
        self,
        operator_id: str,
        *,
        choice: str | None = None,
        choose_for_me: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]: ...


class OpenDotsRuntimeAdapter:
    """Translate bounded OpenDots requests into deterministic Cockpit actions."""

    def __init__(
        self,
        store: CockpitStore,
        *,
        runtime: CockpitRuntime | None = None,
    ) -> None:
        self.store = store
        self.runtime = runtime or OperatorManager(store)
        self.receipts_dir = (
            store.base
            / "integrations"
            / "opendots"
            / "receipts"
        )

    def handle(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        envelope = self._validate_request(request)
        request_id = envelope["request_id"]
        digest = self._request_digest(envelope)
        receipt_path = self.receipts_dir / f"{request_id}.json"

        if receipt_path.exists():
            receipt = self._read_json(receipt_path)
            if receipt.get("request_sha256") != digest:
                raise OpenDotsAdapterError(
                    "request_id was already used with different content"
                )
            self._event(
                "opendots.request.replayed",
                envelope,
                status=receipt["response"]["status"],
            )
            return receipt["response"]

        try:
            data = self._dispatch(envelope)
        except OpenDotsAdapterError:
            raise
        except RuntimeError as exc:
            response = self._response(
                envelope,
                status="error",
                error={
                    "code": "cockpit_runtime_error",
                    "message": str(exc),
                },
            )
        else:
            response = self._response(
                envelope,
                status="ok",
                data=data,
            )

        receipt = {
            "schema": SCHEMA,
            "adapter_version": ADAPTER_VERSION,
            "request_sha256": digest,
            "request": envelope,
            "response": response,
            "recorded_at": utc_now(),
        }
        self._write_json(receipt_path, receipt)
        self._event(
            "opendots.request.completed",
            envelope,
            status=response["status"],
        )
        return response

    def _dispatch(
        self,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        action = request["action"]
        operator_id = request["target"]["operator_id"]
        payload = request["payload"]

        if action == "operator.status":
            self._require_empty_payload(payload, action)
            return self.runtime.inspect(operator_id)

        if action == "operator.advance":
            self._require_empty_payload(payload, action)
            return self.runtime.advance(operator_id)

        if action == "gate.resolve":
            allowed = {"choice", "choose_for_me", "note"}
            unknown = set(payload) - allowed
            if unknown:
                raise OpenDotsAdapterError(
                    "gate.resolve payload has unsupported fields: "
                    + ", ".join(sorted(unknown))
                )

            choice = payload.get("choice")
            choose_for_me = payload.get("choose_for_me", False)
            note = payload.get("note")

            if choice is not None and (
                not isinstance(choice, str) or not choice.strip()
            ):
                raise OpenDotsAdapterError(
                    "gate.resolve choice must be a non-empty string"
                )
            if not isinstance(choose_for_me, bool):
                raise OpenDotsAdapterError(
                    "gate.resolve choose_for_me must be boolean"
                )
            if note is not None and not isinstance(note, str):
                raise OpenDotsAdapterError(
                    "gate.resolve note must be a string"
                )
            if bool(choice) == choose_for_me:
                raise OpenDotsAdapterError(
                    "gate.resolve requires exactly one of choice or choose_for_me"
                )

            return self.runtime.resolve_gate(
                operator_id,
                choice=choice.strip() if choice else None,
                choose_for_me=choose_for_me,
                note=note,
            )

        raise OpenDotsAdapterError(
            f"unsupported OpenDots action: {action}"
        )

    def _validate_request(
        self,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise OpenDotsAdapterError(
                "OpenDots request must be a JSON object"
            )

        allowed = {
            "schema",
            "request_id",
            "action",
            "source",
            "target",
            "payload",
        }
        unknown = set(request) - allowed
        if unknown:
            raise OpenDotsAdapterError(
                "OpenDots request has unsupported fields: "
                + ", ".join(sorted(unknown))
            )

        if request.get("schema") != SCHEMA:
            raise OpenDotsAdapterError(
                f"schema must be {SCHEMA}"
            )

        request_id = request.get("request_id")
        if (
            not isinstance(request_id, str)
            or not _REQUEST_ID.fullmatch(request_id)
        ):
            raise OpenDotsAdapterError(
                "request_id must be 1-128 safe identifier characters"
            )

        action = request.get("action")
        if action not in _ALLOWED_ACTIONS:
            raise OpenDotsAdapterError(
                "action is not allowed by MCC-M1.2: "
                f"{action!r}"
            )

        source = request.get("source")
        if not isinstance(source, Mapping):
            raise OpenDotsAdapterError(
                "source must be an object"
            )
        source_allowed = {
            "dot_id",
            "space_id",
            "thread_id",
        }
        source_unknown = set(source) - source_allowed
        if source_unknown:
            raise OpenDotsAdapterError(
                "source has unsupported fields: "
                + ", ".join(sorted(source_unknown))
            )
        dot_id = source.get("dot_id")
        if not isinstance(dot_id, str) or not dot_id.strip():
            raise OpenDotsAdapterError(
                "source.dot_id is required"
            )
        normalized_source: dict[str, Any] = {
            "dot_id": dot_id.strip()
        }
        for key in ("space_id", "thread_id"):
            value = source.get(key)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise OpenDotsAdapterError(
                        f"source.{key} must be a non-empty string"
                    )
                normalized_source[key] = value.strip()

        target = request.get("target")
        if not isinstance(target, Mapping):
            raise OpenDotsAdapterError(
                "target must be an object"
            )
        if set(target) != {"operator_id"}:
            raise OpenDotsAdapterError(
                "target must contain only operator_id"
            )
        operator_id = target.get("operator_id")
        if (
            not isinstance(operator_id, str)
            or not operator_id.strip()
        ):
            raise OpenDotsAdapterError(
                "target.operator_id is required"
            )

        payload = request.get("payload", {})
        if not isinstance(payload, Mapping):
            raise OpenDotsAdapterError(
                "payload must be an object"
            )

        return {
            "schema": SCHEMA,
            "request_id": request_id,
            "action": action,
            "source": normalized_source,
            "target": {
                "operator_id": operator_id.strip()
            },
            "payload": dict(payload),
        }

    @staticmethod
    def _require_empty_payload(
        payload: Mapping[str, Any],
        action: str,
    ) -> None:
        if payload:
            raise OpenDotsAdapterError(
                f"{action} does not accept payload fields"
            )

    @staticmethod
    def _request_digest(
        request: Mapping[str, Any],
    ) -> str:
        canonical = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    def _response(
        self,
        request: Mapping[str, Any],
        *,
        status: str,
        data: dict[str, Any] | None = None,
        error: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        response: dict[str, Any] = {
            "schema": SCHEMA,
            "adapter_version": ADAPTER_VERSION,
            "request_id": request["request_id"],
            "action": request["action"],
            "status": status,
            "completed_at": utc_now(),
        }
        if data is not None:
            response["data"] = data
        if error is not None:
            response["error"] = error
        return response

    def _event(
        self,
        event_type: str,
        request: Mapping[str, Any],
        *,
        status: str,
    ) -> None:
        self.store.append_event(
            Event(
                type=event_type,
                actor="opendots",
                subject={
                    "request_id": request["request_id"],
                    "action": request["action"],
                    "dot_id": request["source"]["dot_id"],
                    "operator_id": request["target"]["operator_id"],
                    "status": status,
                },
            )
        )

    @staticmethod
    def _write_json(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return json.loads(
            path.read_text(encoding="utf-8")
        )


def _load_request(path: str | None) -> dict[str, Any]:
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenDotsAdapterError(
            f"invalid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise OpenDotsAdapterError(
            "OpenDots request must be a JSON object"
        )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mado_cockpit.opendots"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="MADO Cockpit repository root",
    )
    parser.add_argument(
        "--file",
        help="Read one OpenDots request from a JSON file; default is stdin",
    )
    args = parser.parse_args(argv)

    store = CockpitStore(Path(args.root).resolve())
    adapter = OpenDotsRuntimeAdapter(store)
    try:
        response = adapter.handle(
            _load_request(args.file)
        )
    except OpenDotsAdapterError as exc:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "adapter_version": ADAPTER_VERSION,
                    "status": "rejected",
                    "error": {
                        "code": "invalid_request",
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
            response,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if response["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
