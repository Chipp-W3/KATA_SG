import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    with TestClient(app) as c:  # context manager runs the lifespan (token loading)
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


def test_admin_rejects_missing_token(client):
    assert client.get("/api/admin/stats").status_code == 401


def test_admin_rejects_wrong_token(client):
    assert client.get("/api/admin/stats", headers={"X-Admin-Token": "nope"}).status_code == 401


def test_admin_stats_reports_real_figures(client):
    client.get("/api/whoami")
    resp = client.get("/api/admin/stats", headers={"X-Admin-Token": "test-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["requests_served"] >= 1
    assert body["secret_source"] == "env"


def test_admin_unavailable_without_secret(monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    with TestClient(app) as c:
        assert c.get("/api/admin/stats").status_code == 503


def test_latency_histogram_uses_route_template_and_status(client):
    client.get("/api/work", params={"iterations": 5})
    client.get("/does-not-exist")
    text = client.get("/metrics").text
    bucket = 'http_request_duration_seconds_bucket{le="0.5",method="GET",route="/api/work",status="200"}'
    assert bucket in text
    assert 'route="unmatched",status="404"' in text  # raw URLs never become labels
