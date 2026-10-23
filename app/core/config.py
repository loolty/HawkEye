"""
Application configuration.

All secrets and environment-specific values are read from a `.env` file
(see `.env.example`) via python-dotenv. Never hard-code credentials here.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# backend/ -> root of the backend
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env from the backend root only (avoid picking up stray env files).
load_dotenv(BASE_DIR / ".env")


def _env(key: str, default: str) -> str:
    value = os.getenv(key)
    return value if value not in (None, "") else default


@dataclass(frozen=True)
class Settings:
    """Central, read-only application settings."""

    # Application
    APP_NAME: str = _env("APP_NAME", "Hawkeyes Optical System")
    APP_ENV: str = _env("APP_ENV", "development")
    DEBUG: bool = _env("DEBUG", "true").lower() in {"1", "true", "yes"}

    # Database
    DB_HOST: str = _env("DB_HOST", "localhost")
    DB_PORT: int = int(_env("DB_PORT", "3306"))
    DB_USER: str = _env("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = _env("DB_NAME", "hawkeyes_db")

    # Security
    SECRET_KEY: str = _env("SECRET_KEY", "insecure-dev-secret-change-me")
    SECURITY_ITERATIONS: int = int(_env("SECURITY_ITERATIONS", "390000"))

    # Scheduler / follow-ups
    APPOINTMENT_REMINDER_HOURS: int = int(_env("APPOINTMENT_REMINDER_HOURS", "24"))

    @property
    def sqlalchemy_url(self) -> str:
        """Connection URL for the Hawkeyes database (used at runtime)."""
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
        )

    @property
    def serverless_url(self) -> str:
        """Connection URL without a database (used to bootstrap the DB itself)."""
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/?charset=utf8mb4"
        )


settings = Settings()


def validate_settings() -> list[str]:
    """Return a list of human-readable configuration problems (empty = OK)."""
    problems: list[str] = []
    if not settings.DB_PASSWORD and settings.APP_ENV == "production":
        problems.append("DB_PASSWORD is empty in a production environment.")
    if settings.SECRET_KEY in ("", "insecure-dev-secret-change-me"):
        problems.append("SECRET_KEY is not set to a secure value.")
    if not 1 <= settings.DB_PORT <= 65535:
        problems.append("DB_PORT must be between 1 and 65535.")
    return problems
