"""
IB Version schemas - IB version management request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class IBVersionCreate(BaseModel):
    """Create IB version request schema."""
    name: str = Field(..., min_length=1, max_length=50)
    display_order: int = 0


class IBVersionUpdate(BaseModel):
    """Update IB version request schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    display_order: Optional[int] = None


class IBVersionResponse(BaseModel):
    """IB version response schema."""
    id: str
    name: str
    display_order: int
    created_at: datetime
    updated_at: datetime


class IBVersionListResponse(BaseModel):
    """IB version list response schema."""
    data: list[IBVersionResponse]