"""Client for interacting with the calendar service."""

import logging
import requests
from typing import Any

from .config import settings
from .models import CalendarCommand

logger = logging.getLogger(__name__)


class CalendarClient:
    """Client for sending commands to the calendar service."""

    def __init__(self, base_url: str | None = None):
        """
        Initialize the calendar client.

        Args:
            base_url: Optional override for calendar service URL
        """
        self.base_url = base_url or settings.calendar_service_url
        logger.info(f"Initialized CalendarClient with base URL: {self.base_url}")

    def send_command(self, command: CalendarCommand) -> dict[str, Any]:
        """
        Send a command to the calendar service.

        Args:
            command: The CalendarCommand to execute

        Returns:
            Response from the calendar service

        Raises:
            requests.RequestException: If the request fails
        """
        params = command.to_query_params()

        # Build full URL for logging
        full_url = f"{self.base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

        logger.info("=" * 60)
        logger.info("CALENDAR SERVICE REQUEST")
        logger.info(f"Action: {command.action}")
        logger.info(f"Squad: {command.squad}")
        logger.info(f"Date: {command.date}")
        logger.info(f"Shift: {command.shift_start}-{command.shift_end}")
        logger.info(f"Preview Mode: {command.preview}")
        logger.info(f"Full URL: {full_url}")
        logger.info("-" * 60)

        try:
            response = requests.get(
                self.base_url,
                params=params,
                timeout=settings.calendar_service_timeout,
            )

            response.raise_for_status()

            # Try to parse JSON response, fall back to text
            try:
                response_data = response.json()

                logger.info("CALENDAR SERVICE RESPONSE")
                logger.info(f"Status Code: {response.status_code}")
                logger.info(f"Response Body:")
                logger.info(f"{response_data}")
                logger.info("=" * 60)

                return response_data
            except ValueError:
                logger.info("CALENDAR SERVICE RESPONSE")
                logger.info(f"Status Code: {response.status_code}")
                logger.info(f"Response Body (text): {response.text}")
                logger.info("=" * 60)

                return {"status": "success", "message": response.text}

        except requests.RequestException as e:
            logger.error("CALENDAR SERVICE ERROR")
            logger.error(f"Error: {e}")
            logger.error("=" * 60)
            raise

    def send_command_with_retry(
        self, command: CalendarCommand, max_retries: int = 3
    ) -> dict[str, Any]:
        """
        Send a command with retry logic.

        Args:
            command: The CalendarCommand to execute
            max_retries: Maximum number of retry attempts

        Returns:
            Response from the calendar service
        """
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.send_command(command)
            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")

                if attempt < max_retries - 1:
                    logger.info("Retrying...")
                    continue
                else:
                    logger.error(f"All {max_retries} attempts failed")
                    raise last_error

        raise last_error

    def get_schedule(
        self, start_date: str, end_date: str, squad: int | None = None
    ) -> dict[str, Any]:
        """
        Fetch the schedule from the calendar service for a date range.

        Args:
            start_date: Start date in YYYYMMDD format
            end_date: End date in YYYYMMDD format (currently only single day supported)
            squad: Optional squad number to filter by

        Returns:
            Dictionary with schedule data from the calendar service

        Raises:
            requests.RequestException: If the request fails
        """
        # Use get_schedule_day action with single date parameter
        params = {
            "action": "get_schedule_day",
            "date": start_date,  # Use start_date as the single date
        }

        if squad is not None:
            params["squad"] = str(squad)

        # Build full URL for logging
        full_url = f"{self.base_url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

        logger.info("=" * 60)
        logger.info("CALENDAR SERVICE REQUEST")
        logger.info(f"Action: get_schedule_day")
        logger.info(f"Date: {start_date}")
        if squad:
            logger.info(f"Squad Filter: {squad}")
        logger.info(f"Full URL: {full_url}")
        logger.info("-" * 60)

        try:
            response = requests.get(
                self.base_url,
                params=params,
                timeout=settings.calendar_service_timeout,
            )

            response.raise_for_status()

            # Try to parse JSON response
            try:
                response_data = response.json()

                logger.info("CALENDAR SERVICE RESPONSE")
                logger.info(f"Status Code: {response.status_code}")
                logger.info(f"Response Body:")
                logger.info(f"{response_data}")
                logger.info("=" * 60)

                return response_data
            except ValueError:
                logger.info("CALENDAR SERVICE RESPONSE")
                logger.info(f"Status Code: {response.status_code}")
                logger.info(f"Response Body (text): {response.text}")
                logger.info("=" * 60)

                return {"status": "success", "data": response.text}

        except requests.RequestException as e:
            logger.error("CALENDAR SERVICE ERROR")
            logger.error(f"Error: {e}")
            logger.error("=" * 60)
            raise
