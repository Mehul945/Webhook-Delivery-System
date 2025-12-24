from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import APIRouter, Request, HTTPException, Header

from app.database import Database
from app.logging_config import get_logger
from app.metrics import EVENTS_RECEIVED
from app.models.webhook import (
    WebhookStatus,
    WebhookEvent,
    IngestResponse,
    SearchRequest,
    SearchResponse,
    Aggregations,
    StatusCount,
    EventTypeCount,
    HourlyCount,
)
from app.services.hmac_validator import validate_signature, HMACValidationError

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/ingest", response_model=IngestResponse)
async def ingest_webhook(
    request: Request,
    x_signature: str = Header(..., alias="X-Signature"),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
) -> IngestResponse:
    """
    Ingest a webhook event.

    Accepts arbitrary JSON payloads and validates the HMAC signature.
    Events are stored with status=RECEIVED and processed asynchronously.

    Headers:
    - X-Signature: HMAC-SHA256 signature of the request body
    - X-Idempotency-Key: Optional key to prevent duplicate processing
    """
    # Get raw body for HMAC validation
    body = await request.body()

    # Validate HMAC signature
    try:
        validate_signature(body, x_signature)
    except HMACValidationError as e:
        logger.warning("ingest_hmac_failed: %s", str(e))
        raise HTTPException(status_code=401, detail=str(e))

    # Parse payload
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # Check idempotency key
    db = Database.get_db()
    if x_idempotency_key:
        existing = await db.webhooks.find_one({"idempotency_key": x_idempotency_key})
        if existing:
            logger.info(
                "ingest_idempotent_duplicate: idempotency_key=%s",
                x_idempotency_key,
            )
            return IngestResponse(
                id=str(existing["_id"]),
                status=WebhookStatus(existing["status"]),
                received_at=existing["received_at"],
                message="Duplicate event (idempotency key exists)",
            )

    # Extract event type if present
    event_type = payload.get("event_type") or payload.get("type") or payload.get("event")

    # Create webhook event
    event = WebhookEvent(
        payload=payload,
        status=WebhookStatus.RECEIVED,
        received_at=datetime.now(timezone.utc),
        event_type=event_type,
        idempotency_key=x_idempotency_key,
    )

    # Store in database
    result = await db.webhooks.insert_one(event.to_mongo())
    event_id = str(result.inserted_id)

    # Update metrics
    EVENTS_RECEIVED.labels(event_type=event_type or "unknown").inc()

    logger.info(
        "ingest_success: event_id=%s, event_type=%s",
        event_id,
        event_type,
    )

    return IngestResponse(
        id=event_id,
        status=WebhookStatus.RECEIVED,
        received_at=event.received_at,
    )


@router.post("/search", response_model=SearchResponse)
async def search_webhooks(search: SearchRequest) -> SearchResponse:
    """
    Search and aggregate webhook events.

    Supports:
    - Filtering by status, event_type, timestamp range
    - Aggregations: count by status, count by event_type, hourly histogram
    - Pagination with skip/limit
    """
    db = Database.get_db()

    # Build query
    query: dict[str, Any] = {}

    if search.status:
        query["status"] = search.status.value

    if search.event_type:
        query["event_type"] = search.event_type

    if search.from_date or search.to_date:
        query["received_at"] = {}
        if search.from_date:
            query["received_at"]["$gte"] = search.from_date
        if search.to_date:
            query["received_at"]["$lte"] = search.to_date

    # Get total count
    total = await db.webhooks.count_documents(query)

    # Get events
    cursor = db.webhooks.find(query).skip(search.skip).limit(search.limit).sort("received_at", -1)
    events = [WebhookEvent.from_mongo(doc) async for doc in cursor]

    # Build aggregations if requested
    aggregations = None
    if search.include_aggregations:
        aggregations = await _build_aggregations(db, query)

    logger.info(
        "search_complete: total=%d, returned=%d",
        total,
        len(events),
    )

    return SearchResponse(
        events=events,
        aggregations=aggregations,
        skip=search.skip,
        limit=search.limit,
        total=total,
    )


async def _build_aggregations(db, base_query: dict) -> Aggregations:
    """Build aggregation statistics."""
    aggregations = Aggregations()

    # Count by status
    status_pipeline = [
        {"$match": base_query} if base_query else {"$match": {}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    status_results = await db.webhooks.aggregate(status_pipeline).to_list(None)
    aggregations.by_status = [
        StatusCount(status=r["_id"] or "unknown", count=r["count"])
        for r in status_results
    ]

    # Count by event type
    type_pipeline = [
        {"$match": base_query} if base_query else {"$match": {}},
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
    ]
    type_results = await db.webhooks.aggregate(type_pipeline).to_list(None)
    aggregations.by_event_type = [
        EventTypeCount(event_type=r["_id"] or "unknown", count=r["count"])
        for r in type_results
    ]

    # Hourly histogram
    hourly_pipeline = [
        {"$match": base_query} if base_query else {"$match": {}},
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%dT%H:00:00Z",
                        "date": "$received_at",
                    }
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    hourly_results = await db.webhooks.aggregate(hourly_pipeline).to_list(None)
    aggregations.hourly_histogram = [
        HourlyCount(hour=r["_id"], count=r["count"])
        for r in hourly_results
    ]

    # Total count
    aggregations.total_count = sum(s.count for s in aggregations.by_status)

    return aggregations


@router.get("/{event_id}")
async def get_webhook(event_id: str) -> WebhookEvent:
    """Get a specific webhook event by ID."""
    db = Database.get_db()

    try:
        doc = await db.webhooks.find_one({"_id": ObjectId(event_id)})
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid event ID format")

    if not doc:
        raise HTTPException(status_code=404, detail="Event not found")

    return WebhookEvent.from_mongo(doc)
