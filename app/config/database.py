from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from loguru import logger
from app.config.settings import settings


class Database:
    client: AsyncIOMotorClient = None
    db = None


db_instance = Database()


async def connect_to_mongo():
    """Connect to MongoDB and initialize Beanie ODM."""
    logger.info(f"Connecting to MongoDB: {settings.MONGODB_URL}")
    try:
        db_instance.client = AsyncIOMotorClient(settings.MONGODB_URL)
        db_instance.db = db_instance.client[settings.MONGODB_DB_NAME]

        # Import all models for Beanie initialization
        from app.models.user import User
        from app.models.region import Region
        from app.models.country import Country
        from app.models.ib_version import IBVersion
        from app.models.uploaded_file import UploadedFile
        from app.models.survey_response import SurveyResponse
        from app.models.issue_mapping import IssueMapping
        from app.models.issue_analysis import IssueAnalysis
        from app.models.activity_log import ActivityLog
        from app.models.user_preference import UserPreference
        from app.models.system_setting import SystemSetting

        await init_beanie(
            database=db_instance.db,
            document_models=[
                User,
                Region,
                Country,
                IBVersion,
                UploadedFile,
                SurveyResponse,
                IssueMapping,
                IssueAnalysis,
                ActivityLog,
                UserPreference,
                SystemSetting,
            ],
        )
        logger.success("✅ MongoDB connected and Beanie initialized")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        raise


async def close_mongo_connection():
    """Close MongoDB connection."""
    if db_instance.client:
        db_instance.client.close()
        logger.info("MongoDB connection closed")
