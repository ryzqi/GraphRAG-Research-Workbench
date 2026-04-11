from __future__ import annotations

from app.bootstrap.app_factory import create_app
from app.core.logging import configure_logging
from app.core.settings import get_settings

settings = get_settings()
configure_logging(settings.app_log_level)

app = create_app(settings)
