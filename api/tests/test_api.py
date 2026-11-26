import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_ready(client):
    assert client.get("/ready").status_code == 200


def test_whoami_exposes_pod_and_version(client):
    body = client.get("/api/whoami").json()
    assert body["pod"]
    assert body["version"]


def test_work_returns_pod_and_iterations(client):
    body = client.get("/api/work", params={"iterations": 10}).json()
    assert body["iterations"] == 10
    assert body["pod"]


def test_work_rejects_abusive_iterations(client):
    assert client.get("/api/work", params={"iterations": 10_000_000}).status_code == 422
