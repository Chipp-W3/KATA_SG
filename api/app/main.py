"""KATA_SG API: probes, pod identity, CPU-bound work, admin stats, metrics."""

import hashlib
import hmac
import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Histogram, generate_latest


class JsonFormatter(logging.Formatter):
    """One JSON object per line on stdout. Cloud Logging parses it: `severity`
    sets the log level, the other keys become searchable fields."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        entry.update(getattr(record, "fields", {}))  # structured fields passed with extra={"fields": ...}
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
log = logging.getLogger("api")

POD_NAME = os.getenv("POD_NAME", socket.gethostname())
APP_VERSION = os.getenv("APP_VERSION", "dev")  # baked into the image at build time
STARTED_AT = time.time()

# SLI metric: traffic, errors AND latency in one histogram.
#   p95 latency : histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))
#   error rate  : sum(rate(..._count{status=~"5.."}[5m])) / sum(rate(..._count[5m]))
# Labels use the route TEMPLATE (/api/work), never the raw URL: bounded cardinality.
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency by route and status",
    ["method", "route", "status"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),  # dense around the 500 ms SLO
)

# Probes and scrapes every few seconds would drown the useful access logs.
QUIET_ROUTES = {"/health", "/ready", "/metrics"}

state: dict[str, str | None] = {"admin_token": None}
served = {"requests": 0}  # requests handled by THIS pod since it started


def load_admin_token() -> str | None:
    """Local run: ADMIN_TOKEN env var. On GKE: Secret Manager, with the pod identity."""
    if token := os.getenv("ADMIN_TOKEN"):
        return token
    project = os.getenv("GCP_PROJECT")
    if not project:
        log.warning("no ADMIN_TOKEN and no GCP_PROJECT: admin endpoint disabled")
        return None
    from google.cloud import secretmanager  # imported lazily: not needed locally

    name = f"projects/{project}/secrets/admin-token/versions/latest"
    client = secretmanager.SecretManagerServiceClient()
    return client.access_secret_version(name=name).payload.data.decode()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        state["admin_token"] = load_admin_token()
        log.info("admin token loaded: %s", state["admin_token"] is not None)
    except Exception:  # non-critical feature: keep serving, admin endpoint returns 503
        log.exception("cannot load admin token")
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def observe(request: Request, call_next):
    """Time every request and record it with its route template and status code."""
    start = time.perf_counter()
    status = 500  # if the handler raises, the request is counted as a server error
    try:
        response = await call_next(request)
        status = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        template = route.path if route else "unmatched"  # e.g. 404s on random URLs
        duration = time.perf_counter() - start
        REQUEST_LATENCY.labels(request.method, template, str(status)).observe(duration)
        served["requests"] += 1
        if template not in QUIET_ROUTES:
            log.info(
                "request",
                extra={
                    "fields": {
                        "method": request.method,
                        "route": template,
                        "status": status,
                        "duration_ms": round(duration * 1000, 1),
                        "pod": POD_NAME,
                    }
                },
            )


@app.get("/health")
def health() -> dict:
    """Liveness: the process answers. No dependency check, or a dependency
    outage would make Kubernetes restart every pod."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    """Readiness: the pod can receive traffic."""
    return {"status": "ready"}


@app.get("/api/whoami")
def whoami() -> dict:
    return {"pod": POD_NAME, "version": APP_VERSION}


@app.get("/api/work")
def work(iterations: int = Query(20_000, ge=1, le=200_000)) -> dict:
    """CPU-bound work to drive the HPA. Sync `def`: runs in the threadpool, so it
    never blocks the event loop serving the probes. Bounded to limit abuse."""
    digest = b"kata"
    for _ in range(iterations):
        digest = hashlib.sha256(digest).digest()
    return {"pod": POD_NAME, "version": APP_VERSION, "iterations": iterations}


@app.get("/api/admin/stats")
def admin_stats(x_admin_token: str = Header(default="")) -> dict:
    expected = state["admin_token"]
    if expected is None:
        raise HTTPException(503, "admin token unavailable")
    if not hmac.compare_digest(x_admin_token, expected):  # constant time: no timing attack
        raise HTTPException(401, "invalid token")
    return {
        "pod": POD_NAME,
        "version": APP_VERSION,
        "uptime_seconds": round(time.time() - STARTED_AT),
        "requests_served": served["requests"],
        "secret_source": "env" if os.getenv("ADMIN_TOKEN") else "secret-manager",
    }


@app.get("/metrics")
def metrics() -> PlainTextResponse:
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
