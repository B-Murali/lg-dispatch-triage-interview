"""Entrypoint: `uv run dispatch-agent`."""

from __future__ import annotations

import uvicorn

from dispatch_agent.config import settings


def main() -> None:
    uvicorn.run(
        "dispatch_agent.api:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
