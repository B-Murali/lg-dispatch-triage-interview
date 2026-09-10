"""FastAPI application exposing the agent over JSON-RPC."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, Response

from dispatch_agent.config import settings
from dispatch_agent.rpc import methods  # noqa: F401  (registers RPC methods)
from dispatch_agent.rpc.dispatcher import (
    dispatch,
    dispatch_batch,
    registered_methods,
)
from dispatch_agent.rpc.models import INVALID_REQUEST, failure

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Dispatch Triage Agent", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "app": settings.app_name, "methods": registered_methods()}


@app.post("/rpc")
async def rpc(request: Request) -> Any:
    """Single JSON-RPC endpoint: one call, or a batch of them."""
    body = await request.json()

    if isinstance(body, list):
        logger.info("rpc batch size=%d", len(body))
        if not body:
            return failure(None, INVALID_REQUEST, "Invalid Request", "batch must not be empty")
        responses = await dispatch_batch(body)
        if not responses:
            return Response(status_code=204)
        return responses

    logger.info("rpc request method=%s", body.get("method") if isinstance(body, dict) else None)
    response = await dispatch(body)
    if response is None:
        return Response(status_code=204)
    return response
