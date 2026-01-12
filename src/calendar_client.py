"""Client for interacting with the calendar service."""

import json
import logging
import requests
from typing import Any

from .config import settings
from .models import CalendarCommand

logger = logging.getLogger(__name__)
calendar_logger = logging.getLogger("calendar")


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

        # Log to dedicated calendar log
        calendar_logger.info("=" * 80)
        calendar_logger.info("CALENDAR SERVICE REQUEST")
        calendar_logger.info(f"Method: GET")
        calendar_logger.info(f"URL: {self.base_url}")
        calendar_logger.info(f"Parameters:")
        for key, value in params.items():
            calendar_logger.info(f"  {key}: {value}")
        calendar_logger.info(f"Full URL: {full_url}")
        calendar_logger.info("-" * 80)

        logger.info(f"Sending calendar command: {command.action} for squad {command.squad}")

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

                # Log to dedicated calendar log
                calendar_logger.info("CALENDAR SERVICE RESPONSE")
                calendar_logger.info(f"Status Code: {response.status_code}")
                calendar_logger.info(f"Response Headers:")
                for key, value in response.headers.items():
                    calendar_logger.info(f"  {key}: {value}")
                calendar_logger.info(f"Response Body (JSON):")
                calendar_logger.info(json.dumps(response_data, indent=2))
                calendar_logger.info("=" * 80)

                logger.info(f"Calendar command successful: {response.status_code}")
                return response_data
            except ValueError:
                # Log text response
                calendar_logger.info("CALENDAR SERVICE RESPONSE")
                calendar_logger.info(f"Status Code: {response.status_code}")
                calendar_logger.info(f"Response Headers:")
                for key, value in response.headers.items():
                    calendar_logger.info(f"  {key}: {value}")
                calendar_logger.info(f"Response Body (text):")
                calendar_logger.info(response.text)
                calendar_logger.info("=" * 80)

                logger.info(f"Calendar command successful: {response.status_code}")
                return {"status": "success", "message": response.text}

        except requests.RequestException as e:
            # Log error to dedicated calendar log
            calendar_logger.error("CALENDAR SERVICE ERROR")
            calendar_logger.error(f"Error Type: {type(e).__name__}")
            calendar_logger.error(f"Error Message: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                calendar_logger.error(f"Response Status Code: {e.response.status_code}")
                calendar_logger.error(f"Response Body: {e.response.text}")
            calendar_logger.error("=" * 80)

            logger.error(f"Calendar service error: {e}")
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

        # Log to dedicated calendar log
        calendar_logger.info("=" * 80)
        calendar_logger.info("CALENDAR SERVICE REQUEST (GET SCHEDULE)")
        calendar_logger.info(f"Method: GET")
        calendar_logger.info(f"URL: {self.base_url}")
        calendar_logger.info(f"Parameters:")
        for key, value in params.items():
            calendar_logger.info(f"  {key}: {value}")
        calendar_logger.info(f"Full URL: {full_url}")
        calendar_logger.info("-" * 80)

        logger.info(f"Fetching schedule for date: {start_date}")

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

                # Log to dedicated calendar log
                calendar_logger.info("CALENDAR SERVICE RESPONSE (GET SCHEDULE)")
                calendar_logger.info(f"Status Code: {response.status_code}")
                calendar_logger.info(f"Response Headers:")
                for key, value in response.headers.items():
                    calendar_logger.info(f"  {key}: {value}")
                calendar_logger.info(f"Response Body (JSON):")
                calendar_logger.info(json.dumps(response_data, indent=2))
                calendar_logger.info("=" * 80)

                logger.info(f"Schedule fetch successful: {response.status_code}")
                return response_data
            except ValueError:
                # Log text response
                calendar_logger.info("CALENDAR SERVICE RESPONSE (GET SCHEDULE)")
                calendar_logger.info(f"Status Code: {response.status_code}")
                calendar_logger.info(f"Response Headers:")
                for key, value in response.headers.items():
                    calendar_logger.info(f"  {key}: {value}")
                calendar_logger.info(f"Response Body (text):")
                calendar_logger.info(response.text)
                calendar_logger.info("=" * 80)

                logger.info(f"Schedule fetch successful: {response.status_code}")
                return {"status": "success", "data": response.text}

        except requests.RequestException as e:
            # Log error to dedicated calendar log
            calendar_logger.error("CALENDAR SERVICE ERROR (GET SCHEDULE)")
            calendar_logger.error(f"Error Type: {type(e).__name__}")
            calendar_logger.error(f"Error Message: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                calendar_logger.error(f"Response Status Code: {e.response.status_code}")
                calendar_logger.error(f"Response Body: {e.response.text}")
            calendar_logger.error("=" * 80)

            logger.error(f"Calendar service error: {e}")
            raise
