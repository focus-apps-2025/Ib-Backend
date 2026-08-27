"""
Response schemas - Survey response request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class SurveyResponseSchema(BaseModel):
    """Survey response schema."""
    id: str
    file_id: str
    survey_date: Optional[datetime] = None
    survey_location: Optional[str] = None
    brand_model: Optional[str] = None
    vin_number: Optional[str] = None
    odometer_reading: Optional[float] = None
    user_name: Optional[str] = None
    user_age: Optional[float] = None
    user_age_group: Optional[str] = None
    user_profession: Optional[str] = None
    nps_score: Optional[float] = None
    complaint_groups: List[str] = Field(default_factory=list)
    full_data: Dict[str, Any] = Field(default_factory=dict)
    row_index: int = 0
    created_at: datetime


class SurveyResponseListResponse(BaseModel):
    """Survey response list response schema."""
    data: list[SurveyResponseSchema]
    total: int
    page: int
    page_size: int
    total_pages: int


class SurveyResponseStats(BaseModel):
    """Survey response statistics."""
    total_records: int
    total_complaints: int
    unique_locations: int
    average_nps_score: float
    total_brands: int
    date_range: Dict[str, Optional[datetime]]


class FilterOptionsResponse(BaseModel):
    """Filter options response schema."""
    brands: List[str]
    locations: List[str]