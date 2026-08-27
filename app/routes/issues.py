from typing import Optional, List
from fastapi import APIRouter, Depends, Query
from beanie import PydanticObjectId

from app.models.user import User
from app.models.issue_analysis import IssueAnalysis
from app.models.uploaded_file import UploadedFile
from app.models.issue_mapping import IssueMapping
from app.middleware.auth import get_admin_or_super
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
    _: User = Depends(get_admin_or_super),
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
    )



@router.get("/top")
async def get_top_issues(
    limit: int = Query(10, ge=1, le=33),
    file_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    query = {}
    if file_id:
        query["file_id"] = PydanticObjectId(file_id)
    analyses = await IssueAnalysis.find(query).to_list()

    counts: dict = {}
    for analysis in analyses:
        for issue in analysis.issues:
            counts[issue.issue_name] = counts.get(issue.issue_name, 0) + issue.total_complaints

    top = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    return {
        "data": [{"issue_name": n, "count": c} for n, c in top]
    }


@router.get("/trend")
async def get_issue_trend(
    file_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """Return monthly trend data for top 5 issues."""
    from app.models.survey_response import SurveyResponse

    query = {}
    if file_id:
        query["file_id"] = PydanticObjectId(file_id)

    pipeline = [
        {"$match": query},
        {"$unwind": "$complaint_groups"},
        {
            "$group": {
                "_id": {
                    "issue": "$complaint_groups",
                    "year": {"$year": "$survey_date"},
                    "month": {"$month": "$survey_date"},
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"_id.year": 1, "_id.month": 1}},
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list()
    return {"data": results}
