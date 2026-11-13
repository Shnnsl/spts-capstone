import requests
import pytest

from api_client import APIError, SPTSClient


class Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
    def json(self): return self._body
    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception): raise result
        return result
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        result = next(self.responses)
        if isinstance(result, Exception): raise result
        return result


def test_authentication_and_delivery():
    session = Session([Response(body={"access_token": "secret-token"}), Response(body={"accepted": True, "duplicate": False})])
    client = SPTSClient("http://test", "user", "pass", session=session)
    assert client.send_event({"event_id": "e1"})["accepted"]
    assert session.calls[0][1]["json"] == {"username": "user", "password": "pass"}
    assert session.calls[1][1]["headers"]["Authorization"] == "Bearer secret-token"


def test_reauthenticates_after_401():
    session = Session([Response(body={"access_token": "old"}), Response(401), Response(body={"access_token": "new"}), Response(body={"accepted": True})])
    client = SPTSClient("http://test", "user", "pass", retries=2, session=session, sleeper=lambda _: None)
    assert client.send_event({"event_id": "e1"})["accepted"]
    assert len(session.calls) == 4


def test_retry_then_success():
    session = Session([Response(body={"access_token": "token"}), requests.ConnectionError(), Response(body={"accepted": True})])
    client = SPTSClient("http://test", "user", "pass", retries=1, session=session, sleeper=lambda _: None)
    assert client.send_event({"event_id": "e1"})["accepted"]


def test_retry_exhaustion():
    session = Session([requests.ConnectionError(), requests.ConnectionError()])
    client = SPTSClient("http://test", "user", "pass", retries=1, session=session, sleeper=lambda _: None)
    with pytest.raises(APIError):
        client.send_event({"event_id": "e1"})


def test_health_check_records_version():
    from runtime_status import RuntimeStatus
    status = RuntimeStatus()
    client = SPTSClient("http://test", "user", "pass", session=Session([Response(body={"api_version": "2.4.0"})]), status=status)
    assert client.health_check() == "2.4.0"
    assert status.snapshot()["api_version"] == "2.4.0"


def test_failed_health_check_is_nonfatal():
    client = SPTSClient("http://test", "user", "pass", session=Session([requests.ConnectionError()]))
    assert client.health_check() is None
