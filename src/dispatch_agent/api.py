"""FastAPI application exposing the agent over JSON-RPC."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request

from dispatch_agent.config import settings
from dispatch_agent.rpc import methods  # noqa: F401  (registers RPC methods)
from dispatch_agent.rpc.dispatcher import dispatch, registered_methods

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dispatch Triage Agent", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "app": settings.app_name, "methods": registered_methods()}


@app.post("/rpc")
async def rpc(request: Request) -> Any:
    """Single JSON-RPC endpoint."""
    body = await request.json()
    logger.info("rpc request method=%s", body.get("method"))
    return await dispatch(body)
