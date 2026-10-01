import json

from mado_cockpit.cli import main


def test_cli_golden_path(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "init",
                "--project-id",
                "fixture",
                "--name",
                "Fixture",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "mission",
                "create",
                "MCC-DEMO",
                "Demo mission",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "worker",
                "create",
                "builder",
                "--role",
                "builder",
                "--mission",
                "MCC-DEMO",
            ]
        )
        == 0
    )

    capsys.readouterr()
    assert main(["status"]) == 0
    output = capsys.readouterr().out
    snapshot = json.loads(output)

    assert snapshot["project"]["name"] == "Fixture"
    assert len(snapshot["missions"]) == 1
    assert len(snapshot["workers"]) == 1
    assert snapshot["workspaces"] == []
    assert snapshot["event_count"] == 3
