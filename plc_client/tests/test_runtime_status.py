from datetime import datetime

from runtime_status import RuntimeStatus
from terminal_status import format_status


def test_runtime_status_updates_delivery_retry_queue_and_sensors():
    status = RuntimeStatus()
    status.update(queue_depth=2)
    status.increment("retry_count")
    status.sensor_changed("S2", True)
    event = {"event_id": "event-1", "event_type": "SENSOR_ACTIVE", "sensor_id": "S2", "station": "FILLER"}
    status.event_delivered(event, 1)
    snapshot = status.snapshot()
    assert snapshot["delivered_count"] == 1
    assert snapshot["retry_count"] == 1
    assert snapshot["queue_depth"] == 1
    assert snapshot["sensor_states"]["S2"] == "ACTIVE"
    assert isinstance(snapshot["last_successful_communication"], datetime)


def test_terminal_formatter_contains_no_secrets():
    status = RuntimeStatus()
    rendered = format_status(status.snapshot(), "LINE-01")
    assert "password" not in rendered.lower()
    assert "authorization" not in rendered.lower()
    assert "jwt" not in rendered.lower()
