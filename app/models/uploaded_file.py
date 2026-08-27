from beanie import Document, PydanticObjectId
from pydantic import Field
from typing import Optional
from datetime import datetime
from pymongo import IndexModel, ASCENDING, DESCENDING


class UploadedFile(Document):
    region_id: PydanticObjectId
    country_id: PydanticObjectId
    ib_version_id: PydanticObjectId
    uploaded_by: PydanticObjectId
    file_name: str
    file_path: str
    file_size: Optional[int] = 0
    total_records: int = 0
    processed_records: int = 0
    status: str = "processing"  # 'processing' | 'completed' | 'failed' | 'partial'
    error_message: Optional[str] = None
    celery_task_id: Optional[str] = None
    upload_started_at: datetime = Field(default_factory=datetime.utcnow)
    upload_completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "uploaded_files"
        indexes = [
            IndexModel([("region_id", ASCENDING)]),
            IndexModel([("country_id", ASCENDING)]),
            IndexModel([("ib_version_id", ASCENDING)]),
            IndexModel([("uploaded_by", ASCENDING)]),
            IndexModel([("status", ASCENDING)]),
            IndexModel([("created_at", DESCENDING)]),
        ]
