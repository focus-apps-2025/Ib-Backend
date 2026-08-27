"""
Country schemas - Country management request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CountryCreate(BaseModel):
    """Create country request schema."""
    region_id: str
    name: str = Field(..., min_length=1, max_length=100)
    display_order: int = 0


class CountryUpdate(BaseModel):
    """Update country request schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    region_id: Optional[str] = None
    display_order: Optional[int] = None


class CountryResponse(BaseModel):
    """Country response schema."""
    id: str
    region_id: str
    region_name: str = "Unknown"
    name: str
    display_order: int
    created_at: datetime
    updated_at: datetime


class CountryListResponse(BaseModel):
    """Country list response schema."""
    data: list[CountryResponse]
    total: int