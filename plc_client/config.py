"""Environment-based configuration for the SPTS PLC edge client."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from version import SPTS_PLC_CLIENT_VERSION


def _int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    api_base_url: str
    username: str
    password: str
    line_id: str
    gpio_mode: str
    log_level: str
    http_timeout: float
    http_retries: int
    queue_path: Path
    debounce_seconds: float
    terminal_status_enabled: bool
    terminal_status_force: bool
    terminal_status_interval_seconds: float
    heartbeat_enabled: bool
    heartbeat_interval_seconds: float
    client_version: str
    log_path: Path
    test_mode: bool

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("GPIO_MODE", "mock").strip().lower()
        if mode == "gpio":  # Backward-compatible alias.
            mode = "gpiozero"
        if mode not in {"mock", "gpiozero"}:
            raise ValueError("GPIO_MODE must be 'mock' or 'gpiozero'")
        base_url = os.getenv("SPTS_API_BASE_URL", "http://192.168.1.22:8000").strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("SPTS_API_BASE_URL must start with http:// or https://")
        line_id = os.getenv("SPTS_LINE_ID", "LINE-01").strip()
        if not line_id:
            raise ValueError("SPTS_LINE_ID cannot be empty")
        settings = cls(
            api_base_url=base_url,
            username=os.getenv("SPTS_USERNAME", "").strip(),
            password=os.getenv("SPTS_PASSWORD", ""),
            line_id=line_id,
            gpio_mode=mode,
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            http_timeout=_float("HTTP_TIMEOUT", 10.0, 0.1),
            http_retries=_int("HTTP_RETRIES", 3, 0),
            queue_path=Path(os.getenv("QUEUE_PATH", "data/event_queue.sqlite3")).expanduser(),
            debounce_seconds=_float("DEBOUNCE", 0.08, 0),
            terminal_status_enabled=_bool("SPTS_TERMINAL_STATUS_ENABLED", True),
            terminal_status_force=_bool("SPTS_TERMINAL_STATUS_FORCE", False),
            terminal_status_interval_seconds=_float("SPTS_TERMINAL_STATUS_INTERVAL_SECONDS", 2.0, 0.01),
            heartbeat_enabled=_bool("SPTS_HEARTBEAT_ENABLED", False),
            heartbeat_interval_seconds=_float("SPTS_HEARTBEAT_INTERVAL_SECONDS", 30.0, 5.0),
            client_version=os.getenv("SPTS_CLIENT_VERSION", SPTS_PLC_CLIENT_VERSION).strip(),
            log_path=Path(os.getenv("LOG_PATH", "logs/spts-plc-client.log")).expanduser(),
            test_mode=_bool("SPTS_TEST_MODE", False),
        )
        settings.validate_startup()
        return settings

    def validate_startup(self) -> None:
        if not self.client_version:
            raise ValueError("SPTS_CLIENT_VERSION cannot be empty")
        if not self.test_mode and (not self.username or not self.password):
            raise ValueError("SPTS_USERNAME and SPTS_PASSWORD are required")
        for name, path in (("QUEUE_PATH", self.queue_path), ("LOG_PATH", self.log_path)):
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                probe = path.parent / ".spts-write-test"
                probe.touch(exist_ok=True)
                probe.unlink()
            except OSError as exc:
                raise ValueError(f"{name} parent is not writable: {path.parent}") from exc


def load_settings(env_file: str | Path = ".env") -> Settings:
    from dotenv import load_dotenv

    load_dotenv(env_file, override=False)
    return Settings.from_env()
