"""
Configuration loader for Job Hunter v1.

All secrets and configuration are loaded from environment variables.
No hardcoded credentials. See .env.example for required variables.
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class SupabaseConfig:
    """Supabase connection configuration."""
    url: str
    service_key: str


@dataclass(frozen=True)
class GeminiConfig:
    """Gemini API configuration."""
    api_key: str
    model: str = "gemini-2.5-flash"
    match_threshold: int = 60  # 0–100 score gate


@dataclass(frozen=True)
class TelegramConfig:
    """Telegram bot configuration."""
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class GmailConfig:
    """Gmail SMTP configuration."""
    sender_address: str
    app_password: str
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_timeout: int = 30  # seconds


@dataclass(frozen=True)
class DispatchConfig:
    """Dispatch worker configuration."""
    max_emails_per_run: int = 5  # Gmail reputation protection
    retry_max: int = 3


@dataclass(frozen=True)
class Config:
    """Top-level application configuration."""
    supabase: SupabaseConfig
    gemini: GeminiConfig
    telegram: TelegramConfig
    gmail: GmailConfig
    dispatch: DispatchConfig = field(default_factory=DispatchConfig)


def _require_env(key: str) -> str:
    """Get a required environment variable or raise."""
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{key}' is not set. "
            f"See .env.example for required variables."
        )
    return value


def load_config() -> Config:
    """
    Load application configuration from environment variables.

    Raises:
        EnvironmentError: If any required variable is missing.
    """
    return Config(
        supabase=SupabaseConfig(
            url=_require_env("SUPABASE_URL"),
            service_key=_require_env("SUPABASE_SERVICE_KEY"),
        ),
        gemini=GeminiConfig(
            api_key=_require_env("GEMINI_API_KEY"),
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            match_threshold=int(os.environ.get("MATCH_THRESHOLD", "60")),
        ),
        telegram=TelegramConfig(
            bot_token=_require_env("TELEGRAM_BOT_TOKEN"),
            chat_id=_require_env("MY_TELEGRAM_CHAT_ID"),
        ),
        gmail=GmailConfig(
            sender_address=os.environ.get("GMAIL_ADDRESS") or _require_env("GMAIL_SENDER_ADDRESS"),
            app_password=_require_env("GMAIL_APP_PASSWORD"),
        ),
        dispatch=DispatchConfig(
            max_emails_per_run=int(os.environ.get("MAX_EMAILS_PER_RUN", "5")),
        ),
    )
