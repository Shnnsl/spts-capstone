from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.dependencies import get_current_user
from app.main import app
from app.main import downtime_events, supervisor_messages


@pytest.fixture(autouse=True)
def clear_in_memory_workflows():
    downtime_events.clear()
    supervisor_messages.clear()
    yield
    downtime_events.clear()
    supervisor_messages.clear()


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        username="trial-tester", role=SimpleNamespace(name="ADMINISTRATOR")
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def event_payload():
    return {
        "event_id": "91c1a144-61c4-4649-a4ae-82cf6b411ad4",
        "line_id": "LINE-01", "station": "INPUT", "sensor_id": "S1", "gpio_pin": 17,
        "event_type": "PRODUCT_DETECTED", "event_time": "2026-08-06T12:00:00Z",
        "source": "DEVELOPMENT_SIMULATOR",
    }
