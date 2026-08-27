from beanie import Document, Indexed
from pydantic import Field
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class IBVersion(Document):
    name: Indexed(str, unique=True)  # IB1, IB2, IB3, IB4, IB5
    display_order: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "ib_versions"
        indexes = [
            IndexModel([("name", ASCENDING)], unique=True),
            IndexModel([("display_order", ASCENDING)]),
        ]
