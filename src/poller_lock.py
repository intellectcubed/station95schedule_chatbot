"""File-based poller lock mechanism to prevent concurrent polling."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)


class PollerLock:
    """Manages file-based locking for poller to prevent concurrent execution."""

    def __init__(self, lock_file: str | None = None):
        """
        Initialize poller lock.

        Args:
            lock_file: Path to lock file (defaults to config setting)
        """
        self.lock_file = Path(lock_file or settings.poller_lock_file)
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.instance_id = str(uuid.uuid4())

    def acquire(self) -> bool:
        """
        Acquire the poller lock.

        Returns:
            True if lock acquired, False if another poller is active

        Raises:
            Exception: If stale lock detected (notifies admin)
        """
        # Check if lock exists
        if self.lock_file.exists():
            try:
                lock_data = json.loads(self.lock_file.read_text())
                started_at = datetime.fromisoformat(lock_data["started_at"])

                # Check if stale (older than configured timeout)
                age = datetime.now() - started_at
                timeout = timedelta(minutes=settings.poller_timeout_minutes)

                if age > timeout:
                    logger.warning(
                        f"Stale poller lock detected (age: {age.total_seconds():.0f}s), "
                        f"overriding"
                    )
                    # Import here to avoid circular dependency
                    from .admin_notifier import notify_admin
                    notify_admin(
                        "poller_timeout",
                        {
                            "started_at": started_at.isoformat(),
                            "age_seconds": age.total_seconds(),
                            "instance_id": lock_data.get("poller_instance_id"),
                        }
                    )
                    # Override stale lock
                    self._create_lock()
                    return True
                else:
                    logger.info(
                        f"Active poller detected (age: {age.total_seconds():.0f}s), "
                        f"yielding"
                    )
                    return False

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Invalid lock file format: {e}, overriding")
                self._create_lock()
                return True

        # No lock exists, create it
        self._create_lock()
        return True

    def _create_lock(self) -> None:
        """Create the lock file with current timestamp."""
        lock_data = {
            "poller_instance_id": self.instance_id,
            "started_at": datetime.now().isoformat(),
            "last_heartbeat": datetime.now().isoformat(),
        }
        self.lock_file.write_text(json.dumps(lock_data, indent=2))
        logger.debug(f"Created poller lock: {self.instance_id}")

    def update_heartbeat(self) -> None:
        """Update the heartbeat timestamp in the lock file."""
        if self.lock_file.exists():
            try:
                lock_data = json.loads(self.lock_file.read_text())
                lock_data["last_heartbeat"] = datetime.now().isoformat()
                self.lock_file.write_text(json.dumps(lock_data, indent=2))
            except Exception as e:
                logger.warning(f"Failed to update heartbeat: {e}")

    def release(self) -> None:
        """Release the poller lock by deleting the lock file."""
        if self.lock_file.exists():
            try:
                self.lock_file.unlink()
                logger.debug(f"Released poller lock: {self.instance_id}")
            except Exception as e:
                logger.error(f"Failed to release lock: {e}")

    def __enter__(self):
        """Context manager entry."""
        if not self.acquire():
            raise RuntimeError("Could not acquire poller lock")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - always release lock."""
        self.release()
        return False  # Don't suppress exceptions
