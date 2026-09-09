"""Shared test fixtures."""

from __future__ import annotations

import pytest

from dispatch_agent.graph import nodes
from dispatch_agent.services import dispatch_service

# Free minutes reported by the stubbed depot unless a test says otherwise.
DEFAULT_FREE_MINUTES = 480


@pytest.fixture(autouse=True)
def plenty_of_capacity(monkeypatch):
    """Stub the downstream availability service so tests never touch the network."""

    async def _free_minutes(*_args, **_kwargs) -> int:
        return DEFAULT_FREE_MINUTES

    monkeypatch.setattr(nodes._availability_client, "free_minutes", _free_minutes)


@pytest.fixture
def depot_reporting(monkeypatch):
    """Let a test dictate how many free minutes the depot reports."""

    def _apply(minutes: int) -> None:
        async def _free_minutes(*_args, **_kwargs) -> int:
            return minutes

        monkeypatch.setattr(nodes._availability_client, "free_minutes", _free_minutes)

    return _apply


@pytest.fixture(autouse=True)
def clear_idempotency_ledger():
    """Keep cached results from leaking between tests."""
    dispatch_service._RESULTS.clear()
    yield
    dispatch_service._RESULTS.clear()
