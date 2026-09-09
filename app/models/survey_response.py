from beanie import Document, PydanticObjectId
from pydantic import Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from pymongo import IndexModel, ASCENDING, DESCENDING


class SurveyResponse(Document):
    file_id: PydanticObjectId

    # ─── Indexed key fields for fast filtering ──────────────────
    survey_date: Optional[datetime] = None
    survey_location: Optional[str] = None
    brand_model: Optional[str] = None
    vin_number: Optional[str] = None
    odometer_reading: Optional[float] = None
    user_name: Optional[str] = None
    user_age: Optional[float] = None
    user_age_group: Optional[str] = None
    user_profession: Optional[str] = None
    mode_of_purchase: Optional[str] = None
    ownership: Optional[str] = None
    nps_score: Optional[float] = None
    
    # ─── New NPS fields ─────────────────────────────────────────
    recommend_vehicle: Optional[str] = None
    recommend_score: Optional[float] = None
    recommend_category: Optional[str] = None
    duration_of_usage: Optional[str] = None

    # ─── Service Frequency fields (Column BP & BQ) ─────────────
    service_freq_time: Optional[str] = None
    service_freq_kms: Optional[str] = None

    # ─── All 422 columns stored as document ─────────────────────
    full_data: Dict[str, Any] = Field(default_factory=dict)

    # ─── Complaint section columns EL-OD ────────────────────────
    complaint_data: Dict[str, Any] = Field(default_factory=dict)

    # ─── Issues from "Complaint group (L2)" column ───────────────
    complaint_groups: List[str] = Field(default_factory=list)

    # ─── Passive/Good feedback from columns AU-BM, grouped by topic ──
    passive_data: Dict[str, List[str]] = Field(default_factory=dict)

    row_index: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "survey_responses"
        indexes = [
            IndexModel([("file_id", ASCENDING)]),
            IndexModel([("survey_date", ASCENDING)]),
            IndexModel([("survey_location", ASCENDING)]),
            IndexModel([("brand_model", ASCENDING)]),
            IndexModel([("user_age_group", ASCENDING)]),
            IndexModel([("nps_score", ASCENDING)]),
            IndexModel([("complaint_groups", ASCENDING)]),
            IndexModel([
                ("file_id", ASCENDING),
                ("survey_date", DESCENDING),
                ("survey_location", ASCENDING),
                ("brand_model", ASCENDING),
            ]),
        ]
