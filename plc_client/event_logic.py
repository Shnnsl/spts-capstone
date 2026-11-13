"""Pure event creation and sensor transition rules."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4


@dataclass(frozen=True)
class SensorDefinition:
    sensor_id: str
    gpio_pin: int
    station: str
    kind: str
    active_event: str


FIXED_SENSOR_MAPPING = (
    SensorDefinition("S1", 17, "INPUT", "count", "PRODUCT_DETECTED"),
    SensorDefinition("S2", 27, "FILLER", "state", "SENSOR_ACTIVE"),
    SensorDefinition("S3", 22, "CARTONER", "state", "SENSOR_ACTIVE"),
    SensorDefinition("S4", 23, "CASE_PACKER", "state", "SENSOR_ACTIVE"),
    SensorDefinition("S5", 24, "FINISHED_GOODS", "count", "CASE_DETECTED"),
)
SENSORS = {sensor.sensor_id: sensor for sensor in FIXED_SENSOR_MAPPING}


def validate_sensor_mapping(mapping=FIXED_SENSOR_MAPPING) -> None:
    mapping = tuple(mapping)
    ids = [sensor.sensor_id for sensor in mapping]
    pins = [sensor.gpio_pin for sensor in mapping]
    if len(ids) != len(set(ids)):
        raise ValueError("Sensor IDs must be unique")
    if len(pins) != len(set(pins)):
        raise ValueError("GPIO pins must be unique")
    expected = {sensor.sensor_id: sensor for sensor in FIXED_SENSOR_MAPPING}
    if set(ids) != set(expected):
        raise ValueError("Mapping must define exactly S1 through S5")
    for sensor in mapping:
        reference = expected[sensor.sensor_id]
        if sensor.gpio_pin != reference.gpio_pin:
            raise ValueError(f"{sensor.sensor_id} must use GPIO{reference.gpio_pin}")
        if sensor.station != reference.station:
            raise ValueError(f"{sensor.sensor_id} must use station {reference.station}")
        if sensor.kind != reference.kind or sensor.active_event != reference.active_event:
            raise ValueError(f"{sensor.sensor_id} has incompatible count/state semantics")


def create_event(sensor: SensorDefinition, event_type: str, line_id: str) -> dict:
    return {
        "event_id": str(uuid4()),
        "line_id": line_id,
        "station": sensor.station,
        "sensor_id": sensor.sensor_id,
        "gpio_pin": sensor.gpio_pin,
        "event_type": event_type,
        "event_time": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": "RASPBERRY_PI",
    }


class TransitionProcessor:
    """Emits once per edge. Count sensors emit only CLEAR -> ACTIVE."""

    def __init__(self, line_id: str, emit: Callable[[dict], None]):
        self.line_id = line_id
        self.emit = emit
        self._states: dict[str, bool] = {}

    def initialize(self, sensor_id: str, active: bool) -> None:
        self._states[sensor_id] = active

    def update(self, sensor_id: str, active: bool) -> dict | None:
        sensor = SENSORS[sensor_id]
        previous = self._states.get(sensor_id)
        self._states[sensor_id] = active
        if previous is None or previous == active:
            return None
        if sensor.kind == "count" and not active:
            return None
        event_type = sensor.active_event if active else "SENSOR_CLEAR"
        event = create_event(sensor, event_type, self.line_id)
        self.emit(event)
        return event
