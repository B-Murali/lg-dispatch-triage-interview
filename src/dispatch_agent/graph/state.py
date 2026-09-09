"""Graph state definition."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

Severity = Literal["safety", "urgent", "routine", "non_technical", "unknown"]
Decision = Literal["pending", "auto_dispatch", "needs_scheduling", "rejected"]


class DispatchState(TypedDict, total=False):
    """State threaded through the dispatch triage graph."""

    # --- inputs -------------------------------------------------------
    ticket_id: str
    asset_id: str
    site_code: str
    issue_code: str
    reported_hours_ago: int
    estimated_minutes: int
    contract_tier: str

    # --- derived ------------------------------------------------------
    severity: Severity
    serviceable: bool
    skill: str
    free_minutes: int
    has_capacity: bool
    technician_id: str
    sla_minutes: int
    decision: Decision
    rejection_reason: str

    # --- observability ------------------------------------------------
    audit: list[str]
    errors: list[str]
    metadata: dict[str, Any]
