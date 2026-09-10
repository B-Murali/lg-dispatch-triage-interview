"""Minimal JSON-RPC 2.0 dispatcher."""

from __future__ import annotations

import asyncio
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


def _is_notification(raw: Any) -> bool:
    """A notification is a request the caller wants no reply to."""
    return isinstance(raw, dict) and raw.get("id") is None


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


async def dispatch(raw: Any) -> dict[str, Any] | None:
    """Execute a single JSON-RPC call.

    Returns the response envelope, or `None` when the call was a notification and
    the caller must receive no reply at all.
    """
    reason = _invalid_request_reason(raw)
    if reason is not None:
        return failure(_read_id(raw), INVALID_REQUEST, "Invalid Request", reason)

    request = JsonRpcRequest(**raw)
    quiet = _is_notification(raw)

    handler = _REGISTRY.get(request.method)
    if handler is None:
        if quiet:
            return None
        return failure(request.id, METHOD_NOT_FOUND, f"Unknown method: {request.method}")

    try:
        result = await handler(request.params)
    except (KeyError, TypeError) as exc:
        if quiet:
            return None
        return failure(request.id, INVALID_PARAMS, "Invalid params", str(exc))
    except Exception as exc:
        logger.exception("rpc handler failed method=%s", request.method)
        if quiet:
            return None
        return failure(request.id, SERVER_ERROR, str(exc), repr(exc))

    if quiet:
        return None
    return success(request.id, result)


async def dispatch_batch(raws: list[Any]) -> list[dict[str, Any]]:
    """Execute a batch of calls, dropping the members that expect no reply."""
    tasks = [asyncio.create_task(dispatch(raw)) for raw in raws]

    responses: list[dict[str, Any]] = []
    for finished in asyncio.as_completed(tasks):
        response = await finished
        if response is not None:
            responses.append(response)

    return responses
