from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field
from typing import Optional, Any
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class SystemSetting(Document):
    key: Indexed(str, unique=True)
    value: Any = None
    description: Optional[str] = None
    updated_by: Optional[PydanticObjectId] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "system_settings"
        indexes = [
            IndexModel([("key", ASCENDING)], unique=True),
        ]
