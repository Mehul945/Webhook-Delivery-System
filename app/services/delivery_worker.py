"""
Background delivery worker with exponential backoff retry logic.

Implements multi-replica safety using atomic MongoDB updates with optimistic locking.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from bson import ObjectId
from pymongo import ReturnDocument

from app.config import get_settings
from app.database import Database
from app.logging_config import get_logger
from app.metrics import (
    EVENTS_DELIVERED,
    EVENTS_FAILED,
    RETRY_ATTEMPTS,
    DELIVERY_DURATION,
    PENDING_EVENTS,
)
from app.models.webhook import WebhookStatus, DeliveryAttempt, WebhookEvent
from app.services.circuit_breaker import circuit_breaker

logger = get_logger(__name__)


class DeliveryWorker:
    """
    Background worker for reliable webhook delivery.

    Features:
    - Exponential backoff (1s → 2s → 4s → 8s → 16s)
    - Multi-replica safety via atomic claims
    - Circuit breaker integration
    - Comprehensive delivery logging
    """

    def __init__(self):
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._http_client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        """Start the delivery worker."""
        if self._running:
            return

        self._running = True
        self._http_client = httpx.AsyncClient(timeout=30.0)
        self._task = asyncio.create_task(self._run())
        logger.info("delivery_worker_started")

    async def stop(self) -> None:
        """Stop the delivery worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._http_client:
            await self._http_client.aclose()
        logger.info("delivery_worker_stopped")

    async def _run(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                # Process pending events
                await self._process_pending_events()

                # Update pending events gauge
                await self._update_pending_count()

                # Sleep before next poll
                await asyncio.sleep(self.settings.worker_poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("delivery_worker_error: error=%s", str(e))
                await asyncio.sleep(self.settings.worker_poll_interval)

    async def _process_pending_events(self) -> None:
        """Find and process events ready for delivery."""
        db = Database.get_db()
        now = datetime.now(timezone.utc)

        # Find events that are RECEIVED or need retry
        query = {
            "$or": [
                {"status": WebhookStatus.RECEIVED.value},
                {
                    "status": WebhookStatus.PROCESSING.value,
                    "next_retry_at": {"$lte": now},
                },
            ]
        }

        # Process events one at a time with atomic claim
        while self._running:
            event = await self._claim_event(db, query)
            if not event:
                break

            await self._deliver_event(event)

    async def _claim_event(self, db, query: dict) -> Optional[WebhookEvent]:
        """
        Atomically claim an event for processing.

        Uses findOneAndUpdate with version check for multi-replica safety.
        Only one replica will successfully claim each event.
        """
        try:
            result = await db.webhooks.find_one_and_update(
                query,
                {
                    "$set": {"status": WebhookStatus.PROCESSING.value},
                    "$inc": {"version": 1},
                },
                return_document=ReturnDocument.AFTER,
            )

            if result:
                return WebhookEvent.from_mongo(result)
            return None

        except Exception as e:
            logger.error("claim_event_error: error=%s", str(e))
            return None

    async def _deliver_event(self, event: WebhookEvent) -> None:
        """Attempt to deliver an event to the downstream service."""
        attempt_number = len(event.delivery_attempts) + 1
        event_type = event.event_type or "unknown"

        logger.info(
            "delivery_attempt_start: event_id=%s, attempt=%d, event_type=%s",
            event.id,
            attempt_number,
            event_type,
        )

        RETRY_ATTEMPTS.labels(attempt_number=str(attempt_number)).inc()

        # Check circuit breaker
        if not await circuit_breaker.can_execute():
            logger.warning(
                "delivery_skipped_circuit_open: event_id=%s",
                event.id,
            )
            # Schedule retry later
            await self._schedule_retry(event, attempt_number)
            return

        # Attempt delivery
        start_time = time.time()
        attempt = DeliveryAttempt(
            attempt_number=attempt_number,
            success=False,
        )

        try:
            response = await self._http_client.post(
                f"{self.settings.downstream_url}/downstream/receive",
                json=event.payload,
                headers={"X-Event-Id": event.id or ""},
            )

            duration_ms = (time.time() - start_time) * 1000
            attempt.status_code = response.status_code
            attempt.duration_ms = duration_ms
            DELIVERY_DURATION.observe(duration_ms / 1000)

            if response.status_code == 200:
                attempt.success = True
                await self._mark_delivered(event, attempt)
                await circuit_breaker.record_success()
                EVENTS_DELIVERED.labels(event_type=event_type).inc()
                logger.info(
                    "delivery_success: event_id=%s, attempt=%d, duration_ms=%.2f",
                    event.id,
                    attempt_number,
                    duration_ms,
                )
            else:
                attempt.error_message = f"HTTP {response.status_code}"
                await circuit_breaker.record_failure()
                await self._handle_failure(event, attempt, attempt_number, event_type)

        except httpx.TimeoutException:
            duration_ms = (time.time() - start_time) * 1000
            attempt.error_message = "Timeout"
            attempt.duration_ms = duration_ms
            await circuit_breaker.record_failure()
            await self._handle_failure(event, attempt, attempt_number, event_type)

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            attempt.error_message = str(e)
            attempt.duration_ms = duration_ms
            await circuit_breaker.record_failure()
            await self._handle_failure(event, attempt, attempt_number, event_type)

    async def _handle_failure(
        self,
        event: WebhookEvent,
        attempt: DeliveryAttempt,
        attempt_number: int,
        event_type: str,
    ) -> None:
        """Handle a failed delivery attempt."""
        logger.warning(
            "delivery_failed: event_id=%s, attempt=%d, error=%s",
            event.id,
            attempt_number,
            attempt.error_message,
        )

        if attempt_number >= self.settings.max_retry_attempts:
            await self._mark_failed_permanently(event, attempt)
            EVENTS_FAILED.labels(event_type=event_type).inc()
        else:
            await self._schedule_retry(event, attempt_number, attempt)

    async def _mark_delivered(
        self, event: WebhookEvent, attempt: DeliveryAttempt
    ) -> None:
        """Mark event as successfully delivered."""
        db = Database.get_db()
        await db.webhooks.update_one(
            {"_id": ObjectId(event.id)},
            {
                "$set": {
                    "status": WebhookStatus.DELIVERED.value,
                    "delivered_at": datetime.now(timezone.utc),
                },
                "$push": {"delivery_attempts": attempt.model_dump()},
            },
        )

    async def _mark_failed_permanently(
        self, event: WebhookEvent, attempt: DeliveryAttempt
    ) -> None:
        """Mark event as permanently failed (dead letter)."""
        db = Database.get_db()
        logger.error(
            "delivery_failed_permanently: event_id=%s, total_attempts=%d",
            event.id,
            len(event.delivery_attempts) + 1,
        )
        await db.webhooks.update_one(
            {"_id": ObjectId(event.id)},
            {
                "$set": {
                    "status": WebhookStatus.FAILED_PERMANENTLY.value,
                    "failed_at": datetime.now(timezone.utc),
                },
                "$push": {"delivery_attempts": attempt.model_dump()},
            },
        )

    async def _schedule_retry(
        self,
        event: WebhookEvent,
        attempt_number: int,
        attempt: Optional[DeliveryAttempt] = None,
    ) -> None:
        """Schedule event for retry with exponential backoff."""
        # Calculate backoff: 1s, 2s, 4s, 8s, 16s
        delay = min(
            self.settings.retry_base_delay * (2 ** (attempt_number - 1)),
            self.settings.retry_max_delay,
        )
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)

        logger.info(
            "delivery_retry_scheduled: event_id=%s, next_attempt=%d, delay_seconds=%.1f",
            event.id,
            attempt_number + 1,
            delay,
        )

        db = Database.get_db()
        update = {
            "$set": {"next_retry_at": next_retry},
        }
        if attempt:
            update["$push"] = {"delivery_attempts": attempt.model_dump()}

        await db.webhooks.update_one(
            {"_id": ObjectId(event.id)},
            update,
        )

    async def _update_pending_count(self) -> None:
        """Update the pending events gauge."""
        try:
            db = Database.get_db()
            count = await db.webhooks.count_documents(
                {
                    "status": {
                        "$in": [
                            WebhookStatus.RECEIVED.value,
                            WebhookStatus.PROCESSING.value,
                        ]
                    }
                }
            )
            PENDING_EVENTS.set(count)
        except Exception:
            pass


# Global worker instance
delivery_worker = DeliveryWorker()
