from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from beanie import PydanticObjectId

from app.models.user import User
from app.models.issue_analysis import IssueAnalysis
from app.models.uploaded_file import UploadedFile
from app.models.issue_mapping import IssueMapping
from app.middleware.auth import get_admin_or_super
from app.middleware.scope import ScopedUser, get_scoped_user
from app.utils.column_mapping import ISSUE_COLUMN_RANGE_MAPPING, get_question_text_for_column

from app.controllers.issue_controller import IssueController

router = APIRouter(prefix="/issues", tags=["Issues Analysis"])


@router.get("")
async def list_issues(_: User = Depends(get_admin_or_super)):
    """Return the 33 issue definitions with column ranges."""
    return await IssueController.list_issues()


@router.get("/analysis")
async def get_issue_analysis(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    issue_name: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    """
    Get issue analysis with brand-wise breakdown of sub-issues on the fly.
    """
    return await IssueController.get_issue_analysis(
        file_id=file_id,
        region_id=region_id,
        country_id=country_id,
        ib_version_id=ib_version_id,
        issue_name=issue_name,
        brand_model=brand_model,
        survey_location=survey_location,
        date_from=date_from,
        date_to=date_to,
        search=search,
        scoped_user=scoped_user,
    )


@router.get("/top")
async def get_top_issues(
    limit: int = Query(10, ge=1, le=33),
    file_id: Optional[str] = None,
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    return await IssueController.get_top_issues(
        limit=limit,
        file_id=file_id,
        scoped_user=scoped_user,
    )


@router.get("/trend")
async def get_issue_trend(
    file_id: Optional[str] = None,
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    """Return monthly trend data for top 5 issues."""
    return await IssueController.get_issue_trend(
        file_id=file_id,
        scoped_user=scoped_user,
    )
