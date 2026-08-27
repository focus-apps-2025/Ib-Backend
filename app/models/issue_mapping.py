from beanie import Document, Indexed
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class FollowUp(BaseModel):
    column_letter: str
    question_text: str
    display_order: int = 0


class ColumnRange(BaseModel):
    start: str
    end: str
    count: int = 0


class IssueMapping(Document):
    issue_name: Indexed(str, unique=True)
    display_order: int = 0
    column_range: Optional[ColumnRange] = None
    follow_ups: List[FollowUp] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "issue_mapping"
        indexes = [
            IndexModel([("issue_name", ASCENDING)], unique=True),
            IndexModel([("display_order", ASCENDING)]),
        ]
