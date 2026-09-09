"""Client for the downstream technician-availability service."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from dispatch_agent.config import settings

logger = logging.getLogger(__name__)


class AvailabilityClient:
    """Fetches the free technician minutes left today for a site + skill pool."""

    def __init__(self, base_url: str | None = None, cache: dict[str, int] = {}) -> None:
        self.base_url = base_url or settings.availability_service_url
        self.cache = cache
        self._client = httpx.AsyncClient(timeout=5.0)

    async def free_minutes(self, site_code: str, skill: str) -> int:
        key = site_code
        if key in self.cache:
            return self.cache[key]

        payload: dict[str, Any] = {"site_code": site_code, "skill": skill}
        try:
            response = await self._client.post(self.base_url, json=payload)
            response.raise_for_status()
            minutes = int(response.json()["free_minutes"])
        except Exception:
            # Fail closed: an unusable depot lookup means we cannot promise a
            # technician, so the ticket must fall through to human scheduling.
            logger.warning(
                "availability lookup failed for site=%s skill=%s; reporting no capacity",
                site_code,
                skill,
            )
            return 0

        self.cache[key] = minutes
        return minutes

    async def aclose(self) -> None:
        await self._client.aclose()
