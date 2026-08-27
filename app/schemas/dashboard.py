"""
Dashboard schemas - Dashboard request/response models.
"""
from pydantic import BaseModel
from typing import List, Optional


class DashboardStatsResponse(BaseModel):
    """Dashboard statistics response schema."""
    total_records: int
    total_uploads: int
    total_brands: int
    unique_locations: int
    average_nps: float
    total_complaints: int


class ChartDataPoint(BaseModel):
    """Chart data point schema."""
    label: str
    count: int


class BrandDistributionResponse(BaseModel):
    """Brand distribution response schema."""
    data: list[ChartDataPoint]


class NPSDistributionResponse(BaseModel):
    """NPS distribution response schema."""
    data: list[dict]


class LocationIssueHeatmapResponse(BaseModel):
    """Location-issue heatmap response schema."""
    data: list[dict]