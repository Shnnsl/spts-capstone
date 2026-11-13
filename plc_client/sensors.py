"""GPIO and interactive Windows-safe mock sensor backends."""
from __future__ import annotations

import logging
import queue

from event_logic import SENSORS

LOG = logging.getLogger(__name__)


class MockSensors:
    def __init__(self, callback, debounce_seconds: float = 0.08):
        self.callback = callback
        self.states = {sensor_id: False for sensor_id in SENSORS}
        self._commands: queue.Queue[str] = queue.Queue()

    def run(self, stop_event) -> None:
        LOG.info("Mock sensors initialized; commands: S1..S5, status, quit")
        while not stop_event.is_set():
            try:
                command = input("sensor> ").strip().upper()
            except (EOFError, KeyboardInterrupt):
                stop_event.set()
                break
            if command in {"QUIT", "EXIT", "Q"}:
                stop_event.set()
            elif command == "STATUS":
                LOG.info("Mock states: %s", self.states)
            elif command in self.states:
                self.states[command] = not self.states[command]
                self.callback(command, self.states[command])
            elif command:
                LOG.warning("Unknown mock command: %s", command)

    def close(self) -> None:
        pass


class GPIOSensors:
    def __init__(self, callback, debounce_seconds: float = 0.08):
        try:
            from gpiozero import DigitalInputDevice
        except ImportError as exc:
            raise RuntimeError("gpiozero is required for GPIO_MODE=gpio") from exc
        self.devices = {}
        for sensor_id, definition in SENSORS.items():
            device = DigitalInputDevice(definition.gpio_pin, pull_up=None, active_state=False, bounce_time=debounce_seconds)
            self.devices[sensor_id] = device
            callback(sensor_id, bool(device.is_active), initialize=True)
            device.when_activated = lambda sid=sensor_id: callback(sid, True)
            device.when_deactivated = lambda sid=sensor_id: callback(sid, False)
            LOG.info("Initialized %s on GPIO%d", sensor_id, definition.gpio_pin)

    def run(self, stop_event) -> None:
        stop_event.wait()

    def close(self) -> None:
        for device in self.devices.values():
            device.close()
