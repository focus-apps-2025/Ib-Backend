from beanie import Document, PydanticObjectId
from pydantic import Field
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class Country(Document):
    region_id: PydanticObjectId
    name: str
    display_order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "countries"
        indexes = [
            IndexModel([("region_id", ASCENDING), ("name", ASCENDING)], unique=True),
            IndexModel([("region_id", ASCENDING)]),
            IndexModel([("display_order", ASCENDING)]),
        ]
