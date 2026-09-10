"""Behaviour of the downstream technician-availability client."""

from __future__ import annotations

import httpx

from dispatch_agent.graph import nodes
from dispatch_agent.services.availability_client import AvailabilityClient
from dispatch_agent.services.dispatch_service import triage_ticket

DEPOT_URL = "http://depot.invalid/availability"


def _answers(monkeypatch, client: AvailabilityClient, minutes: int) -> None:
    """Make every lookup on `client` return `minutes` free minutes."""

    async def _post(*_args, **_kwargs):
        return httpx.Response(
            200,
            json={"free_minutes": minutes},
            request=httpx.Request("POST", DEPOT_URL),
        )

    monkeypatch.setattr(client._client, "post", _post)


def _fails(monkeypatch, client: AvailabilityClient) -> None:
    async def _post(*_args, **_kwargs):
        raise httpx.ConnectError("depot unreachable")

    monkeypatch.setattr(client._client, "post", _post)


async def test_skill_is_part_of_the_cache_key(monkeypatch):
    client = AvailabilityClient(base_url=DEPOT_URL, cache={})

    _answers(monkeypatch, client, 240)
    assert await client.free_minutes("AAA-01", "certified") == 240

    _answers(monkeypatch, client, 30)
    assert await client.free_minutes("AAA-01", "general") == 30


async def test_each_client_keeps_its_own_cache(monkeypatch):
    first = AvailabilityClient(base_url=DEPOT_URL)
    _answers(monkeypatch, first, 240)
    assert await first.free_minutes("BBB-01", "certified") == 240

    second = AvailabilityClient(base_url=DEPOT_URL)
    _answers(monkeypatch, second, 15)
    assert await second.free_minutes("BBB-01", "certified") == 15


async def test_repeated_lookup_is_served_from_cache(monkeypatch):
    client = AvailabilityClient(base_url=DEPOT_URL, cache={})
    _answers(monkeypatch, client, 240)
    assert await client.free_minutes("CCC-01", "certified") == 240

    async def _boom(*_args, **_kwargs):
        raise AssertionError("a cached lookup must not hit the depot again")

    monkeypatch.setattr(client._client, "post", _boom)

    assert await client.free_minutes("CCC-01", "certified") == 240


async def test_unreachable_depot_reports_no_capacity(monkeypatch):
    client = AvailabilityClient(base_url=DEPOT_URL, cache={})
    _fails(monkeypatch, client)

    assert await client.free_minutes("DDD-01", "certified") == 0


async def test_error_response_reports_no_capacity(monkeypatch):
    client = AvailabilityClient(base_url=DEPOT_URL, cache={})

    async def _post(*_args, **_kwargs):
        return httpx.Response(503, text="down", request=httpx.Request("POST", DEPOT_URL))

    monkeypatch.setattr(client._client, "post", _post)

    assert await client.free_minutes("EEE-01", "certified") == 0


async def test_a_failed_lookup_is_not_cached(monkeypatch):
    client = AvailabilityClient(base_url=DEPOT_URL, cache={})

    _fails(monkeypatch, client)
    assert await client.free_minutes("FFF-01", "certified") == 0

    _answers(monkeypatch, client, 240)
    assert await client.free_minutes("FFF-01", "certified") == 240


async def test_ticket_is_queued_when_the_depot_is_down(monkeypatch):
    client = AvailabilityClient(base_url=DEPOT_URL, cache={})
    _fails(monkeypatch, client)
    monkeypatch.setattr(nodes, "_availability_client", client)

    result = await triage_ticket(
        {
            "ticket_id": "TCK-DOWN",
            "asset_id": "AST-9001",
            "site_code": "SFO-02",
            "issue_code": "NO_POWER",
            "reported_hours_ago": 4,
            "estimated_minutes": 90,
        }
    )

    assert result["decision"] == "needs_scheduling"
    assert result["technician_id"] == ""
