"""JSON-RPC method surface."""

from __future__ import annotations

from typing import Any

from dispatch_agent.rpc.dispatcher import method, registered_methods
from dispatch_agent.services import dispatch_service


@method("dispatch.triage")
async def dispatch_triage(params: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a work order and return the dispatch decision."""
    return await dispatch_service.triage_ticket(params)


@method("dispatch.policy")
async def dispatch_policy(params: dict[str, Any]) -> dict[str, Any]:
    """Return the effective dispatch policy configuration."""
    return await dispatch_service.get_policy()


@method("agent.describe")
async def agent_describe(params: dict[str, Any]) -> dict[str, Any]:
    """Lightweight capability descriptor for an orchestrating parent agent."""
    return {
        "name": "dispatch-triage-agent",
        "protocol": "json-rpc-2.0",
        "transport": "http",
        "methods": registered_methods(),
    }
