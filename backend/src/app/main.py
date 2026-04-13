from __future__ import annotations

from app.bootstrap.app_factory import create_app
from app.core.logging import configure_logging
from app.core.settings import get_settings, validate_startup_settings

settings = get_settings()
validate_startup_settings(settings)
configure_logging(settings.core.app_log_level)

app = create_app(settings)
