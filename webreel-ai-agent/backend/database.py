"""
MongoDB database connection and initialization.

Uses Motor (async MongoDB driver) for FastAPI integration.
Handles connection lifecycle, index creation, and database access.
"""

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import IndexModel, ASCENDING, DESCENDING
import os
import logging

logger = logging.getLogger(__name__)

MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("MONGO_DB", "webreel")


class Database:
    """MongoDB connection manager with lazy initialization."""
    
    client: AsyncIOMotorClient = None
    
    @classmethod
    async def connect(cls):
        """
        Connect to MongoDB and create indexes.
        
        Called during FastAPI lifespan startup.
        """
        try:
            cls.client = AsyncIOMotorClient(
                MONGO_URL,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
            )
            
            # Test connection
            await cls.client.admin.command('ping')
            
            db = cls.client[DB_NAME]
            
            # Create indexes for jobs collection
            await db.jobs.create_indexes([
                IndexModel([("job_id", ASCENDING)], unique=True, name="job_id_unique"),
                IndexModel([("deleted_at", ASCENDING)], name="soft_delete"),
                
                # Optimized for user dashboard (Phase 3: Authentication)
                # Query: user_id + status + sort by created_at
                IndexModel([
                    ("user_id", ASCENDING),
                    ("status", ASCENDING),
                    ("created_at", DESCENDING)
                ], name="user_dashboard"),
                
                # Optimized for admin dashboard (all users)
                # Query: status + sort by created_at
                IndexModel([
                    ("status", ASCENDING),
                    ("created_at", DESCENDING)
                ], name="admin_dashboard"),
            ])
            
            # Create indexes for users collection
            await db.users.create_indexes([
                IndexModel([("email", ASCENDING)], unique=True, name="email_unique"),
                IndexModel([("google_id", ASCENDING)], unique=True, sparse=True, name="google_id_unique"),
                IndexModel([("verification_token", ASCENDING)], sparse=True, name="verification_token"),
                IndexModel([("reset_token", ASCENDING)], sparse=True, name="reset_token"),
            ])
            
            # Create indexes for cookie_status collection
            await db.cookie_status.create_indexes([
                IndexModel([("service", ASCENDING)], unique=True, name="service_unique"),
            ])
            
            logger.info(f"MongoDB connected: {cls._sanitize_url(MONGO_URL)}")
            logger.info(f"Database: {DB_NAME}")
            
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            logger.warning("Application will continue without MongoDB (in-memory only)")
            cls.client = None
    
    @classmethod
    async def close(cls):
        """
        Close MongoDB connection.
        
        Called during FastAPI lifespan shutdown.
        """
        if cls.client:
            cls.client.close()
            logger.info("MongoDB connection closed")
    
    @classmethod
    def get_db(cls):
        """
        Get database instance.
        
        Returns:
            AsyncIOMotorDatabase: MongoDB database instance
        """
        if cls.client is None:
            return None
        return cls.client[DB_NAME]
    
    @classmethod
    def is_connected(cls) -> bool:
        """Check if MongoDB is connected."""
        return cls.client is not None
    
    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Hide password in MongoDB URL for logging."""
        if "@" in url and "://" in url:
            protocol = url.split("://")[0]
            rest = url.split("://")[1]
            if "@" in rest:
                return f"{protocol}://***@{rest.split('@')[-1]}"
        return url
