"""JSON-RPC 2.0 envelope models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR = -32000


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: str | int | None = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: Any | None = None


def success(request_id: str | int | None, result: Any) -> dict[str, Any]:
    """Build a success envelope. The `error` member is omitted entirely."""
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def failure(
    request_id: str | int | None,
    code: int,
    message: str,
    data: Any | None = None,
) -> dict[str, Any]:
    """Build an error envelope. The `result` member is omitted entirely."""
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}
