"""Graph nodes for the dispatch triage flow.

Flow (as designed):

    START -> validate -> triage -> (route_after_triage)
                                    |-- "assess" -> capacity_check
                                    |-- "reject" -> finalize
    capacity_check -> (route_after_capacity)
                                    |-- "assign" -> assign_technician    -> finalize
                                    |-- "queue"  -> queue_for_scheduling -> finalize
    finalize -> END
"""

from __future__ import annotations

import asyncio
import logging

from dispatch_agent.config import settings
from dispatch_agent.graph.state import Decision, DispatchState, Severity
from dispatch_agent.services.availability_client import AvailabilityClient

logger = logging.getLogger(__name__)

ISSUE_TO_SEVERITY: dict[str, Severity] = {
    "NO_POWER": "safety",
    "SMOKE_DETECTED": "safety",
    "WATER_LEAK": "urgent",
    "OVERHEATING": "urgent",
    "NOISE_COMPLAINT": "routine",
    "COSMETIC_DAMAGE": "routine",
    "WARRANTY_QUESTION": "non_technical",
}

SERVICEABLE_SEVERITIES = {"safety", "urgent", "routine"}

# Response target, in minutes, per severity.
SLA_MINUTES = {
    "safety": 60,
    "urgent": 240,
    "routine": 1440,
}

# Which technician pool a severity draws from.
SKILL_FOR_SEVERITY = {
    "safety": "certified",
    "urgent": "certified",
    "routine": "general",
}

_availability_client = AvailabilityClient()


async def validate(state: DispatchState) -> DispatchState:
    """Reject structurally invalid tickets before any policy work happens."""
    errors: list[str] = []

    if not state.get("asset_id"):
        errors.append("asset_id is required")
    if not state.get("site_code"):
        errors.append("site_code is required")
    if state.get("estimated_minutes", 0) <= 0:
        errors.append("estimated_minutes must be positive")
    if state.get("reported_hours_ago", -1) < 0:
        errors.append("reported_hours_ago must be >= 0")

    state["audit"].append("validate")

    logger.info("validated ticket asset=%s errors=%d", state.get("asset_id"), len(errors))

    return {"audit": state["audit"]}


async def triage(state: DispatchState) -> DispatchState:
    """Map the raw issue code onto a severity band."""
    issue = state.get("issue_code", "")
    severity = ISSUE_TO_SEVERITY.get(issue, "unknown")

    # Severity lookup is backed by a slow legacy fault-taxonomy service.
    await asyncio.sleep(0.05)

    serviceable = severity in SERVICEABLE_SEVERITIES and (
        state.get("reported_hours_ago", 9999) <= settings.intake_window_hours
    )

    state["audit"].append("triage")
    return {
        "severity": severity,
        "serviceable": serviceable,
        "skill": SKILL_FOR_SEVERITY.get(severity, "general"),
        "audit": state["audit"],
    }


async def capacity_check(state: DispatchState) -> DispatchState:
    """Ask the depot how much technician time is free, and apply the job-size rule."""
    free = await _availability_client.free_minutes(
        state.get("site_code", ""), state.get("skill", "general")
    )

    estimated = state.get("estimated_minutes", 0)
    fits_in_the_day = free >= estimated + settings.capacity_buffer_minutes
    small_enough = estimated <= settings.max_auto_dispatch_minutes

    state["audit"].append("capacity_check")
    return {
        "free_minutes": free,
        "has_capacity": fits_in_the_day and small_enough,
        "audit": state["audit"],
    }


async def assign_technician(state: DispatchState) -> DispatchState:
    """Reserve a technician from the site's pool."""
    site = state.get("site_code", "")
    skill = state.get("skill", "general")
    severity = state.get("severity", "routine")

    state["audit"].append("assign_technician")
    return {
        "technician_id": f"{site}-{skill.upper()}-01",
        "sla_minutes": SLA_MINUTES.get(severity, 1440),
        "audit": state["audit"],
    }


async def queue_for_scheduling(state: DispatchState) -> DispatchState:
    """Park the ticket for a human coordinator; no technician is reserved."""
    severity = state.get("severity", "routine")

    state["audit"].append("queue_for_scheduling")
    return {
        "technician_id": "",
        "sla_minutes": SLA_MINUTES.get(severity, 1440),
        "audit": state["audit"],
    }


async def finalize(state: DispatchState) -> DispatchState:
    """Collapse the run into a terminal decision."""
    decision: Decision
    if state.get("errors"):
        decision = "rejected"
        rejection_reason = "; ".join(state["errors"])
    elif not state.get("serviceable", False):
        decision = "rejected"
        severity = state.get("severity", "unknown")
        if severity not in SERVICEABLE_SEVERITIES:
            rejection_reason = f"severity '{severity}' is not a serviceable fault"
        else:
            rejection_reason = (
                f"reported {state.get('reported_hours_ago')}h ago, outside the "
                f"{settings.intake_window_hours}h intake window"
            )
    elif state.get("technician_id"):
        decision = "auto_dispatch"
        rejection_reason = ""
    else:
        decision = "needs_scheduling"
        rejection_reason = ""

    state["audit"].append("finalize")
    return {
        "decision": decision,
        "rejection_reason": rejection_reason,
        "audit": state["audit"],
        "metadata": {
            "intake_window_hours": settings.intake_window_hours,
            "capacity_buffer_minutes": settings.capacity_buffer_minutes,
            "max_auto_dispatch_minutes": settings.max_auto_dispatch_minutes,
        },
    }


# --------------------------------------------------------------------------
# routers
# --------------------------------------------------------------------------


def route_after_triage(state: DispatchState) -> str:
    """Short-circuit rule: anything already known to be undispatchable skips the depot."""
    if state.get("errors"):
        return "reject"
    if not state.get("serviceable", False):
        return "reject"
    return "assess"


def route_after_capacity(state: DispatchState) -> str:
    if state.get("free_minutes", 0) >= state.get("estimated_minutes", 0):
        return "assign"
    return "queue"
