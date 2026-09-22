from beanie import Document, Indexed, PydanticObjectId
from pydantic import Field
from typing import Optional, List
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class UserScope(Document):
    user_id: Indexed(PydanticObjectId, unique=True)

    all_regions: bool = True
    region_ids: List[PydanticObjectId] = Field(default_factory=list)

    all_countries: bool = True
    country_ids: List[PydanticObjectId] = Field(default_factory=list)

    all_ib_versions: bool = True
    ib_version_ids: List[PydanticObjectId] = Field(default_factory=list)

    all_brands: bool = True
    brand_models: List[str] = Field(default_factory=list)

    all_cities: bool = True
    survey_locations: List[str] = Field(default_factory=list)

    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "user_scopes"
        indexes = [
            IndexModel([("user_id", ASCENDING)], unique=True),
        ]
