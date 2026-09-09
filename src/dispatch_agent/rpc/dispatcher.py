"""Minimal JSON-RPC 2.0 dispatcher."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from dispatch_agent.rpc.models import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    SERVER_ERROR,
    JsonRpcRequest,
    failure,
    success,
)

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[Any]]

_REGISTRY: dict[str, Handler] = {}


def method(name: str) -> Callable[[Handler], Handler]:
    """Register a coroutine as a JSON-RPC method."""

    def decorator(func: Handler) -> Handler:
        _REGISTRY[name] = func
        return func

    return decorator


def registered_methods() -> list[str]:
    return sorted(_REGISTRY)


def _read_id(raw: Any) -> str | int | None:
    """Best-effort read of the request id, for error envelopes."""
    if isinstance(raw, dict):
        candidate = raw.get("id")
        if isinstance(candidate, (str, int)):
            return candidate
    return None


def _invalid_request_reason(raw: Any) -> str | None:
    """Return why `raw` is not a valid JSON-RPC request object, or None if it is."""
    if not isinstance(raw, dict):
        return "request must be a JSON object"
    if raw.get("jsonrpc") != "2.0":
        return "jsonrpc must be exactly '2.0'"
    if not isinstance(raw.get("method"), str) or not raw.get("method"):
        return "method must be a non-empty string"
    if "params" in raw and not isinstance(raw["params"], dict):
        return "params must be an object"
    return None


async def dispatch(raw: Any) -> dict[str, Any]:
    """Execute a single JSON-RPC call and return the response envelope."""
    reason = _invalid_request_reason(raw)
    if reason is not None:
        return failure(_read_id(raw), INVALID_REQUEST, "Invalid Request", reason)

    request = JsonRpcRequest(**raw)

    handler = _REGISTRY.get(request.method)
    if handler is None:
        return failure(request.id, METHOD_NOT_FOUND, f"Unknown method: {request.method}")

    try:
        result = await handler(request.params)
    except (KeyError, TypeError) as exc:
        return failure(request.id, INVALID_PARAMS, "Invalid params", str(exc))
    except Exception as exc:
        logger.exception("rpc handler failed method=%s", request.method)
        return failure(request.id, SERVER_ERROR, str(exc), repr(exc))

    return success(request.id, result)
