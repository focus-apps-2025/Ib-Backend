"""
Region schemas - Region management request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class RegionCreate(BaseModel):
    """Create region request schema."""
    name: str = Field(..., min_length=1, max_length=100)
    display_order: int = 0


class RegionUpdate(BaseModel):
    """Update region request schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    display_order: Optional[int] = None


class RegionResponse(BaseModel):
    """Region response schema."""
    id: str
    name: str
    display_order: int
    country_count: int = 0
    created_at: datetime
    updated_at: datetime


class ReorderRequest(BaseModel):
    """Reorder request schema."""
    ids: List[str]


class RegionListResponse(BaseModel):
    """Region list response schema."""
    data: list[RegionResponse]
    total: int