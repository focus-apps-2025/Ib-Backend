from beanie import Document, PydanticObjectId
from pydantic import Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class UserPreference(Document):
    user_id: PydanticObjectId
    hidden_columns: List[str] = Field(default_factory=list)
    column_widths: Dict[str, int] = Field(default_factory=dict)
    default_page_size: int = 25
    default_date_range: str = "last_30_days"
    theme: str = "light"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "user_preferences"
        indexes = [
            IndexModel([("user_id", ASCENDING)], unique=True),
        ]
