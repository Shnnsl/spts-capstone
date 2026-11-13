"""SPTS Raspberry Pi PLC edge client entry point."""
from __future__ import annotations

import logging
import signal
import threading
import time

from api_client import APIError, SPTSClient
from config import load_settings
from event_logic import TransitionProcessor
from event_logic import SENSORS, validate_sensor_mapping
from event_queue import EventQueue
from logging_config import configure_logging
from sensors import GPIOSensors, MockSensors
from runtime_status import RuntimeStatus
from terminal_status import TerminalStatusDisplay

LOG = logging.getLogger(__name__)


def run() -> int:
    settings = load_settings()
    configure_logging(settings.log_level, settings.log_path)
    validate_sensor_mapping()
    LOG.info("Starting SPTS PLC Client v%s", settings.client_version)
    LOG.info("Configuration: api_url=%s line=%s gpio_mode=%s queue_path=%s debounce=%ss", settings.api_base_url, settings.line_id, settings.gpio_mode, settings.queue_path, settings.debounce_seconds)
    event_queue = EventQueue(settings.queue_path)
    status = RuntimeStatus()
    status.update(queue_depth=len(event_queue), dead_letter_count=event_queue.dead_letter_count())
    client = SPTSClient(settings.api_base_url, settings.username, settings.password, settings.http_timeout, settings.http_retries, status=status)
    client.health_check()
    stop = threading.Event()

    def enqueue(event: dict) -> None:
        if event_queue.put(event):
            depth = len(event_queue)
            status.update(queue_depth=depth, last_event_type=event["event_type"], last_event_id=event["event_id"], last_sensor_id=event["sensor_id"], last_station=event["station"])
            LOG.info("Event queued: id=%s sensor=%s station=%s type=%s queue_depth=%d", event["event_id"], event["sensor_id"], event["station"], event["event_type"], depth)

    processor = TransitionProcessor(settings.line_id, enqueue)

    def on_change(sensor_id: str, active: bool, initialize: bool = False) -> None:
        status.sensor_changed(sensor_id, active)
        LOG.info("Sensor state %s: sensor=%s station=%s state=%s", "initialized" if initialize else "changed", sensor_id, SENSORS[sensor_id].station, "ACTIVE" if active else "CLEAR")
        if initialize:
            processor.initialize(sensor_id, active)
        else:
            processor.update(sensor_id, active)

    backend = MockSensors(on_change, settings.debounce_seconds) if settings.gpio_mode == "mock" else GPIOSensors(on_change, settings.debounce_seconds)
    if settings.gpio_mode == "mock":
        for sensor_id in backend.states:
            processor.initialize(sensor_id, backend.states[sensor_id])
            status.sensor_changed(sensor_id, backend.states[sensor_id])

    def deliver() -> None:
        connection_lost = False
        while not stop.is_set():
            event = event_queue.peek()
            if not event:
                stop.wait(0.5)
                continue
            try:
                result = client.send_event(event)
                event_queue.remove(event["event_id"])
                depth = len(event_queue)
                status.event_delivered(event, depth)
                LOG.info("Event delivered: id=%s sensor=%s station=%s type=%s accepted=%s duplicate=%s queue_depth=%d", event["event_id"], event["sensor_id"], event["station"], event["event_type"], str(bool(result.get("accepted"))).lower(), str(bool(result.get("duplicate"))).lower(), depth)
                connection_lost = False
            except APIError as exc:
                if not exc.retryable:
                    event_queue.dead_letter(event, str(exc), exc.status_code)
                    status.update(queue_depth=len(event_queue), dead_letter_count=event_queue.dead_letter_count())
                    LOG.error("Event dead-lettered: id=%s sensor=%s station=%s type=%s reason=%s http_status=%s", event["event_id"], event["sensor_id"], event["station"], event["event_type"], str(exc), exc.status_code)
                    continue
                status.update(api_reachable=False)
                if not connection_lost:
                    LOG.warning("Connection lost; events remain queued")
                    connection_lost = True
                stop.wait(5)

    worker = threading.Thread(target=deliver, name="event-delivery", daemon=True)
    worker.start()
    display = TerminalStatusDisplay(status, settings.line_id, settings.terminal_status_interval_seconds, settings.terminal_status_enabled, settings.terminal_status_force, version=settings.client_version)
    display.start(stop)

    def heartbeat() -> None:
        while not stop.wait(settings.heartbeat_interval_seconds):
            LOG.info("Local heartbeat: api_reachable=%s authenticated=%s queue_depth=%d (no compatible SPTS heartbeat endpoint)", status.snapshot()["api_reachable"], status.snapshot()["authenticated"], status.snapshot()["queue_depth"])

    heartbeat_worker = None
    if settings.heartbeat_enabled:
        LOG.warning("Heartbeat is local-only; SPTS has no compatible device heartbeat endpoint")
        heartbeat_worker = threading.Thread(target=heartbeat, name="local-heartbeat", daemon=True)
        heartbeat_worker.start()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
    try:
        backend.run(stop)
    finally:
        stop.set()
        backend.close()
        worker.join(timeout=settings.http_timeout + 1)
        if heartbeat_worker:
            heartbeat_worker.join(timeout=1)
        display.stop()
        LOG.info("SPTS PLC client shutdown; %d event(s) queued", len(event_queue))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
