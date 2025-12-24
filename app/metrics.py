"""
Prometheus metrics for observability.
"""

from prometheus_client import Counter, Histogram, Gauge


# Event metrics
EVENTS_RECEIVED = Counter(
    "webhook_events_received_total",
    "Total number of webhook events received",
    ["event_type"],
)

EVENTS_DELIVERED = Counter(
    "webhook_events_delivered_total",
    "Total number of webhook events successfully delivered",
    ["event_type"],
)

EVENTS_FAILED = Counter(
    "webhook_events_failed_total",
    "Total number of webhook events that failed permanently",
    ["event_type"],
)

# Retry metrics
RETRY_ATTEMPTS = Counter(
    "webhook_retry_attempts_total",
    "Total number of retry attempts",
    ["attempt_number"],
)

# Delivery timing
DELIVERY_DURATION = Histogram(
    "webhook_delivery_duration_seconds",
    "Time spent delivering webhooks",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

# Queue metrics
PENDING_EVENTS = Gauge(
    "webhook_pending_events",
    "Number of events pending delivery",
)

# Downstream health
CIRCUIT_BREAKER_STATE = Gauge(
    "webhook_circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half-open)",
)
