from pathlib import Path
from uuid import uuid4

from event_queue import EventQueue


def test_queue_is_fifo_durable_and_idempotent():
    path = Path(__file__).with_name(f"queue-{uuid4()}.sqlite3")
    try:
        queue = EventQueue(path)
        first = {"event_id": "one", "value": 1}
        second = {"event_id": "two", "value": 2}
        assert queue.put(first) is True
        assert queue.put(first) is False
        assert queue.put(second) is True
        assert EventQueue(path).peek() == first
        queue.remove("one")
        assert queue.peek() == second
    finally:
        path.unlink(missing_ok=True)


def test_dead_letters_survive_restart_without_secrets():
    path = Path(__file__).with_name(f"queue-{uuid4()}.sqlite3")
    try:
        queue = EventQueue(path)
        event = {"event_id": "bad-one", "sensor_id": "S1", "event_type": "PRODUCT_DETECTED"}
        queue.put(event)
        queue.dead_letter(event, "Backend rejected event", 422)
        records = EventQueue(path).list_dead_letters()
        assert len(records) == 1
        assert records[0]["event_id"] == "bad-one"
        assert records[0]["http_status"] == 422
        assert records[0]["reason"] == "Backend rejected event"
        assert "password" not in str(records).lower()
    finally:
        path.unlink(missing_ok=True)
