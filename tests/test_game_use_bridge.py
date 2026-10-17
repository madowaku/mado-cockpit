import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from mado_cockpit.game_use_bridge import (
    DeterministicFixtureAdapter,
    GameCapabilities,
    GameUseController,
    GameUseError,
    LocalJsonAdapter,
    run_scenario,
)


def target(runtime):
    return {"runtime": "web", "url": "http://localhost:4173/"} if runtime == "web" else {
        "runtime": runtime, "projectPath": "/tmp/dummy-game"
    }


@pytest.mark.parametrize("runtime", ["web", "godot", "unity"])
def test_all_runtime_contracts_are_deterministic_and_closed(runtime, tmp_path):
    adapter = DeterministicFixtureAdapter(runtime)
    controller = GameUseController(adapter)
    scenario = {
        "target": target(runtime),
        "steps": [
            {"operation": "act", "actions": [
                {"type": "bridge", "method": "setSeed", "value": 17},
                {"type": "press", "key": "Space"},
                {"type": "bridge", "method": "step", "value": 4}],
             "expectGameState": {"seed": 17, "tick": 4, "inputs": ["press"]}},
            {"operation": "capture"},
            {"operation": "act", "actions": [{"type": "bridge", "method": "reset"}],
             "expectGameState": {"tick": 0, "inputs": []}},
        ],
    }
    result = run_scenario(controller, scenario, tmp_path, run_id="test-run")
    assert result["status"] == "passed"
    manifest = json.loads((tmp_path / "test-run" / "manifest.json").read_text())
    assert manifest["schema"] == "mcc.game_use.evidence.v1"
    assert manifest["records"][2]["sha256"]
    assert (tmp_path / "test-run" / manifest["records"][2]["file"]).read_bytes().startswith(b"\x89PNG")
    assert not adapter.sessions


def test_bad_capabilities_and_actions_fail_closed():
    with pytest.raises(GameUseError, match="Invalid or duplicate"):
        GameCapabilities(runtime="web", input=("keyboard", "keyboard"))
    controller = GameUseController(DeterministicFixtureAdapter("godot"))
    with pytest.raises(GameUseError, match="No active"):
        controller.inspect()
    controller.open(target("godot"))
    for actions in ([{"type": "touch", "x": 2, "y": 3}],
                    [{"type": "wait", "milliseconds": 6000}],
                    [{"type": "bridge", "method": "setSeed", "value": "NaN"}],
                    [{"type": "missing"}], []):
        with pytest.raises(GameUseError):
            controller.act(actions)
    controller.close()


def test_failed_assertion_still_leaves_manifest_and_closes(tmp_path):
    adapter = DeterministicFixtureAdapter()
    outcome = run_scenario(GameUseController(adapter), {
        "target": target("web"),
        "steps": [{"operation": "inspect", "expectGameState": {"tick": 99}}],
    }, tmp_path, run_id="failure")
    assert outcome["status"] == "failed"
    assert "Expected 99" in outcome["error"]
    assert not adapter.sessions
    assert json.loads((tmp_path / "failure" / "manifest.json").read_text())["status"] == "failed"


def test_invalid_run_id_cannot_escape_evidence_root(tmp_path):
    with pytest.raises(GameUseError, match="Unsafe run id"):
        run_scenario(GameUseController(DeterministicFixtureAdapter()), {}, tmp_path, run_id="../oops")


def test_http_live_adapter_requires_policy_and_rejects_nonlocal_hosts():
    caps = GameCapabilities(runtime="web", input=("keyboard",), observation=("screenshot",))
    for url in ("https://localhost:7777/use", "http://evil.example:7777/use", "http://localhost/use"):
        with pytest.raises(GameUseError, match="localhost"):
            LocalJsonAdapter(url, caps)
    controller = GameUseController(LocalJsonAdapter("http://127.0.0.1:8777/use", caps))
    with pytest.raises(GameUseError, match="requires a policy authorizer"):
        controller.open(target("web"))


def test_http_transport_with_explicit_authorizer_and_local_sidecar():
    fixture = DeterministicFixtureAdapter()
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = json.loads(body)
            received.append(message["operation"])
            result = fixture.request(message)
            encoded = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        approved = []
        def authorize(op, payload):
            approved.append(op)
        caps = fixture.capabilities
        controller = GameUseController(LocalJsonAdapter(
            f"http://127.0.0.1:{server.server_port}/game-use", caps), authorize)
        snap = controller.open(target("web"))
        assert snap["gameState"]["tick"] == 0
        assert controller.act([{"type": "bridge", "method": "step", "value": 2}])["gameState"]["tick"] == 2
        picture, meta = controller.capture()
        assert picture.startswith(b"\x89PNG") and meta["sessionId"]
        controller.close()
        assert approved == ["open", "act"]
        assert received == ["open", "act", "capture", "close"]
        assert not fixture.sessions
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_policy_hook_denial_prevents_side_effects():
    class FakeLive(DeterministicFixtureAdapter):
        requires_authorization = True
    backend = FakeLive()
    def deny(_op, _payload):
        raise GameUseError("denied")
    controller = GameUseController(backend, authorize=deny)
    with pytest.raises(GameUseError, match="denied"):
        controller.open(target("web"))
    assert not backend.sessions
