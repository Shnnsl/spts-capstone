"""Authenticated, retrying SPTS REST client."""
from __future__ import annotations

import logging
import time
from typing import Callable

import requests

LOG = logging.getLogger(__name__)


class APIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class SPTSClient:
    def __init__(self, base_url: str, username: str, password: str, timeout: float = 10, retries: int = 3, session=None, sleeper: Callable[[float], None] = time.sleep, status=None):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self._password = password
        self.timeout = timeout
        self.retries = retries
        self.session = session or requests.Session()
        self._token: str | None = None
        self._sleep = sleeper
        self.status = status

    def health_check(self) -> str | None:
        """Return the backend version when available; failure is non-fatal."""
        try:
            response = self.session.get(f"{self.base_url}/health", timeout=self.timeout)
            response.raise_for_status()
            version = response.json().get("api_version")
            if self.status:
                self.status.communication_succeeded(authenticated=False)
                self.status.update(api_version=version)
            LOG.info("SPTS health check successful: api_version=%s", version or "unknown")
            return version
        except (requests.RequestException, ValueError) as exc:
            if self.status:
                self.status.update(api_reachable=False)
            LOG.warning("SPTS health check failed; client will continue: %s", type(exc).__name__)
            return None

    def login(self) -> None:
        response = self.session.post(f"{self.base_url}/auth/login", json={"username": self.username, "password": self._password}, timeout=self.timeout)
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise APIError("Login response did not contain access_token")
        self._token = token
        if self.status:
            self.status.communication_succeeded(authenticated=True)
        LOG.info("Authentication successful")

    def send_event(self, event: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                if not self._token:
                    self.login()
                response = self.session.post(f"{self.base_url}/plc/production-event", json=event, headers={"Authorization": f"Bearer {self._token}"}, timeout=self.timeout)
                if response.status_code in (401, 403) and attempt < self.retries:
                    self._token = None
                    if self.status:
                        self.status.update(authenticated=False)
                    LOG.warning("Authentication expired; signing in again")
                    continue
                if 400 <= response.status_code < 500:
                    raise APIError("Backend rejected event", status_code=response.status_code, retryable=False)
                response.raise_for_status()
                result = response.json()
                if result.get("duplicate"):
                    LOG.info("Duplicate acknowledgement event_id=%s", event["event_id"])
                return result
            except APIError as exc:
                if not exc.retryable:
                    raise
                last_error = exc
                if attempt < self.retries:
                    if self.status:
                        self.status.increment("retry_count")
                    delay = min(2 ** attempt, 30)
                    LOG.warning("Delivery attempt %d failed; retrying in %ss", attempt + 1, delay)
                    self._sleep(delay)
            except (requests.RequestException, APIError, ValueError) as exc:
                last_error = exc
                if attempt < self.retries:
                    if self.status:
                        self.status.increment("retry_count")
                    delay = min(2 ** attempt, 30)
                    LOG.warning("Delivery attempt %d failed; retrying in %ss", attempt + 1, delay)
                    self._sleep(delay)
        raise APIError("Event delivery failed after retries") from last_error
