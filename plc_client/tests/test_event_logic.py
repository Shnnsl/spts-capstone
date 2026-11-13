from uuid import UUID

from event_logic import SENSORS, TransitionProcessor, create_event


def test_event_creation_and_uuid():
    event = create_event(SENSORS["S1"], "PRODUCT_DETECTED", "LINE-01")
    assert UUID(event["event_id"])
    assert event["source"] == "RASPBERRY_PI"
    assert event["event_time"].endswith("Z")


def test_count_sensor_only_clear_to_active():
    events = []
    processor = TransitionProcessor("LINE-01", events.append)
    processor.initialize("S1", False)
    processor.update("S1", True)
    processor.update("S1", True)
    processor.update("S1", False)
    processor.update("S1", True)
    assert [e["event_type"] for e in events] == ["PRODUCT_DETECTED", "PRODUCT_DETECTED"]


def test_state_sensor_emits_each_distinct_state_once():
    events = []
    processor = TransitionProcessor("LINE-01", events.append)
    processor.initialize("S2", False)
    processor.update("S2", True)
    processor.update("S2", True)
    processor.update("S2", False)
    processor.update("S2", False)
    assert [e["event_type"] for e in events] == ["SENSOR_ACTIVE", "SENSOR_CLEAR"]
