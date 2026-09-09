"""Application service that drives the graph."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from dispatch_agent.graph.builder import build_graph

logger = logging.getLogger(__name__)

# Idempotency ledger: ticket_id -> (payload fingerprint, previously returned result).
_RESULTS: dict[str, tuple[str, dict[str, Any]]] = {}

_IDEMPOTENCY_FIELDS = (
    "asset_id",
    "site_code",
    "issue_code",
    "reported_hours_ago",
    "estimated_minutes",
    "contract_tier",
)


def _fingerprint(payload: dict[str, Any]) -> str:
    """Hash the business content of a ticket so replays can be told from id reuse."""
    material = {field: payload.get(field) for field in _IDEMPOTENCY_FIELDS}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


async def triage_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one work order through the graph and return the dispatch decision."""
    ticket_id = payload.get("ticket_id", "")
    fingerprint = _fingerprint(payload)

    cached = _RESULTS.get(ticket_id)
    if cached is not None:
        cached_fingerprint, cached_result = cached
        if cached_fingerprint == fingerprint:
            return cached_result
        logger.warning("ticket_id=%s reused with a different payload; re-running", ticket_id)

    compiled = build_graph().compile()

    initial_state: dict[str, Any] = {
        "ticket_id": ticket_id,
        "asset_id": payload.get("asset_id", ""),
        "site_code": payload.get("site_code", ""),
        "issue_code": payload.get("issue_code", ""),
        "reported_hours_ago": payload.get("reported_hours_ago", 0),
        "estimated_minutes": payload.get("estimated_minutes", 0),
        "contract_tier": payload.get("contract_tier", "standard"),
        "technician_id": "",
        "free_minutes": 0,
        "sla_minutes": 0,
        "decision": "pending",
        "audit": [],
        "errors": [],
    }

    final_state = await compiled.ainvoke(initial_state)

    result = {
        "ticket_id": ticket_id,
        "asset_id": final_state.get("asset_id"),
        "site_code": final_state.get("site_code"),
        "severity": final_state.get("severity"),
        "serviceable": final_state.get("serviceable"),
        "decision": final_state.get("decision"),
        "rejection_reason": final_state.get("rejection_reason", ""),
        "technician_id": final_state.get("technician_id", ""),
        "sla_minutes": final_state.get("sla_minutes", 0),
        "free_minutes": final_state.get("free_minutes", 0),
        "audit": final_state.get("audit", []),
    }

    _RESULTS[ticket_id] = (fingerprint, result)
    return result


async def get_policy() -> dict[str, Any]:
    """Expose the effective dispatch policy configuration."""
    from dispatch_agent.config import settings
    from dispatch_agent.graph.nodes import SLA_MINUTES

    return {
        "intake_window_hours": settings.intake_window_hours,
        "capacity_buffer_minutes": settings.capacity_buffer_minutes,
        "max_auto_dispatch_minutes": settings.max_auto_dispatch_minutes,
        "sla_minutes": dict(SLA_MINUTES),
    }
