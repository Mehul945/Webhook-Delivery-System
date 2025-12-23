from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# Create FastAPI application
app = FastAPI(
    title="Webhook Delivery System",
    description="Production-grade webhook ingestion and reliable delivery system",
    version="1.0.0",
)



@app.get("/health")
async def health_check() -> dict:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "webhook-delivery-system",
    }


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler."""
    logger.error(
        "unhandled_exception",
        error=str(exc),
        path=request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


