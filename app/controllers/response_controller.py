"""
Response controller - Business logic for survey response management.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.survey_response import SurveyResponse
from app.models.uploaded_file import UploadedFile


class ResponseController:
    """Controller for survey response operations."""
    
    @staticmethod
    async def get_responses(
        page: int = 1,
        page_size: int = 25,
        file_id: Optional[str] = None,
        region_id: Optional[str] = None,
        country_id: Optional[str] = None,
        ib_version_id: Optional[str] = None,
        brand_model: Optional[str] = None,
        survey_location: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "survey_date",
        sort_dir: str = "desc",
    ) -> Dict[str, Any]:
        """
        Get survey responses with filters and pagination.
        """
        query = {}

        # File-based filtering
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

        return {
            "data": [ResponseController._serialize_response(r) for r in responses],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @staticmethod
    async def get_response_stats(
        file_id: Optional[str] = None,
        region_id: Optional[str] = None,
        country_id: Optional[str] = None,
        ib_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get statistics for survey responses.
        """
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

    @staticmethod
    async def get_filter_options() -> Dict[str, Any]:
        """
        Get unique filter options for dropdowns.
        """
        brands = await SurveyResponse.distinct("brand_model")
        locations = await SurveyResponse.distinct("survey_location")
        return {
            "brands": sorted([b for b in brands if b and b != "Blank"]),
            "locations": sorted([l for l in locations if l and l != "Blank"]),
        }

    @staticmethod
    async def get_single_response(response_id: str) -> Dict[str, Any]:
        """
        Get a single survey response by ID.
        """
        r = await SurveyResponse.get(PydanticObjectId(response_id))
        if not r:
            raise HTTPException(status_code=404, detail="Response not found")
            
        return {
            "id": str(r.id),
            "file_id": str(r.file_id),
            "survey_date": r.survey_date,
            "survey_location": r.survey_location,
            "brand_model": r.brand_model,
            "vin_number": r.vin_number,
            "odometer_reading": r.odometer_reading,
            "user_name": r.user_name,
            "user_age": r.user_age,
            "user_age_group": r.user_age_group,
            "user_profession": r.user_profession,
            "nps_score": r.nps_score,
            "full_data": r.full_data,
            "complaint_data": r.complaint_data,
            "complaint_groups": r.complaint_groups,
            "row_index": r.row_index,
            "created_at": r.created_at,
        }

    @staticmethod
    def _serialize_response(r: SurveyResponse) -> Dict[str, Any]:
        """
        Serialize SurveyResponse model to dictionary.
        """
        return {
            "id": str(r.id),
            "file_id": str(r.file_id),
            "survey_date": r.survey_date,
            "survey_location": r.survey_location,
            "brand_model": r.brand_model,
            "vin_number": r.vin_number,
            "odometer_reading": r.odometer_reading,
            "user_name": r.user_name,
            "user_age": r.user_age,
            "user_age_group": r.user_age_group,
            "user_profession": r.user_profession,
            "nps_score": r.nps_score,
            "complaint_groups": r.complaint_groups,
            "full_data": r.full_data,
            "row_index": r.row_index,
            "created_at": r.created_at,
        }