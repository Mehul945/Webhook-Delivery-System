from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.responses import Response

from app.config import get_settings
from app.database import Database
from app.logging_config import setup_logging, get_logger
from app.routes.webhooks import router as webhooks_router
from app.services.delivery_worker import delivery_worker


setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan manager."""
    settings = get_settings()

    # Startup
    logger.info("application_starting, log_level=%s", settings.log_level)

    await Database.connect()
    logger.info("database_connected")

    await delivery_worker.start()
    logger.info("delivery_worker_started")

    yield

    # Shutdown
    logger.info("application_stopping")

    await delivery_worker.stop()
    await Database.disconnect()

    logger.info("application_stopped")


# Create FastAPI application
app = FastAPI(
    title="Webhook Delivery System",
    description="Production-grade webhook ingestion and reliable delivery system",
    version="1.0.0",
    lifespan=lifespan,
)


# Request ID middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    """Add request ID to all requests for correlation."""
    import uuid

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id

    return response


# Include routers
app.include_router(webhooks_router)


# Health check endpoint
@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "webhook-delivery-system",
    }


# Prometheus metrics endpoint
@app.get("/metrics")
async def metrics() -> Response:
    """Expose Prometheus metrics."""
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler."""
    logger.error(
        "unzhandled_exception: error=%s, path=%s",
        str(exc),
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
