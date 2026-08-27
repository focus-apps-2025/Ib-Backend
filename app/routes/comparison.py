from fastapi import APIRouter, Depends
from typing import Optional

from app.models.user import User
from app.middleware.auth import get_admin_or_super
from app.routes.dashboard import brand_comparison, brand_topics

router = APIRouter(prefix="/comparison", tags=["Comparison"])


@router.get("/brand-passive-issues")
async def get_brand_passive_issues(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """Alias for dashboard brand-comparison endpoint."""
    return await brand_comparison(
        file_id=file_id,
        region_id=region_id,
        country_id=country_id,
        ib_version_id=ib_version_id,
    )


@router.get("/brand-topics")
async def get_brand_topics_endpoint(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """Alias for dashboard brand-topics endpoint."""
    return await brand_topics(
        file_id=file_id,
        region_id=region_id,
        country_id=country_id,
        ib_version_id=ib_version_id,
    )
