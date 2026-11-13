"""Thread-safe, secret-free runtime status."""
from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime, timezone


class RuntimeStatus:
    def __init__(self, sensor_ids=("S1", "S2", "S3", "S4", "S5")):
        self._lock = threading.RLock()
        self._data = {
            "api_reachable": False,
            "authenticated": False,
            "api_version": None,
            "queue_depth": 0,
            "last_successful_communication": None,
            "last_event_type": None,
            "last_event_id": None,
            "last_sensor_id": None,
            "last_station": None,
            "delivered_count": 0,
            "retry_count": 0,
            "dead_letter_count": 0,
            "sensor_states": {sensor_id: "UNKNOWN" for sensor_id in sensor_ids},
        }

    def update(self, **values) -> None:
        with self._lock:
            unknown = values.keys() - self._data.keys()
            if unknown:
                raise KeyError(f"Unknown status fields: {sorted(unknown)}")
            self._data.update(values)

    def increment(self, field: str, amount: int = 1) -> None:
        with self._lock:
            self._data[field] += amount

    def communication_succeeded(self, authenticated: bool | None = None) -> None:
        values = {"api_reachable": True, "last_successful_communication": datetime.now(timezone.utc)}
        if authenticated is not None:
            values["authenticated"] = authenticated
        self.update(**values)

    def sensor_changed(self, sensor_id: str, active: bool) -> None:
        with self._lock:
            self._data["sensor_states"][sensor_id] = "ACTIVE" if active else "CLEAR"

    def event_delivered(self, event: dict, queue_depth: int) -> None:
        with self._lock:
            self._data.update(
                queue_depth=queue_depth,
                last_event_type=event["event_type"],
                last_event_id=event["event_id"],
                last_sensor_id=event["sensor_id"],
                last_station=event["station"],
                api_reachable=True,
                authenticated=True,
                last_successful_communication=datetime.now(timezone.utc),
            )
            self._data["delivered_count"] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._data)
