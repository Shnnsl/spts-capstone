from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.dependencies import get_current_user
from app.main import app
from tests.test_plc_trial import post_event


def dashboard_summaries(client):
    supervisor = client.get("/supervisor/summary?line_id=LINE-01")
    manager = client.get("/manager/summary?line_id=LINE-01")
    assert supervisor.status_code == manager.status_code == 200
    return supervisor.json(), manager.json()


def test_dashboard_waste_is_zero_with_no_input(client):
    supervisor, manager = dashboard_summaries(client)
    assert supervisor["tabletop"]["input_tube_count"] == 0
    assert supervisor["waste_percent"] == 0
    assert manager["waste_percent"] == 0


def test_active_wip_is_not_dashboard_waste(client):
    assert post_event(client, "INPUT").status_code == 200
    supervisor, manager = dashboard_summaries(client)
    assert supervisor["tabletop"]["input_tube_count"] == 50
    assert supervisor["tabletop"]["finalized_waste_tube_count"] == 0
    assert supervisor["waste_percent"] == manager["waste_percent"] == 0


def test_supervisor_and_manager_match_authoritative_finalized_tabletop_kpis(client):
    assert post_event(client, "INPUT").status_code == 200
    assert post_event(client, "INPUT").status_code == 200
    for _ in range(8):
        assert post_event(client, "FINISHED_CASE").status_code == 200
    finalized = client.post("/plc/trial-finalize/LINE-01").json()
    assert finalized["input_tube_count"] == 100
    assert finalized["finished_tube_equivalent"] == 96
    assert finalized["finalized_waste_tube_count"] == 4

    supervisor, manager = dashboard_summaries(client)
    expected_oee_percent = round(finalized["overall_oee"] * 100, 2)
    assert supervisor["tabletop"]["overall_oee_percent"] == expected_oee_percent
    assert manager["overall_oee"] == expected_oee_percent
    assert supervisor["waste_percent"] == manager["waste_percent"] == 4
    assert supervisor["tabletop"]["quality_percent"] == pytest.approx(96)
    assert manager["quality"] == pytest.approx(96)


def test_dashboard_downtime_and_approval_kpis_keep_workflow_semantics(client):
    start = datetime.utcnow() - timedelta(minutes=40)
    response = client.post("/downtime", json={
        "line_id": "Line1",
        "machine_id": "FILLER",
        "reason_code": "TEST_BLOCKAGE",
        "start_time": start.isoformat() + "Z",
        "end_time": (start + timedelta(minutes=40)).isoformat() + "Z",
        "source": "PLC",
        "comments": "Dashboard KPI regression",
    })
    assert response.status_code == 200
    event_id = response.json()["event_id"]

    pending = client.get("/supervisor/summary").json()
    manager = client.get("/manager/summary").json()
    assert pending["pending_approvals"] == 1
    assert pending["waiting_over_30_minutes"] == 1
    assert pending["approved_events"] == 0
    assert manager["total_downtime_minutes"] == 40
    assert manager["pending_approvals"] == 1

    assert client.post(f"/downtime/{event_id}/approve").status_code == 200
    approved = client.get("/supervisor/summary").json()
    assert approved["pending_approvals"] == 0
    assert approved["waiting_over_30_minutes"] == 0
    assert approved["approved_events"] == 1
    assert approved["average_approval_time_minutes"] is not None


@pytest.mark.parametrize("route", ["supervisor/summary", "manager/summary"])
def test_dashboard_summary_rbac_remains_intact(client, route):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        username="line-tester", role=SimpleNamespace(name="LINE_WORKSTATION")
    )
    assert client.get(f"/{route}").status_code == 403


def test_dashboard_frontends_use_live_summary_kpis_and_poll(client):
    script = Path("frontend/script.js").read_text(encoding="utf-8")
    supervisor = Path("frontend/supervisor.html").read_text(encoding="utf-8")
    manager = Path("frontend/manager.html").read_text(encoding="utf-8")
    assert "/supervisor/summary?line_id=" in script
    assert "/manager/summary?line_id=" in script
    assert 'id="supervisorWaste"' in supervisor
    assert 'id="managerWaste"' in manager
    assert 'const lines = [getTrialLineId(), "Line1", "Line2", "Line3"]' in script
    assert "setInterval(loadSupervisorDashboard, 10000)" in script
    assert "setInterval(loadManagerDashboard, 10000)" in script
