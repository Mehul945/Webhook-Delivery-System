# Downstream Service Dockerfile
FROM python:3.11-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /appw

# Install dependencies directly (minimal for downstream service)
RUN uv pip install --system fastapi uvicorn

# Copy application
COPY downstream/main.py ./main.py

# Expose port
EXPOSE 8001

# Run the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
