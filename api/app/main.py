"""KATA_SG API: probes, pod identity, CPU-bound work endpoint."""

import hashlib
import os
import socket

from fastapi import FastAPI, Query

POD_NAME = os.getenv("POD_NAME", socket.gethostname())
APP_VERSION = os.getenv("APP_VERSION", "dev")  # baked into the image at build time

app = FastAPI()


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
