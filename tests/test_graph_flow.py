"""Behaviour of the dispatch decision graph."""

from __future__ import annotations

import pytest

from dispatch_agent.graph import nodes
from dispatch_agent.services.dispatch_service import triage_ticket

BASE = {
    "ticket_id": "TCK-1",
    "asset_id": "AST-9001",
    "site_code": "SFO-02",
    "issue_code": "NO_POWER",
    "reported_hours_ago": 4,
    "estimated_minutes": 90,
}


def ticket(**overrides):
    return {**BASE, **overrides}


# ---------------------------------------------------------------------------
# triage / severity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("issue_code", "severity"),
    [
        ("NO_POWER", "safety"),
        ("SMOKE_DETECTED", "safety"),
        ("WATER_LEAK", "urgent"),
        ("OVERHEATING", "urgent"),
        ("NOISE_COMPLAINT", "routine"),
        ("COSMETIC_DAMAGE", "routine"),
        ("WARRANTY_QUESTION", "non_technical"),
        ("PILOT_LIGHT_OUT", "unknown"),
    ],
)
async def test_issue_code_severity_mapping(issue_code, severity):
    result = await triage_ticket(ticket(issue_code=issue_code))
    assert result["severity"] == severity


async def test_non_technical_issue_is_rejected():
    result = await triage_ticket(ticket(issue_code="WARRANTY_QUESTION"))

    assert result["decision"] == "rejected"
    assert "not a serviceable fault" in result["rejection_reason"]
    assert result["audit"] == ["validate", "triage", "finalize"]


async def test_stale_ticket_is_rejected():
    result = await triage_ticket(ticket(reported_hours_ago=100))

    assert result["decision"] == "rejected"
    assert "intake window" in result["rejection_reason"]
    assert result["audit"] == ["validate", "triage", "finalize"]


# ---------------------------------------------------------------------------
# capacity
# ---------------------------------------------------------------------------


async def test_thin_capacity_queues_the_ticket(depot_reporting):
    depot_reporting(100)

    result = await triage_ticket(ticket(estimated_minutes=90))

    assert result["decision"] == "needs_scheduling"
    assert result["technician_id"] == ""
    assert result["audit"] == [
        "validate",
        "triage",
        "capacity_check",
        "queue_for_scheduling",
        "finalize",
    ]


async def test_oversized_job_never_auto_dispatches():
    result = await triage_ticket(ticket(estimated_minutes=300))

    assert result["decision"] == "needs_scheduling"


@pytest.mark.parametrize(
    ("issue_code", "sla_minutes"),
    [("NO_POWER", 60), ("WATER_LEAK", 240), ("NOISE_COMPLAINT", 1440)],
)
async def test_sla_follows_severity(depot_reporting, issue_code, sla_minutes):
    depot_reporting(0)

    result = await triage_ticket(ticket(issue_code=issue_code))

    assert result["sla_minutes"] == sla_minutes


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------


async def test_dispatched_ticket_reaches_a_terminal_decision():
    result = await triage_ticket(ticket())

    assert result["decision"] == "auto_dispatch"
    assert result["technician_id"] == "SFO-02-CERTIFIED-01"
    assert result["sla_minutes"] == 60
    assert result["rejection_reason"] == ""


async def test_dispatched_ticket_runs_every_node_in_order():
    result = await triage_ticket(ticket())

    assert result["audit"] == [
        "validate",
        "triage",
        "capacity_check",
        "assign_technician",
        "finalize",
    ]


@pytest.mark.parametrize(
    ("issue_code", "skill"),
    [("NO_POWER", "CERTIFIED"), ("WATER_LEAK", "CERTIFIED"), ("COSMETIC_DAMAGE", "GENERAL")],
)
async def test_technician_comes_from_the_right_pool(issue_code, skill):
    result = await triage_ticket(ticket(issue_code=issue_code))

    assert result["decision"] == "auto_dispatch"
    assert result["technician_id"] == f"SFO-02-{skill}-01"


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


async def test_invalid_ticket_is_rejected_without_calling_the_depot(monkeypatch):
    calls = []

    async def _counting_lookup(*args, **kwargs):
        calls.append(args)
        return 480

    monkeypatch.setattr(nodes._availability_client, "free_minutes", _counting_lookup)

    result = await triage_ticket(ticket(asset_id=""))

    assert result["decision"] == "rejected"
    assert "asset_id is required" in result["rejection_reason"]
    assert result["audit"] == ["validate", "triage", "finalize"]
    assert calls == [], "an invalid ticket must never reach the availability service"


async def test_invalid_duration_is_rejected():
    result = await triage_ticket(ticket(estimated_minutes=0))

    assert result["decision"] == "rejected"
    assert "estimated_minutes must be positive" in result["rejection_reason"]
    assert result["technician_id"] == ""


# ---------------------------------------------------------------------------
# idempotency
# ---------------------------------------------------------------------------


async def test_replaying_a_ticket_id_returns_the_same_result():
    first = await triage_ticket(ticket())
    second = await triage_ticket(ticket())

    assert first == second
