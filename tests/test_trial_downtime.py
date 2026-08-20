from datetime import datetime, timedelta

import pytest

from app.models import TabletopTrialDowntime, TabletopTrialSensorState
from tests.test_plc_trial import post_event


def start(client):
    assert client.post("/plc/trial-start/LINE-01").status_code == 200


def age_active_sensor(db_session, station, seconds=11):
    sensor = db_session.query(TabletopTrialSensorState).filter_by(line_id="LINE-01", station=station).one()
    sensor.active_since = datetime.utcnow() - timedelta(seconds=seconds)
    sensor.timeout_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()


def test_brief_active_clear_creates_no_downtime(client):
    start(client)
    post_event(client, "FILLER_ACTIVE"); result = post_event(client, "FILLER_CLEAR").json()["status"]
    assert result["active_downtime"] is False
    assert result["recent_downtime_events"] == []


@pytest.mark.parametrize("active_name,clear_name,station", [
    ("FILLER_ACTIVE", "FILLER_CLEAR", "FILLER"),
    ("CARTONER_ACTIVE", "CARTONER_CLEAR", "CARTONER"),
    ("CASE_ACTIVE", "CASE_CLEAR", "CASE_PACKER"),
])
def test_overdue_blockage_opens_and_same_sensor_clear_closes(client, db_session, active_name, clear_name, station):
    start(client); post_event(client, active_name); age_active_sensor(db_session, station)
    opened = client.get("/plc/trial-status/LINE-01").json()
    assert opened["active_downtime"] is True and opened["affected_station"] == station
    assert opened["line_status"] == "DOWNTIME"
    closed = post_event(client, clear_name).json()["status"]
    assert closed["active_downtime"] is False
    assert closed["line_status"] == "RUNNING"
    assert closed["recent_downtime_events"][0]["status"] == "CLOSED"
    assert closed["recent_downtime_events"][0]["duration_seconds"] >= 1


def test_restart_safe_recovery_uses_persisted_deadline(client, db_session):
    start(client); post_event(client, "FILLER_ACTIVE"); age_active_sensor(db_session, "FILLER")
    db_session.expire_all()
    assert client.get("/plc/trial-status/LINE-01").json()["active_downtime"] is True


def test_s1_and_s5_never_create_machine_downtime(client, db_session):
    start(client); post_event(client, "INPUT"); post_event(client, "FINISHED_CASE")
    assert db_session.query(TabletopTrialDowntime).count() == 0
