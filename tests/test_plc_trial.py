from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.dependencies import get_current_user
from app.main import app, downtime_events
from app.models import ProductionEvent, Role, TabletopTrialMetrics, TabletopTrialRun


EVENTS = {
    "INPUT": ("INPUT", "S1", 17, "PRODUCT_DETECTED"),
    "FILLER_ACTIVE": ("FILLER", "S2", 27, "SENSOR_ACTIVE"),
    "FILLER_CLEAR": ("FILLER", "S2", 27, "SENSOR_CLEAR"),
    "CARTONER_ACTIVE": ("CARTONER", "S3", 22, "SENSOR_ACTIVE"),
    "CARTONER_CLEAR": ("CARTONER", "S3", 22, "SENSOR_CLEAR"),
    "CASE_ACTIVE": ("CASE_PACKER", "S4", 23, "SENSOR_ACTIVE"),
    "CASE_CLEAR": ("CASE_PACKER", "S4", 23, "SENSOR_CLEAR"),
    "FINISHED_CASE": ("FINISHED_GOODS", "S5", 24, "CASE_DETECTED"),
}


def post_event(client, name, event_id=None, line_id="LINE-01", **changes):
    station, sensor, pin, event_type = EVENTS[name]
    body = {
        "event_id": event_id or str(uuid4()), "line_id": line_id,
        "station": station, "sensor_id": sensor, "gpio_pin": pin,
        "event_type": event_type, "event_time": datetime.utcnow().isoformat() + "Z",
        "source": "DEVELOPMENT_SIMULATOR",
    }
    body.update(changes)
    return client.post("/plc/production-event", json=body)


def test_s1_is_logged_without_changing_authoritative_batch_and_s5_counts_cases(client, db_session):
    assert client.post("/plc/trial-start/LINE-01").status_code == 200
    response = post_event(client, "INPUT")
    assert response.status_code == 200
    assert db_session.query(ProductionEvent).filter_by(station="INPUT").count() == 1
    body = post_event(client, "FINISHED_CASE").json()["status"]
    assert body["input_tube_count"] == 50
    assert body["finished_case_count"] == 1
    assert body["finished_tube_equivalent"] == 12


@pytest.mark.parametrize("name", ["FILLER_ACTIVE", "FILLER_CLEAR", "CARTONER_ACTIVE", "CARTONER_CLEAR", "CASE_ACTIVE", "CASE_CLEAR"])
def test_machine_sensor_events_do_not_increment_production(client, name):
    body = post_event(client, name).json()["status"]
    assert body["input_tube_count"] == body["finished_case_count"] == 0
    assert body["finished_tube_equivalent"] == 0


@pytest.mark.parametrize("name,changes", [
    ("INPUT", {"event_type": "CASE_DETECTED"}),
    ("FINISHED_CASE", {"event_type": "PRODUCT_DETECTED"}),
    ("FILLER_ACTIVE", {"event_type": "PRODUCT_DETECTED"}),
    ("CARTONER_ACTIVE", {"sensor_id": "S2"}),
    ("CASE_ACTIVE", {"gpio_pin": 24}),
])
def test_invalid_combinations_return_400(client, name, changes):
    assert post_event(client, name, **changes).status_code == 400


def test_duplicate_event_is_idempotent(client):
    event_id = str(uuid4())
    assert post_event(client, "INPUT", event_id=event_id).status_code == 200
    duplicate = post_event(client, "INPUT", event_id=event_id).json()
    assert duplicate["duplicate"] is True
    assert duplicate["status"]["input_tube_count"] == 50
    assert duplicate["status"]["input_count"] == 1


def test_first_s1_auto_starts_batch_and_retries_do_not_restart(client, db_session):
    ready = client.post("/plc/trial-reset/LINE-01").json()
    assert ready["line_status"] == "READY"
    assert ready["trial_started"] is False

    first_event_id = str(uuid4())
    first_response = post_event(client, "INPUT", event_id=first_event_id)
    assert first_response.status_code == 200
    first = first_response.json()["status"]
    assert first["trial_started"] is True
    assert first["line_status"] == "RUNNING"
    assert first["input_tube_count"] == 50
    assert first["trial_start_time"] is not None
    run = db_session.get(TabletopTrialRun, "LINE-01")
    run.trial_start_time = datetime.utcnow() - timedelta(seconds=2)
    db_session.commit()
    original_start_time = run.trial_start_time
    assert client.get("/plc/trial-status/LINE-01").json()["runtime_seconds"] > 0

    second = post_event(client, "INPUT").json()["status"]
    assert second["input_tube_count"] == 100
    db_session.expire_all()
    assert db_session.get(TabletopTrialRun, "LINE-01").trial_start_time == original_start_time

    third = post_event(client, "INPUT").json()["status"]
    assert third["input_tube_count"] == 150
    db_session.expire_all()
    assert db_session.get(TabletopTrialRun, "LINE-01").trial_start_time == original_start_time

    duplicate = post_event(client, "INPUT", event_id=first_event_id).json()
    assert duplicate["duplicate"] is True
    assert duplicate["status"]["input_tube_count"] == 150
    db_session.expire_all()
    assert db_session.get(TabletopTrialRun, "LINE-01").trial_start_time == original_start_time

    finished = post_event(client, "FINISHED_CASE").json()["status"]
    assert finished["finished_case_count"] == 1
    assert finished["finished_tube_equivalent"] == 12
    assert finished["unaccounted_tube_count"] == 138

    reset = client.post("/plc/trial-reset/LINE-01").json()
    assert reset["line_status"] == "READY" and reset["trial_started"] is False
    restarted = post_event(client, "INPUT").json()["status"]
    assert restarted["line_status"] == "RUNNING"
    assert restarted["input_tube_count"] == 50


def test_first_s1_creates_exactly_one_metrics_row_with_production_autoflush_disabled(client, db_session):
    # SessionLocal runs with autoflush=False in production. This reproduces the
    # lifecycle that previously accumulated three pending metrics objects.
    db_session.autoflush = False
    assert db_session.query(TabletopTrialMetrics).filter_by(line_id="LINE-01").count() == 0

    response = post_event(client, "INPUT")
    assert response.status_code == 200
    body = response.json()["status"]
    rows = db_session.query(TabletopTrialMetrics).filter_by(line_id="LINE-01").all()
    assert len(rows) == 1
    assert rows[0].starting_input_quantity == 50
    assert rows[0].input_tube_count == 50
    assert body["trial_started"] is True
    assert body["line_status"] == "RUNNING"

    assert client.post("/plc/trial-reset/LINE-01").status_code == 200
    assert db_session.query(TabletopTrialMetrics).filter_by(line_id="LINE-01").count() == 0
    restarted = post_event(client, "INPUT")
    assert restarted.status_code == 200
    rows = db_session.query(TabletopTrialMetrics).filter_by(line_id="LINE-01").all()
    assert len(rows) == 1
    assert rows[0].starting_input_quantity == rows[0].input_tube_count == 50


def test_line_workstation_s1_can_auto_start_without_manual_start_permission(client):
    set_role("LINE_WORKSTATION")
    assert client.post("/plc/trial-start/LINE-01").status_code == 403
    response = post_event(client, "INPUT")
    assert response.status_code == 200
    assert response.json()["status"]["line_status"] == "RUNNING"
    assert response.json()["status"]["input_tube_count"] == 50


def test_unauthorized_event(client):
    app.dependency_overrides.pop(get_current_user)
    assert post_event(client, "INPUT").status_code in (401, 403)


@pytest.mark.parametrize("route", ["trial-start", "trial-config"])
def test_protected_trial_endpoints_require_authentication(client, route):
    app.dependency_overrides.pop(get_current_user)
    if route == "trial-config":
        response = client.post("/plc/trial-config/LINE-01", json={
            "ideal_cycle_time_seconds": 2, "confirmed_reject_count": 0,
            "starting_input_quantity": 50,
        })
    else:
        response = client.post("/plc/trial-start/LINE-01")
    assert response.status_code in (401, 403)


def test_reset_is_line_scoped_and_preserves_unrelated_data(client, db_session):
    db_session.add(Role(name="PRESERVE_ME")); db_session.commit()
    post_event(client, "INPUT"); post_event(client, "INPUT", line_id="LINE-02")
    downtime_events[99999] = "preserve"
    reset = client.post("/plc/trial-reset/LINE-01")
    assert reset.status_code == 200 and reset.json()["input_tube_count"] == 0
    assert db_session.query(Role).filter_by(name="PRESERVE_ME").count() == 1
    assert db_session.query(ProductionEvent).filter_by(line_id="LINE-02").count() == 1
    assert downtime_events.pop(99999) == "preserve"


def set_role(role):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        username=f"{role.lower()}-tester", role=SimpleNamespace(name=role)
    )


@pytest.mark.parametrize("route", ["trial-reset", "trial-finalize"])
def test_line_workstation_cannot_reset_or_finalize(client, route):
    set_role("LINE_WORKSTATION")
    assert client.post(f"/plc/{route}/LINE-01").status_code == 403


def test_frontend_uses_correct_semantics():
    page = Path("frontend/line.html").read_text(encoding="utf-8")
    script = Path("frontend/script.js").read_text(encoding="utf-8")
    styles = Path("frontend/style.css").read_text(encoding="utf-8")
    assert "Input Tubes" in page and "Finished Cases" in page
    assert 'id="trialFillerCount"' not in page
    assert "SENSOR_ACTIVE" in script and "SENSOR_CLEAR" in script and "CASE_DETECTED" in script
    assert "Number(value ?? fallback)" in script
    assert "TABLETOP_UI_VERSION" in script
    assert 'if (document.getElementById("trialInputTubeCount")) return;' in script
    assert 'id="liveLineStatusPanel"' in page
    assert 'id="liveLineFlow"' in page
    assert 'data-flow-station="FILLER"' in page
    assert "Product blockage detected at" in script
    assert script.count("setInterval(loadTrialStatus, 5000)") == 1
    assert "prefers-reduced-motion: reduce" in styles


def test_non_s1_event_before_start_does_not_make_line_running(client):
    post_event(client, "FILLER_ACTIVE")
    body = client.get("/plc/trial-status/LINE-01").json()
    assert body["line_status"] == "READY"
    assert body["trial_started"] is False
