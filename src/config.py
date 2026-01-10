"""Configuration management for the Station 95 chatbot."""

import os
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Supabase Configuration
    supabase_url: str
    supabase_key: str  # Service role key (has full access, bypasses RLS)

    # OpenAI Configuration (ChatGPT)
    openai_api_key: str

    # GroupMe Configuration
    groupme_bot_id: str
    groupme_api_token: str
    groupme_group_id: str

    # Calendar Service Configuration (Local HTTP only)
    calendar_service_url: str
    calendar_service_timeout: int = 30  # HTTP timeout in seconds

    # Bot Configuration
    confidence_threshold: int = 70
    log_level: str = "INFO"
    roster_file_path: str = "data/roster.json"
    workflow_expiration_hours: int = 24

    # Testing Configuration
    enable_user_impersonation: bool = True  # For testing only - allows {{@username}} prefix
    enable_groupme_posting: bool = True  # If False, messages are logged but not sent to GroupMe

    # System Prompt
    system_prompt_path: str = "ai_prompts/system_prompt.md"

    # Admin Notifications
    admin_groupme_user_id: str = "137549805"  # User ID for admin DMs

    # Poller Settings
    poller_timeout_minutes: int = 30  # Max time before considering poller stale
    poller_lock_file: str = "data/poller.lock"  # Lock file path

    # Message Queue Settings
    message_expiry_hours: int = 24  # Age at which messages expire
    max_retry_attempts: int = 3  # Max retries before admin notification

    # Workflow Settings
    workflow_interaction_limit: int = 2  # Max interactions before escalating to admin

    def validate_config(self) -> None:
        """Validate that all required configuration is present."""
        errors = []

        # Check Supabase configuration
        if not self.supabase_url:
            errors.append("SUPABASE_URL is not set")
        if not self.supabase_key:
            errors.append("SUPABASE_KEY is not set")

        # Check OpenAI configuration
        if not self.openai_api_key:
            errors.append("OPENAI_API_KEY is not set")

        # Check GroupMe configuration
        if not self.groupme_api_token:
            errors.append("GROUPME_API_TOKEN is not set")
        if not self.groupme_group_id:
            errors.append("GROUPME_GROUP_ID is not set")
        if not self.groupme_bot_id:
            errors.append("GROUPME_BOT_ID is not set")

        # Check calendar service
        if not self.calendar_service_url:
            errors.append("CALENDAR_SERVICE_URL is not set")

        if errors:
            raise ValueError(
                "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )


# Global settings instance
settings = Settings()
