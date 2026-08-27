"""
Upload schemas - File upload request/response models.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class UploadRequest(BaseModel):
    """Upload request schema."""
    region_id: str
    country_id: str
    ib_version_id: str


class UploadResponse(BaseModel):
    """Upload response schema."""
    file_id: str
    file_name: str
    status: str
    message: str


class UploadProgressResponse(BaseModel):
    """Upload progress response schema."""
    progress: float
    status: str
    processed_records: int
    total_records: int
    message: str
    updated_at: str


class UploadedFileResponse(BaseModel):
    """Uploaded file response schema."""
    id: str
    file_name: str
    file_size: int
    region_id: str
    region_name: str
    country_id: str
    country_name: str
    ib_version_id: str
    ib_version_name: str
    uploaded_by: str
    uploader_name: str
    total_records: int
    processed_records: int
    status: str
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    upload_started_at: datetime
    upload_completed_at: Optional[datetime] = None
    created_at: datetime


class UploadListResponse(BaseModel):
    """Upload list response schema."""
    data: list[UploadedFileResponse]
    total: int
    page: int
    page_size: int
    total_pages: int