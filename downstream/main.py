import asyncio
import logging
import random
import time
from collections import deque
from typing import Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

# Setup basic logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Downstream Mock Service",
    description="Mock downstream service with rate limiting and random failures",
    version="1.0.0",
)


class RateLimiter:
    def __init__(self, max_requests: int = 3, window_seconds: float = 1.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: deque[float] = deque()

    def is_allowed(self) -> bool:
        """Check if a request is allowed under rate limit."""
        now = time.time()

        # Remove expired timestamps
        while self.requests and now - self.requests[0] > self.window_seconds:
            self.requests.popleft()

        # Check if under limit
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True

        return False


# Global rate limiter: 3 requests per second
rate_limiter = RateLimiter(max_requests=3, window_seconds=1.0)

# Failure injection settings
FAILURE_RATE = 0.15  # 15% failure rate (between 10-20%)
TIMEOUT_PROBABILITY = 0.4  # 40% of failures are timeouts
ERROR_500_PROBABILITY = 0.35  # 35% of failures are 500 errors
# Remaining 25% of failures are 429 errors


@app.post("/downstream/receive")
async def receive_webhook(request: Request) -> dict[str, Any]:
    """
    Receive webhook events from the upstream service.

    Implements:
    - Rate limiting (3 req/sec) -> 429 Too Many Requests
    - Random failures (10-20%):
      - 500 Internal Server Error
      - 429 Too Many Requests
      - Timeout (2-5 seconds delay)
    """
    event_id = request.headers.get("X-Event-Id", "unknown")

    # Check rate limit
    if not rate_limiter.is_allowed():
        logger.warning(
            "rate_limit_exceeded: event_id=%s",
            event_id,
        )
        raise HTTPException(
            status_code=429,
            detail="Too Many Requests - Rate limit exceeded",
        )

    # Random failure injection
    if random.random() < FAILURE_RATE:
        failure_type = random.random()

        if failure_type < TIMEOUT_PROBABILITY:
            # Simulate timeout (2-5 seconds)
            delay = random.uniform(2.0, 5.0)
            logger.info(
                "injecting_timeout: event_id=%s, delay_seconds=%s",
                event_id,
                delay,
            )
            await asyncio.sleep(delay)
            # After delay, either succeed or fail
            if random.random() < 0.5:
                raise HTTPException(
                    status_code=504,
                    detail="Gateway Timeout",
                )

        elif failure_type < TIMEOUT_PROBABILITY + ERROR_500_PROBABILITY:
            # Return 500 error
            logger.info(
                "injecting_500_error: event_id=%s",
                event_id,
            )
            raise HTTPException(
                status_code=500,
                detail="Internal Server Error - Simulated failure",
            )

        else:
            # Return 429 error
            logger.info(
                "injecting_429_error: event_id=%s",
                event_id,
            )
            raise HTTPException(
                status_code=429,
                detail="Too Many Requests - Simulated failure",
            )

    # Parse payload
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    logger.info(
        "webhook_received: event_id=%s, payload_size=%d",
        event_id,
        len(str(payload)),
    )

    return {
        "status": "received",
        "event_id": event_id,
        "message": "Webhook processed successfully",
    }


@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "downstream-mock",
    }


@app.get("/stats")
async def get_stats() -> dict:
    """Get rate limiter stats."""
    return {
        "current_window_requests": len(rate_limiter.requests),
        "max_requests_per_second": rate_limiter.max_requests,
        "failure_rate": FAILURE_RATE,
    }
