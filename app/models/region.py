from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class Region(Document):
    name: Indexed(str, unique=True)
    display_order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "regions"
        indexes = [
            IndexModel([("name", ASCENDING)], unique=True),
            IndexModel([("display_order", ASCENDING)]),
        ]
