import json
from pathlib import Path
from typing import Sequence

import pytest

from mado_cockpit.providers.base import CommandResult
from mado_cockpit.providers.opencode import MINIMAX_FREE_MODEL, OpenCodeCLIProvider


class Runner:
    def __init__(self, *results: CommandResult):
        self.results = list(results)
        self.calls = []

    def run(self, args: Sequence[str], *, cwd: Path) -> CommandResult:
        self.calls.append((list(args), cwd))
        return self.results.pop(0)


def output(session="ses_123", message="Done"):
    return "\n".join([
        json.dumps({"type": "step_start", "sessionID": session}),
        json.dumps({"type": "text", "sessionID": session,
                    "part": {"type": "text", "text": message}}),
    ]) + "\n"


def test_start_and_resume():
    runner = Runner(CommandResult(0, output(), ""),
                    CommandResult(0, output(message="Again"), ""))
    provider = OpenCodeCLIProvider(runner=runner)
    workspace = Path("/tmp/fixture")
    first = provider.start(workspace=workspace, prompt="Build")
    second = provider.send(workspace=workspace, prompt="Test",
                           external_session_id=first.external_session_id)
    assert first.external_session_id == "ses_123"
    assert first.last_message == "Done"
    assert second.last_message == "Again"
    assert runner.calls[0][0] == [
        "opencode", "run", "--format", "json", "--model",
        MINIMAX_FREE_MODEL, "Build"]
    assert runner.calls[1][0][-3:] == ["--session", "ses_123", "Test"]


def test_paid_model_fails_before_execution():
    runner = Runner()
    provider = OpenCodeCLIProvider(runner=runner)
    with pytest.raises(ValueError, match="explicitly free"):
        provider.start(workspace=Path("."), prompt="Hi", model="anthropic/claude")
    assert runner.calls == []


def test_conflicting_session_ids_fail_closed():
    runner = Runner(CommandResult(0,
        output("ses_one") + output("ses_two"), ""))
    with pytest.raises(RuntimeError, match="conflicting"):
        OpenCodeCLIProvider(runner=runner).start(workspace=Path("."), prompt="Hi")


def test_no_session_id_does_not_invent_one():
    runner = Runner(CommandResult(0, '{"type":"step_finish"}\n', ""))
    result = OpenCodeCLIProvider(runner=runner).start(
        workspace=Path("."), prompt="Hi")
    assert result.external_session_id is None


def test_invalid_resume_id_is_rejected():
    runner = Runner()
    with pytest.raises(ValueError, match="Invalid"):
        OpenCodeCLIProvider(runner=runner).send(
            workspace=Path("."), external_session_id="wrong", prompt="Hi")
