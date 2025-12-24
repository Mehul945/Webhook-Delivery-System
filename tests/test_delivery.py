"""
Tests for delivery worker retry logic.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch, MagicMock

from app.models.webhook import WebhookStatus, DeliveryAttempt, WebhookEvent
from app.config import get_settings


class TestExponentialBackoff:
    """Test exponential backoff calculations."""

    def test_backoff_delays(self):
        """Test that backoff delays follow 1s, 2s, 4s, 8s, 16s pattern."""
        settings = get_settings()
        base_delay = settings.retry_base_delay
        max_delay = settings.retry_max_delay

        expected_delays = [1, 2, 4, 8, 16]

        for attempt_number, expected in enumerate(expected_delays, start=1):
            delay = min(
                base_delay * (2 ** (attempt_number - 1)),
                max_delay,
            )
            assert delay == expected, f"Attempt {attempt_number}: expected {expected}s, got {delay}s"

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        settings = get_settings()
        base_delay = settings.retry_base_delay
        max_delay = settings.retry_max_delay

        # Large attempt number should still be capped
        delay = min(
            base_delay * (2 ** 10),
            max_delay,
        )
        assert delay == max_delay


class TestDeliveryAttempt:
    """Test DeliveryAttempt model."""

    def test_create_successful_attempt(self):
        """Test creating a successful delivery attempt."""
        attempt = DeliveryAttempt(
            attempt_number=1,
            status_code=200,
            success=True,
            duration_ms=150.5,
        )

        assert attempt.attempt_number == 1
        assert attempt.status_code == 200
        assert attempt.success is True
        assert attempt.duration_ms == 150.5
        assert attempt.error_message is None

    def test_create_failed_attempt(self):
        """Test creating a failed delivery attempt."""
        attempt = DeliveryAttempt(
            attempt_number=2,
            status_code=500,
            success=False,
            error_message="Internal Server Error",
            duration_ms=2500.0,
        )

        assert attempt.attempt_number == 2
        assert attempt.status_code == 500
        assert attempt.success is False
        assert attempt.error_message == "Internal Server Error"

    def test_create_timeout_attempt(self):
        """Test creating a timeout delivery attempt."""
        attempt = DeliveryAttempt(
            attempt_number=3,
            success=False,
            error_message="Timeout",
            duration_ms=30000.0,
        )

        assert attempt.status_code is None
        assert attempt.error_message == "Timeout"


class TestWebhookEvent:
    """Test WebhookEvent model."""

    def test_create_event(self):
        """Test creating a webhook event."""
        event = WebhookEvent(
            payload={"event": "test", "data": "hello"},
            event_type="test",
        )

        assert event.status == WebhookStatus.RECEIVED
        assert event.payload == {"event": "test", "data": "hello"}
        assert event.event_type == "test"
        assert event.version == 1
        assert len(event.delivery_attempts) == 0

    def test_event_to_mongo(self):
        """Test converting event to MongoDB document."""
        event = WebhookEvent(
            payload={"event": "test"},
            event_type="test",
        )

        doc = event.to_mongo()

        assert "payload" in doc
        assert "status" in doc
        assert "received_at" in doc
        assert "_id" not in doc  # ID is excluded

    def test_event_from_mongo(self):
        """Test creating event from MongoDB document."""
        doc = {
            "_id": "507f1f77bcf86cd799439011",
            "payload": {"event": "test"},
            "status": "DELIVERED",
            "received_at": datetime.now(timezone.utc),
            "event_type": "test",
            "version": 2,
            "delivery_attempts": [],
        }

        event = WebhookEvent.from_mongo(doc)

        assert event.id == "507f1f77bcf86cd799439011"
        assert event.status == WebhookStatus.DELIVERED
        assert event.version == 2
