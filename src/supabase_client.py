"""Supabase client wrapper for database operations."""

import logging
from typing import Any

from supabase import create_client, Client

from .config import settings

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Wrapper around Supabase client for database operations."""

    _instance: Client | None = None

    @classmethod
    def get_client(cls) -> Client:
        """
        Get or create Supabase client singleton.

        Uses service role key for full access to database.

        Returns:
            Authenticated Supabase client
        """
        if cls._instance is None:
            logger.info("Initializing Supabase client")
            try:
                cls._instance = create_client(
                    supabase_url=settings.supabase_url,
                    supabase_key=settings.supabase_key,
                )
                logger.info("Supabase client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                raise

        return cls._instance

    @classmethod
    def reset_client(cls) -> None:
        """Reset the client instance (useful for testing)."""
        cls._instance = None


# Convenience function for getting client
def get_supabase() -> Client:
    """Get the Supabase client instance."""
    return SupabaseClient.get_client()
