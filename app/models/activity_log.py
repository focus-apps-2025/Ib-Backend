from beanie import Document, PydanticObjectId
from pydantic import Field
from typing import Optional, Dict, Any
from datetime import datetime
from pymongo import IndexModel, ASCENDING, DESCENDING


class ActivityLog(Document):
    user_id: Optional[PydanticObjectId] = None
    username: Optional[str] = None
    action: str  # login|logout|upload|export|delete|create|update|view
    details: Optional[Dict[str, Any]] = Field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "activity_logs"
        indexes = [
            IndexModel([("user_id", ASCENDING)]),
            IndexModel([("action", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
