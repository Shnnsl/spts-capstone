from datetime import datetime, timedelta

import pytest

from app.models import TabletopTrialMetrics, TabletopTrialRun
from tests.test_plc_trial import post_event


def start(client):
    response = client.post("/plc/trial-start/LINE-01")
    assert response.status_code == 200


def age_run(db_session, seconds=60):
    run = db_session.get(TabletopTrialRun, "LINE-01")
    run.trial_start_time = datetime.utcnow() - timedelta(seconds=seconds)
    db_session.commit()


def submit_inputs(client, count):
    for _ in range(count): assert post_event(client, "INPUT").status_code == 200


def configure_starting_quantity(client, quantity):
    response = client.post("/plc/trial-config/LINE-01", json={
        "ideal_cycle_time_seconds": 2,
        "confirmed_reject_count": 0,
        "starting_input_quantity": quantity,
    })
    assert response.status_code == 200


def test_units_per_case_default_and_configurable(client):
    start(client)
    assert client.get("/plc/trial-status/LINE-01").json()["units_per_case"] == 12
    configured = client.post("/plc/trial-config/LINE-01", json={
        "ideal_cycle_time_seconds": 2, "confirmed_reject_count": 0, "units_per_case": 24,
    }).json()
    assert configured["units_per_case"] == 24


def test_manual_start_waits_for_first_s1_carton(client):
    body = client.post("/plc/trial-start/LINE-01").json()
    assert body["starting_input_quantity"] == 50
    assert body["input_tube_count"] == 0
    assert body["finished_case_count"] == 0
    assert body["finished_tube_equivalent"] == 0
    assert body["unaccounted_tube_count"] == 0
    assert body["finalized_waste_tube_count"] == 0
    assert body["line_status"] == "RUNNING"


def test_case_progression_for_50_tube_batch(client):
    start(client); post_event(client, "INPUT")
    for cases, equivalent, remaining in (
        (1, 12, 38), (2, 24, 26), (3, 36, 14), (4, 48, 2),
    ):
        body = post_event(client, "FINISHED_CASE").json()["status"]
        assert body["finished_case_count"] == cases
        assert body["finished_tube_equivalent"] == equivalent
        assert body["unaccounted_tube_count"] == remaining
    assert post_event(client, "FINISHED_CASE").status_code == 409
    assert client.get("/plc/trial-status/LINE-01").json()["unaccounted_tube_count"] == 2


def test_finalize_50_tubes_and_four_cases(client):
    start(client); post_event(client, "INPUT")
    for _ in range(4):
        assert post_event(client, "FINISHED_CASE").status_code == 200
    body = client.post("/plc/trial-finalize/LINE-01").json()
    assert body["finished_tube_equivalent"] == 48
    assert body["finalized_waste_tube_count"] == 2
    assert body["quality"] == pytest.approx(48 / 50, abs=0.0001)


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_starting_quantity_must_be_a_positive_whole_number(client, quantity):
    response = client.post("/plc/trial-config/LINE-01", json={
        "ideal_cycle_time_seconds": 2,
        "confirmed_reject_count": 0,
        "starting_input_quantity": quantity,
    })
    assert response.status_code == 422


def test_oee_input_save_creates_missing_settings(client):
    response = client.post("/plc/trial-config/LINE-01", json={
        "ideal_cycle_time_seconds": 3, "confirmed_reject_count": 7,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["ideal_cycle_time_seconds"] == 3
    assert body["confirmed_reject_count"] == 7
    assert body["trial_started"] is False


def test_empty_status_has_complete_nonblank_defaults(client):
    body = client.get("/plc/trial-status/LINE-01").json()
    assert body["line_status"] == "READY"
    assert body["trial_started"] is False
    assert body["trial_start_time"] is None
    assert body["oee_valid"] is False
    assert body["validation_message"] == "Not started"
    for key in (
        "trial_elapsed_seconds", "detected_downtime_seconds", "runtime_seconds",
        "input_tube_count", "finished_case_count", "finished_tube_equivalent",
        "unaccounted_tube_count", "finalized_waste_tube_count", "availability",
        "performance", "quality", "overall_oee",
    ):
        assert body[key] == 0


def test_start_is_idempotent_and_does_not_replace_start_time(client, db_session):
    start(client)
    first = db_session.get(TabletopTrialRun, "LINE-01").trial_start_time
    assert client.post("/plc/trial-start/LINE-01").status_code == 200
    db_session.expire_all()
    assert db_session.get(TabletopTrialRun, "LINE-01").trial_start_time == first


def test_timing_becomes_positive_after_start(client, db_session):
    start(client); age_run(db_session, seconds=2)
    body = client.get("/plc/trial-status/LINE-01").json()
    assert body["trial_elapsed_seconds"] > 0
    assert body["runtime_seconds"] > 0


def test_production_calculations_and_no_negative_waste(client):
    configure_starting_quantity(client, 12); start(client); post_event(client, "INPUT"); post_event(client, "FINISHED_CASE")
    status = client.get("/plc/trial-status/LINE-01").json()
    assert status["finished_tube_equivalent"] == 12
    assert status["unaccounted_tube_count"] == 0
    assert status["finalized_waste_tube_count"] == 0
    post_event(client, "FINISHED_CASE")
    assert client.get("/plc/trial-status/LINE-01").json()["unaccounted_tube_count"] == 0


def test_unaccounted_is_not_waste_until_finalized(client):
    configure_starting_quantity(client, 13); start(client); post_event(client, "INPUT"); post_event(client, "FINISHED_CASE")
    active = client.get("/plc/trial-status/LINE-01").json()
    assert active["unaccounted_tube_count"] == 1 and active["finalized_waste_tube_count"] == 0
    final = client.post("/plc/trial-finalize/LINE-01").json()
    assert final["trial_completed"] is True
    assert final["line_status"] == "COMPLETED"
    assert final["finalized_waste_tube_count"] == 1
    assert final["quality"] == pytest.approx(12 / 13, abs=0.0001)


def test_corrected_oee_and_caps(client, db_session):
    configure_starting_quantity(client, 12); start(client); post_event(client, "INPUT"); age_run(db_session); post_event(client, "FINISHED_CASE")
    body = client.post("/plc/trial-finalize/LINE-01").json()
    assert body["quality"] == 1 and 0 <= body["performance"] <= 1
    assert 0 <= body["availability"] <= 1 and 0 <= body["overall_oee"] <= 1


def test_zero_input_quality_is_zero(client):
    start(client)
    assert client.post("/plc/trial-finalize/LINE-01").json()["quality"] == 0


def test_legacy_confirmed_reject_does_not_change_tabletop_quality(client, db_session):
    configure_starting_quantity(client, 12); start(client); post_event(client, "INPUT"); age_run(db_session); post_event(client, "FINISHED_CASE")
    body = client.post("/plc/trial-config/LINE-01", json={
        "ideal_cycle_time_seconds": 2, "confirmed_reject_count": 12,
    }).json()
    assert body["quality"] == 1


def test_downtime_lowers_availability(client, db_session):
    start(client); age_run(db_session); post_event(client, "FILLER_ACTIVE")
    from tests.test_trial_downtime import age_active_sensor
    age_active_sensor(db_session, "FILLER", seconds=20)
    body = client.get("/plc/trial-status/LINE-01").json()
    assert body["detected_downtime_seconds"] > 0 and body["availability"] < 1


def test_reset_clears_corrected_state(client):
    start(client); submit_inputs(client, 1); post_event(client, "FILLER_ACTIVE")
    reset = client.post("/plc/trial-reset/LINE-01").json()
    assert reset["line_status"] == "READY" and reset["input_tube_count"] == 0
    assert reset["filler_sensor_state"] == "CLEAR" and reset["trial_started"] is False
    assert reset["finished_case_count"] == 0 and reset["finished_tube_equivalent"] == 0
    assert reset["finalized_waste_tube_count"] == 0 and reset["active_downtime"] is False
    assert reset["starting_input_quantity"] == 50


def test_closed_history_cannot_affect_reset_current_status(client, db_session):
    start(client); post_event(client, "FILLER_ACTIVE")
    from tests.test_trial_downtime import age_active_sensor
    age_active_sensor(db_session, "FILLER")
    client.get("/plc/trial-status/LINE-01")
    post_event(client, "FILLER_CLEAR")
    reset = client.post("/plc/trial-reset/LINE-01").json()
    assert reset["line_status"] == "READY"
    assert reset["active_downtime"] is False


def test_legacy_oee_endpoint_unchanged(client):
    response = client.post("/oee/calculate", json={
        "planned_production_minutes": 480, "downtime_minutes": 60,
        "ideal_cycle_time": 0.5, "total_count": 700, "good_count": 680,
    })
    assert response.status_code == 200 and response.json()["oee_percent"] == 70.83
