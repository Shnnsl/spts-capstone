"""Optional lightweight interactive terminal status display."""
from __future__ import annotations

import sys
import threading

from version import SPTS_PLC_CLIENT_VERSION

SENSOR_LABELS = {
    "S1": "Input",
    "S2": "Filler",
    "S3": "Cartoner",
    "S4": "Case Packer",
    "S5": "Finished Case",
}


def format_status(snapshot: dict, line_id: str, version: str = SPTS_PLC_CLIENT_VERSION) -> str:
    communication = snapshot["last_successful_communication"]
    last_communication = communication.astimezone().strftime("%Y-%m-%d %H:%M:%S") if communication else "NEVER"
    last_event = "NONE"
    if snapshot["last_event_type"]:
        last_event = f'{snapshot["last_station"]} / {snapshot["last_event_type"]}'
    lines = [
        f"SPTS PLC CLIENT v{version}",
        f'API: {"CONNECTED" if snapshot["api_reachable"] else "DISCONNECTED"}',
        f'API version: {snapshot["api_version"] or "UNKNOWN"}',
        f'Authenticated: {"YES" if snapshot["authenticated"] else "NO"}',
        f"Line: {line_id}",
        f'Queue: {snapshot["queue_depth"]}',
        f'Dead letters: {snapshot["dead_letter_count"]}',
        f'Delivered: {snapshot["delivered_count"]}',
        f'Retries: {snapshot["retry_count"]}',
        f"Last event: {last_event}",
        f"Last communication: {last_communication}",
        "",
    ]
    lines.extend(f'{sensor_id} {SENSOR_LABELS[sensor_id]}: {snapshot["sensor_states"][sensor_id]}' for sensor_id in SENSOR_LABELS)
    return "\n".join(lines)


class TerminalStatusDisplay:
    def __init__(self, status, line_id: str, interval: float, enabled: bool, force: bool = False, stream=None, version: str = SPTS_PLC_CLIENT_VERSION):
        self.status = status
        self.line_id = line_id
        self.interval = interval
        self.stream = stream or sys.stdout
        self.enabled = enabled and (force or bool(getattr(self.stream, "isatty", lambda: False)()))
        self.version = version
        self._thread: threading.Thread | None = None

    def start(self, stop_event) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(target=self._run, args=(stop_event,), name="terminal-status", daemon=True)
        self._thread.start()

    def _run(self, stop_event) -> None:
        first = True
        while not stop_event.is_set():
            text = format_status(self.status.snapshot(), self.line_id, self.version)
            prefix = "" if first else f"\x1b[{text.count(chr(10)) + 1}F"
            self.stream.write(prefix + text + "\n")
            self.stream.flush()
            first = False
            stop_event.wait(self.interval)

    def stop(self) -> None:
        if self._thread:
            self._thread.join(timeout=self.interval + 1)
