from __future__ import annotations

from enum import StrEnum


class AppEnv(StrEnum):
    DEV = "dev"
    TEST = "test"
    PROD = "prod"

    @property
    def is_development_like(self) -> bool:
        return self in {AppEnv.DEV, AppEnv.TEST}

    @classmethod
    def from_value(cls, value: object | None) -> "AppEnv":
        if isinstance(value, cls):
            return value

        raw = "dev" if value is None else str(value)
        normalized = raw.strip().lower()

        aliases = {
            "dev": cls.DEV,
            "development": cls.DEV,
            "local": cls.DEV,
            "test": cls.TEST,
            "testing": cls.TEST,
            "prod": cls.PROD,
            "production": cls.PROD,
        }

        try:
            return aliases[normalized]
        except KeyError as exc:
            allowed = "', '".join(sorted(aliases))
            raise ValueError(f"APP_ENV must be one of: '{allowed}'") from exc
