from datetime import datetime
from typing import List, Optional
from beanie import Document
from pydantic import BaseModel, Field


class PhotoItemSchema(BaseModel):
    id: str
    url: str
    name: str
    s3_key: Optional[str] = None
    date: str = Field(default_factory=lambda: datetime.utcnow().strftime("%b %d, %Y"))
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class MarketFeedback(Document):
    remark_key: str = Field(..., index=True, unique=True)
    issue_name: Optional[str] = None
    sub_issue_title: Optional[str] = None
    remark: Optional[str] = ""
    content: Optional[str] = ""
    photos: List[PhotoItemSchema] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "market_feedback"
