"""
Database connections for MongoDB and Redis.
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from redis.asyncio import Redis
from typing import Optional

from app.config import get_settings


class Database:
    """Manages MongoDB and Redis connections."""

    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None
    redis: Optional[Redis] = None

    @classmethod
    async def connect(cls) -> None:
        """Initialize database connections."""
        settings = get_settings()

        # MongoDB connection
        cls.client = AsyncIOMotorClient(settings.mongodb_uri)
        cls.db = cls.client[settings.mongodb_database]

        # Create indexes for webhooks collection
        await cls.db.webhooks.create_index("status")
        await cls.db.webhooks.create_index("received_at")
        await cls.db.webhooks.create_index("event_type")
        await cls.db.webhooks.create_index([("status", 1), ("next_retry_at", 1)])

        # Redis connection
        cls.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    @classmethod
    async def disconnect(cls) -> None:
        """Close database connections."""
        if cls.client:
            cls.client.close()
        if cls.redis:
            await cls.redis.close()

    @classmethod
    def get_db(cls) -> AsyncIOMotorDatabase:
        """Get MongoDB database instance."""
        if cls.db is None:
            raise RuntimeError("Database not connected. Call Database.connect() first.")
        return cls.db

    @classmethod
    def get_redis(cls) -> Redis:
        """Get Redis instance."""
        if cls.redis is None:
            raise RuntimeError("Redis not connected. Call Database.connect() first.")
        return cls.redis
