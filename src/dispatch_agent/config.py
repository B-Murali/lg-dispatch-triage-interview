"""Runtime configuration."""

from __future__ import annotations

import os


class Settings:
    """Process configuration, read from the environment."""

    def __init__(self) -> None:
        self.app_name: str = os.getenv("APP_NAME", "dispatch-agent")
        self.host: str = os.getenv("HOST", "127.0.0.1")
        self.port: int = int(os.getenv("PORT", "8090"))
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # Downstream technician-availability service.
        self.availability_service_url: str = os.getenv(
            "AVAILABILITY_SERVICE_URL", "http://localhost:9201/availability"
        )

        # Dispatch policy knobs.
        self.intake_window_hours: int = int(os.getenv("INTAKE_WINDOW_HOURS", "72"))
        self.capacity_buffer_minutes: int = int(os.getenv("CAPACITY_BUFFER_MINUTES", "30"))
        self.max_auto_dispatch_minutes: int = int(os.getenv("MAX_AUTO_DISPATCH_MINUTES", "240"))


settings = Settings()
