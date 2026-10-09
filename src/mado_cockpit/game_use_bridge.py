"""MCC-M2.7: engine-neutral game-use contract and deterministic evidence runner.

This module is an independent bridge inspired by OhMyGame's public GameRuntimeAdapter
contract. It is not a client for OhMyGame's private Electron IPC.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

RUNTIMES = frozenset({"web", "godot", "unity"})
INPUTS = frozenset({"pointer", "keyboard", "text", "touch", "resize"})
OBSERVATIONS = frozenset({"screenshot", "dom", "canvas", "console", "network"})
DETERMINISM = frozenset({"snapshot", "reset", "seed", "step"})
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_REPLY_BYTES = 2 * 1024 * 1024
_SAFE_RUN_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}$")


class GameUseError(RuntimeError):
    """An invalid or denied game-use operation."""


@dataclass(frozen=True)
class GameCapabilities:
    runtime: str
    input: tuple[str, ...] = ()
    observation: tuple[str, ...] = ()
    deterministic: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.runtime not in RUNTIMES:
            raise GameUseError(f"Unsupported runtime: {self.runtime}")
        for values, allowed in (
            (self.input, INPUTS),
            (self.observation, OBSERVATIONS),
            (self.deterministic, DETERMINISM),
        ):
            if len(values) != len(set(values)) or set(values) - allowed:
                raise GameUseError("Invalid or duplicate capability")


class GameRuntimeAdapter(Protocol):
    capabilities: GameCapabilities
    requires_authorization: bool

    def request(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


# The live adapter speaks an independent, small HTTP JSON envelope. An
# engine-specific local sidecar must translate this into actual engine calls.
class LocalJsonAdapter:
    requires_authorization = True

    def __init__(self, endpoint: str, capabilities: GameCapabilities, *, timeout: float = 10.0):
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username or parsed.password or not parsed.port or parsed.fragment):
            raise GameUseError("The live endpoint must be explicit localhost HTTP with a port")
        if timeout <= 0 or timeout > 60:
            raise GameUseError("Timeout must be within (0, 60] seconds")
        self.endpoint = endpoint
        self.capabilities = capabilities
        self.timeout = timeout

    def request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if len(body) > MAX_REPLY_BYTES:
            raise GameUseError("Request is too large")
        req = urllib.request.Request(
            self.endpoint, data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, msg, headers, newurl):
                return None

        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=self.timeout) as response:
                # A redirect must not reroute a local command to a remote host.
                if response.geturl() != self.endpoint:
                    raise GameUseError("Redirected game-use endpoint is forbidden")
                raw = response.read(MAX_REPLY_BYTES + 1)
        except (OSError, ValueError) as exc:
            raise GameUseError(f"Game runtime sidecar unavailable: {type(exc).__name__}") from exc
        if len(raw) > MAX_REPLY_BYTES:
            raise GameUseError("Game runtime response is too large")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise GameUseError("Game runtime returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise GameUseError("Game runtime must return an object")
        return result


class DeterministicFixtureAdapter:
    """No engine is launched: reproducible state transitions for protocol smoke tests."""
    requires_authorization = False
    _PNG = base64.b64encode(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg=="
    )).decode("ascii")

    def __init__(self, runtime: str = "web"):
        self.capabilities = GameCapabilities(
            runtime=runtime,
            input=("pointer", "keyboard", "text", "touch", "resize") if runtime == "web" else ("keyboard", "pointer"),
            observation=("screenshot", "dom", "console") if runtime == "web" else ("screenshot", "console"),
            deterministic=("snapshot", "reset", "seed", "step"),
        )
        self.sessions: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        op = payload["operation"]
        if op == "open":
            self._counter += 1
            session = f"fixture-{self._counter}"
            self.sessions[session] = {"seed": 0, "tick": 0, "inputs": [], "viewport": dict(payload["viewport"])}
            return {"operation": op, "snapshot": self._snapshot(session)}
        session = str(payload["sessionId"])
        if session not in self.sessions:
            raise GameUseError("Unknown or closed fixture session")
        state = self.sessions[session]
        if op == "act":
            for action in payload["actions"]:
                if action["type"] == "bridge":
                    method = action["method"]
                    if method == "reset":
                        state["tick"] = 0
                        state["inputs"] = []
                    elif method == "setSeed":
                        state["seed"] = action["value"]
                    elif method == "step":
                        state["tick"] += action["value"]
                elif action["type"] == "resize":
                    state["viewport"] = dict(action["viewport"])
                elif action["type"] != "wait":
                    state["inputs"].append(action["type"])
            return {"operation": op, "snapshot": self._snapshot(session)}
        if op == "inspect":
            return {"operation": op, "snapshot": self._snapshot(session)}
        if op == "capture":
            return {"operation": op, "capture": {
                "sessionId": session, "mediaType": "image/png", "data": self._PNG,
                "width": 1, "height": 1, "analysis": {"likelyBlank": True},
            }}
        if op == "close":
            del self.sessions[session]
            return {"operation": "close"}
        raise GameUseError(f"Invalid operation: {op}")

    def _snapshot(self, session: str) -> dict[str, Any]:
        state = self.sessions[session]
        return {
            "sessionId": session, "runtime": self.capabilities.runtime,
            "viewport": state["viewport"], "gameState": {
                "seed": state["seed"], "tick": state["tick"], "inputs": list(state["inputs"]),
            },
            "bridgeCapabilities": list(self.capabilities.deterministic),
            "logs": [], "failedRequests": [],
        }


def _viewport(value: Any) -> dict[str, int]:
    if not isinstance(value, dict) or set(value) != {"width", "height"}:
        raise GameUseError("Viewport needs width and height")
    for key in ("width", "height"):
        if type(value[key]) is not int or not 1 <= value[key] <= 8192:
            raise GameUseError("Viewport dimensions must be integers between 1 and 8192")
    return dict(value)


def _actions(values: Any, caps: GameCapabilities) -> list[dict[str, Any]]:
    if not isinstance(values, list) or not 1 <= len(values) <= 20:
        raise GameUseError("act requires 1 to 20 actions")
    kinds = {"click": "pointer", "press": "keyboard", "type": "text", "touch": "touch", "resize": "resize"}
    validated = []
    for item in values:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise GameUseError("Every action must be an object with type")
        kind = item["type"]
        allowed_fields = {
            "click": {"type", "target"}, "press": {"type", "key", "duration"},
            "type": {"type", "target", "text"}, "touch": {"type", "x", "y"},
            "resize": {"type", "viewport"}, "wait": {"type", "milliseconds"},
            "bridge": {"type", "method", "value"},
        }
        if kind not in allowed_fields or set(item) - allowed_fields[kind]:
            raise GameUseError("Unknown action or extra action fields")
        if kind in kinds:
            if kinds[kind] not in caps.input:
                raise GameUseError(f"Runtime does not support {kinds[kind]}")
            required = {"click": ("target",), "press": ("key",), "type": ("target", "text"),
                        "touch": ("x", "y"), "resize": ("viewport",)}[kind]
            if any(key not in item for key in required):
                raise GameUseError(f"Missing {kind} action fields")
            if kind == "resize":
                _viewport(item["viewport"])
            if kind == "touch":
                if any(type(item[key]) not in (int, float) or not 0 <= item[key] <= 8192 for key in ("x", "y")):
                    raise GameUseError("Touch coordinates must be within viewport bounds")
            if kind == "press" and "duration" in item and (type(item["duration"]) is not int
                    or not 0 <= item["duration"] <= 5000):
                raise GameUseError("Invalid key hold duration")
            if kind == "press" and (not isinstance(item["key"], str) or not 1 <= len(item["key"]) <= 40):
                raise GameUseError("Invalid press key")
            if kind == "type" and (not isinstance(item["text"], str) or len(item["text"]) > 10000):
                raise GameUseError("Invalid text")
            if kind in {"click", "type"}:
                tgt = item["target"]
                if not isinstance(tgt, dict):
                    raise GameUseError("Invalid target")
                semantic = ({"selector"}, {"testId"}, {"text"}, {"role"}, {"role", "name"})
                coord = {"x", "y"}
                if set(tgt) == coord and kind == "click":
                    if any(type(tgt[key]) not in (int, float) or not 0 <= tgt[key] <= 8192 for key in coord):
                        raise GameUseError("Invalid click coordinates")
                elif set(tgt) in semantic:
                    if any(not isinstance(val, str) or not val.strip() or len(val) > 500 for val in tgt.values()):
                        raise GameUseError("Invalid semantic target")
                    if "dom" not in caps.observation:
                        raise GameUseError("Semantic targets require DOM observation")
                else:
                    raise GameUseError("Invalid target selector shape")
        elif kind == "wait":
            if type(item.get("milliseconds")) is not int or not 0 <= item["milliseconds"] <= 5000:
                raise GameUseError("wait must be between 0 and 5000 milliseconds")
        elif kind == "bridge":
            method = item.get("method")
            required = {"reset": "reset", "setSeed": "seed", "step": "step"}.get(method)
            if not required or required not in caps.deterministic:
                raise GameUseError("Unsupported deterministic bridge method")
            if (method == "reset" and "value" in item):
                raise GameUseError("reset must not include value")
            if method != "reset" and (type(item.get("value")) not in {int, float}
                                      or not -1_000_000 <= item["value"] <= 1_000_000):
                raise GameUseError("Invalid bridge value")
        else:
            raise GameUseError(f"Unknown action: {kind}")
        validated.append(dict(item))
    return validated


class GameUseController:
    """Manage one session; require an explicit policy hook for live mutations."""

    def __init__(self, adapter: GameRuntimeAdapter,
                 authorize: Callable[[str, Mapping[str, Any]], None] | None = None):
        self.adapter = adapter
        self.authorize = authorize
        self.session_id: str | None = None

    def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.adapter.requires_authorization and request["operation"] in {"open", "act"}:
            if self.authorize is None:
                raise GameUseError("Live game execution requires a policy authorizer")
            self.authorize(request["operation"], request)
        result = self.adapter.request(request)
        if not isinstance(result, dict) or result.get("operation") != request["operation"]:
            raise GameUseError("Runtime returned a mismatched operation")
        return result

    def _session(self) -> str:
        if self.session_id is None:
            raise GameUseError("No active game-use session")
        return self.session_id

    def open(self, target: Mapping[str, str], viewport: Mapping[str, int] | None = None) -> dict[str, Any]:
        if self.session_id is not None:
            raise GameUseError("Already opened; close the previous session first")
        runtime = self.adapter.capabilities.runtime
        expected = {"runtime", "url"} if runtime == "web" else {"runtime", "projectPath"}
        if not isinstance(target, Mapping) or set(target) != expected or target.get("runtime") != runtime:
            raise GameUseError("Target does not match adapter runtime")
        field = "url" if runtime == "web" else "projectPath"
        if not isinstance(target[field], str) or not target[field].strip():
            raise GameUseError("Target path or URL must not be empty")
        if runtime == "web":
            parsed = urlsplit(target["url"])
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise GameUseError("Web target must be a safe http(s) URL")
            if self.adapter.requires_authorization and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise GameUseError("Live web target must be a local project preview")
        result = self._request({"operation": "open", "target": dict(target),
                                "viewport": _viewport(dict(viewport or {"width": 1280, "height": 720}))})
        snapshot = self._snapshot(result)
        self.session_id = snapshot["sessionId"]
        return snapshot

    def _snapshot(self, result: dict[str, Any]) -> dict[str, Any]:
        snapshot = result.get("snapshot")
        if not isinstance(snapshot, dict) or snapshot.get("runtime") != self.adapter.capabilities.runtime:
            raise GameUseError("Invalid runtime snapshot")
        if not isinstance(snapshot.get("sessionId"), str) or not snapshot["sessionId"]:
            raise GameUseError("Missing snapshot sessionId")
        if self.session_id is not None and snapshot["sessionId"] != self.session_id:
            raise GameUseError("Snapshot session changed unexpectedly")
        return snapshot

    def inspect(self) -> dict[str, Any]:
        return self._snapshot(self._request({"operation": "inspect", "sessionId": self._session()}))

    def act(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        return self._snapshot(self._request({"operation": "act", "sessionId": self._session(),
                                              "actions": _actions(actions, self.adapter.capabilities)}))

    def capture(self) -> tuple[bytes, dict[str, Any]]:
        if "screenshot" not in self.adapter.capabilities.observation:
            raise GameUseError("Runtime does not support screenshot")
        result = self._request({"operation": "capture", "sessionId": self._session()})
        capture = result.get("capture")
        if (not isinstance(capture, dict) or capture.get("mediaType") != "image/png"
                or capture.get("sessionId") != self.session_id or not isinstance(capture.get("data"), str)
                or len(capture["data"]) > MAX_IMAGE_BYTES * 4 // 3 + 8):
            raise GameUseError("Invalid screenshot envelope")
        try:
            raw = base64.b64decode(capture["data"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise GameUseError("Invalid screenshot base64") from exc
        if len(raw) > MAX_IMAGE_BYTES or not raw.startswith(PNG_SIGNATURE):
            raise GameUseError("Screenshot must be a bounded PNG")
        meta = {key: value for key, value in capture.items() if key != "data"}
        return raw, meta

    def close(self) -> None:
        if self.session_id is not None:
            session = self.session_id
            try:
                self._request({"operation": "close", "sessionId": session})
            finally:
                self.session_id = None


def _assert_subset(expected: Any, actual: Any) -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise GameUseError("Expected a state object")
        for key, value in expected.items():
            if key not in actual:
                raise GameUseError(f"State is missing {key}")
            _assert_subset(value, actual[key])
    elif expected != actual:
        raise GameUseError(f"Expected {expected!r}, got {actual!r}")


def run_scenario(controller: GameUseController, scenario: Mapping[str, Any], output_dir: Path,
                 *, run_id: str | None = None) -> dict[str, Any]:
    """Write self-contained SHA-verifiable playtest evidence; always close the session."""
    run_id = run_id or "gu-" + uuid4().hex[:12]
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise GameUseError("Unsafe run id")
    destination = output_dir / run_id
    destination.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, Any]] = []
    status = "failed"
    error = None

    def record(operation: str, snapshot: dict[str, Any] | None = None,
               screenshot: bytes | None = None, metadata: dict[str, Any] | None = None) -> None:
        index = len(records)
        item: dict[str, Any] = {"index": index, "operation": operation}
        if snapshot is not None:
            raw = json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
            item["snapshot"] = snapshot
            item["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
        if screenshot is not None:
            filename = f"capture_{index:03d}.png"
            (destination / filename).write_bytes(screenshot)
            item.update({"file": filename, "sha256": hashlib.sha256(screenshot).hexdigest(),
                         "capture": metadata})
        records.append(item)

    try:
        initial = controller.open(scenario["target"], scenario.get("viewport"))
        record("open", initial)
        for step in scenario["steps"]:
            operation = step["operation"]
            if operation == "inspect":
                snap = controller.inspect()
                record("inspect", snap)
            elif operation == "act":
                snap = controller.act(step["actions"])
                record("act", snap)
            elif operation == "capture":
                data, meta = controller.capture()
                record("capture", screenshot=data, metadata=meta)
                continue
            else:
                raise GameUseError(f"Scenario step unsupported: {operation}")
            if "expectGameState" in step:
                _assert_subset(step["expectGameState"], snap.get("gameState"))
        status = "passed"
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            controller.close()
        except Exception as exc:
            status = "failed"
            error = (error + "; " if error else "") + f"close: {type(exc).__name__}: {exc}"
        manifest = {"schema": "mcc.game_use.evidence.v1", "run_id": run_id,
                    "runtime": controller.adapter.capabilities.runtime,
                    "capabilities": asdict(controller.adapter.capabilities),
                    "status": status, "error": error, "records": records,
                    "source": "MCC-M2.7 independent adapter contract; not OhMyGame Electron IPC"}
        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return {"status": status, "error": error, "evidence_dir": str(destination),
            "record_count": len(records)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCC-M2.7 game-use fixture and local adapter evidence")
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".mado/game-use"))
    parser.add_argument("--fixture", choices=sorted(RUNTIMES), required=True,
                        help="Run a deterministic fixture; never launches a real game")
    args = parser.parse_args(argv)
    scenario = json.loads(args.scenario.read_text(encoding="utf-8"))
    outcome = run_scenario(GameUseController(DeterministicFixtureAdapter(args.fixture)), scenario, args.output)
    print(json.dumps(outcome, ensure_ascii=False))
    return 0 if outcome["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())