import pytest
from pathlib import Path
from uuid import uuid4

from config import Settings


def test_defaults(monkeypatch):
    for key in ("SPTS_API_BASE_URL", "SPTS_USERNAME", "SPTS_PASSWORD", "SPTS_LINE_ID", "GPIO_MODE", "HTTP_TIMEOUT", "HTTP_RETRIES", "QUEUE_PATH", "DEBOUNCE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SPTS_TEST_MODE", "true")
    settings = Settings.from_env()
    assert settings.gpio_mode == "mock"
    assert settings.line_id == "LINE-01"
    assert settings.http_retries == 3
    assert settings.client_version == "1.0.0"
    assert settings.heartbeat_enabled is False


def test_version_override(monkeypatch):
    test_dir = Path(__file__).parent
    queue_path = test_dir / f"config-{uuid4()}.db"
    log_path = test_dir / f"config-{uuid4()}.log"
    monkeypatch.setenv("SPTS_TEST_MODE", "true")
    monkeypatch.setenv("SPTS_CLIENT_VERSION", "1.2.3-test")
    monkeypatch.setenv("QUEUE_PATH", str(queue_path))
    monkeypatch.setenv("LOG_PATH", str(log_path))
    assert Settings.from_env().client_version == "1.2.3-test"


def test_invalid_mode(monkeypatch):
    monkeypatch.setenv("SPTS_TEST_MODE", "true")
    monkeypatch.setenv("GPIO_MODE", "wrong")
    with pytest.raises(ValueError):
        Settings.from_env()
