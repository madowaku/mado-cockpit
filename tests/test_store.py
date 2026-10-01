from mado_cockpit.models import Mission, Project, Worker
from mado_cockpit.store import CockpitStore


def test_golden_m0_skeleton(tmp_path):
    store = CockpitStore(tmp_path)

    store.init(Project(id="fixture", name="Fixture Project", root=str(tmp_path)))
    store.save_mission(Mission(id="MCC-DEMO", title="Demo mission"))
    store.save_worker(Worker(id="builder", role="builder", mission_id="MCC-DEMO"))

    snapshot = store.snapshot()

    assert snapshot["project"]["id"] == "fixture"
    assert snapshot["missions"][0]["id"] == "MCC-DEMO"
    assert snapshot["workers"][0]["role"] == "builder"
    assert snapshot["event_count"] == 3
