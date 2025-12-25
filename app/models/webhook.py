from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict
from bson import ObjectId


class WebhookStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED_PERMANENTLY = "FAILED_PERMANENTLY"


class DeliveryAttempt(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    attempt_number: int
    status_code: Optional[int] = None
    success: bool
    error_message: Optional[str] = None
    duration_ms: Optional[float] = None


class WebhookEvent(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    payload: dict[str, Any]
    status: WebhookStatus = WebhookStatus.RECEIVED
    received_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: Optional[str] = None
    delivery_attempts: list[DeliveryAttempt] = Field(default_factory=list)
    version: int = 1
    next_retry_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None

    model_config = ConfigDict(
        populate_by_name=True,
        json_encoders={ObjectId: str},
    )

    def to_mongo(self) -> dict:
        data = self.model_dump(by_alias=True, exclude={"id"})
        return data

    @classmethod
    def from_mongo(cls, doc: dict) -> "WebhookEvent":
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        return cls(**doc)


class IngestRequest(BaseModel):
    pass

class IngestResponse(BaseModel):
    id: str
    status: WebhookStatus
    received_at: datetime
    message: str = "Webhook received successfully"


class SearchRequest(BaseModel):
    status: Optional[WebhookStatus] = None
    event_type: Optional[str] = None
    from_date: Optional[datetime] = None
    to_date: Optional[datetime] = None
    search_query: Optional[str] = None
    skip: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=100)
    include_aggregations: bool = True


class StatusCount(BaseModel):
    status: str
    count: int


class EventTypeCount(BaseModel):
    event_type: str
    count: int


class HourlyCount(BaseModel):
    hour: str
    count: int


class Aggregations(BaseModel):
    by_status: list[StatusCount] = Field(default_factory=list)
    by_event_type: list[EventTypeCount] = Field(default_factory=list)
    hourly_histogram: list[HourlyCount] = Field(default_factory=list)
    total_count: int = 0


class SearchResponse(BaseModel):
    events: list[WebhookEvent]
    aggregations: Optional[Aggregations] = None
    skip: int
    limit: int
    total: int
