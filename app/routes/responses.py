import io
import csv
from typing import Optional, List
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from beanie import PydanticObjectId

from app.models.user import User
from app.models.survey_response import SurveyResponse
from app.models.uploaded_file import UploadedFile
from app.middleware.auth import get_admin_or_super

router = APIRouter(prefix="/responses", tags=["Survey Responses"])


@router.get("")
async def get_responses(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: Optional[str] = "survey_date",
    sort_dir: Optional[str] = "desc",
    _: User = Depends(get_admin_or_super),
):
    query = {}

    # File-based filtering (via uploaded_files join)
    file_ids = []
    if file_id:
        file_ids = [PydanticObjectId(file_id)]
    elif region_id or country_id or ib_version_id:
        file_query = {}
        if region_id:
            file_query["region_id"] = PydanticObjectId(region_id)
        if country_id:
            file_query["country_id"] = PydanticObjectId(country_id)
        if ib_version_id:
            file_query["ib_version_id"] = PydanticObjectId(ib_version_id)
        files = await UploadedFile.find(
            {**file_query, "status": "completed"}
        ).to_list()
        file_ids = [f.id for f in files]

    if file_ids:
        query["file_id"] = {"$in": file_ids}
    elif region_id or country_id or ib_version_id:
        # Filters specified but no matching completed uploads → return empty
        query["file_id"] = {"$in": []}

    if brand_model:
        query["brand_model"] = {"$regex": brand_model, "$options": "i"}
    if survey_location:
        query["survey_location"] = {"$regex": survey_location, "$options": "i"}

    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = datetime.fromisoformat(date_from)
        if date_to:
            date_filter["$lte"] = datetime.fromisoformat(date_to)
        query["survey_date"] = date_filter

    if search:
        query["$or"] = [
            {"brand_model": {"$regex": search, "$options": "i"}},
            {"survey_location": {"$regex": search, "$options": "i"}},
            {"user_name": {"$regex": search, "$options": "i"}},
            {"vin_number": {"$regex": search, "$options": "i"}},
        ]

    skip = (page - 1) * page_size
    sort_key = sort_by or "survey_date"
    sort_order = "-" if sort_dir == "desc" else "+"

    total = await SurveyResponse.find(query).count()
    responses = (
        await SurveyResponse.find(query)
        .sort(f"{sort_order}{sort_key}")
        .skip(skip)
        .limit(page_size)
        .to_list()
    )

    def serialize(r: SurveyResponse) -> dict:
        return {
            "id": str(r.id),
            "file_id": str(r.file_id),
            "survey_date": r.survey_date,
            "survey_location": r.survey_location,
            "brand_model": r.brand_model,
            "vin_number": r.vin_number,
            "odometer_reading": r.odometer_reading,
            "user_name": r.user_name,
            "nps_score": r.nps_score,
            "complaint_groups": r.complaint_groups,
            "full_data": r.full_data,
        }

    return {
        "data": [serialize(r) for r in responses],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.get("/stats")
async def get_stats(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    file_ids = []
    if file_id:
        file_ids = [PydanticObjectId(file_id)]
    elif region_id or country_id or ib_version_id:
        file_query = {}
        if region_id:
            file_query["region_id"] = PydanticObjectId(region_id)
        if country_id:
            file_query["country_id"] = PydanticObjectId(country_id)
        if ib_version_id:
            file_query["ib_version_id"] = PydanticObjectId(ib_version_id)
        files = await UploadedFile.find({**file_query, "status": "completed"}).to_list()
        file_ids = [f.id for f in files]

    query = {}
    if file_ids:
        query["file_id"] = {"$in": file_ids}
    elif region_id or country_id or ib_version_id:
        # Filters specified but no matching completed uploads → return empty
        query["file_id"] = {"$in": []}

    total_records = await SurveyResponse.find(query).count()

    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": None,
            "avg_nps": {"$avg": "$nps_score"},
            "total_complaints": {"$sum": {"$size": "$complaint_groups"}},
            "min_date": {"$min": "$survey_date"},
            "max_date": {"$max": "$survey_date"},
        }},
    ]
    agg = await SurveyResponse.aggregate(pipeline).to_list()
    stats = agg[0] if agg else {}

    # Unique locations
    locations = await SurveyResponse.distinct("survey_location", filter=query if query else None)
    brands = await SurveyResponse.distinct("brand_model", filter=query if query else None)

    return {
        "total_records": total_records,
        "total_complaints": stats.get("total_complaints", 0),
        "unique_locations": len([l for l in locations if l]),
        "average_nps_score": round(stats.get("avg_nps") or 0, 1),
        "total_brands": len([b for b in brands if b]),
        "date_range": {
            "min": stats.get("min_date"),
            "max": stats.get("max_date"),
        },
    }


@router.get("/filter-options")
async def get_filter_options(_: User = Depends(get_admin_or_super)):
    """Get unique values for dropdowns."""
    brands = await SurveyResponse.distinct("brand_model")
    locations = await SurveyResponse.distinct("survey_location")
    return {
        "brands": sorted([b for b in brands if b and b != "Blank"]),
        "locations": sorted([l for l in locations if l and l != "Blank"]),
    }


@router.get("/columns")
async def get_column_headers(_: User = Depends(get_admin_or_super)):
    """Get all 422 column letters mapped to their header titles."""
    from app.utils.column_mapping import get_all_column_headers
    return {"data": get_all_column_headers()}


@router.get("/{response_id}")
async def get_single_response(
    response_id: str,
    _: User = Depends(get_admin_or_super),
):
    r = await SurveyResponse.get(PydanticObjectId(response_id))
    if not r:
        raise HTTPException(status_code=404, detail="Response not found")
    return {
        "id": str(r.id),
        "survey_date": r.survey_date,
        "full_data": r.full_data,
        "complaint_data": r.complaint_data,
        "complaint_groups": r.complaint_groups,
    }


@router.get("/export/csv")
async def export_csv(
    file_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """Export filtered responses as CSV."""
    query = {}
    if file_id:
        query["file_id"] = PydanticObjectId(file_id)
    if brand_model:
        query["brand_model"] = {"$regex": brand_model, "$options": "i"}

    responses = await SurveyResponse.find(query).limit(100000).to_list()

    async def generate():
        output = io.StringIO()
        writer = csv.writer(output)

        # Collect all column keys
        all_keys = set()
        for r in responses:
            all_keys.update(r.full_data.keys())
        sorted_keys = sorted(all_keys)

        writer.writerow(["id", "survey_date", "brand_model", "location", "nps_score"] + sorted_keys)
        output.seek(0)
        yield output.read()
        output.truncate(0)
        output.seek(0)

        for r in responses:
            row = [
                str(r.id), r.survey_date, r.brand_model,
                r.survey_location, r.nps_score,
            ] + [r.full_data.get(k, "") for k in sorted_keys]
            writer.writerow(row)
            output.seek(0)
            yield output.read()
            output.truncate(0)
            output.seek(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=survey_responses.csv"},
    )
