"""
Dashboard controller - Business logic for dashboard statistics.
"""
from typing import Dict, Any, Optional
from beanie import PydanticObjectId
from loguru import logger

from app.models.survey_response import SurveyResponse
from app.models.uploaded_file import UploadedFile
from app.models.issue_analysis import IssueAnalysis


class DashboardController:
    """Controller for dashboard operations."""
    
    @staticmethod
    async def get_dashboard_stats(
        file_id: Optional[str] = None,
        region_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get combined dashboard summary stats.
        """
        file_ids = []
        if file_id:
            file_ids = [PydanticObjectId(file_id)]
        elif region_id:
            files = await UploadedFile.find(
                {"region_id": PydanticObjectId(region_id), "status": "completed"}
            ).to_list()
            file_ids = [f.id for f in files]

        query = {}
        if file_ids:
            query["file_id"] = {"$in": file_ids}

        total_records = await SurveyResponse.find(query).count()
        brands = await SurveyResponse.distinct("brand_model", filter=query if query else None)
        locations = await SurveyResponse.distinct("survey_location", filter=query if query else None)
        total_uploads = await UploadedFile.find({"status": "completed"}).count()

        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": None,
                "avg_nps": {"$avg": "$nps_score"},
                "total_complaints": {"$sum": {"$size": "$complaint_groups"}},
            }},
        ]
        agg = await SurveyResponse.aggregate(pipeline).to_list()
        stats = agg[0] if agg else {}

        return {
            "total_records": total_records,
            "total_uploads": total_uploads,
            "total_brands": len([b for b in brands if b and b != "Blank"]),
            "unique_locations": len([l for l in locations if l and l != "Blank"]),
            "average_nps": round(stats.get("avg_nps") or 0, 1),
            "total_complaints": stats.get("total_complaints", 0),
        }

    @staticmethod
    async def get_brand_distribution() -> Dict[str, Any]:
        """
        Get brand distribution for charts.
        """
        pipeline = [
            {"$group": {"_id": "$brand_model", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 20},
        ]
        results = await SurveyResponse.aggregate(pipeline).to_list()
        return {"data": [{"label": r["_id"] or "Unknown", "count": r["count"]} for r in results]}

    @staticmethod
    async def get_nps_distribution() -> Dict[str, Any]:
        """
        Get NPS score distribution for charts.
        """
        pipeline = [
            {"$match": {"nps_score": {"$ne": None}}},
            {"$group": {"_id": "$nps_score", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        results = await SurveyResponse.aggregate(pipeline).to_list()
        return {"data": [{"score": r["_id"], "count": r["count"]} for r in results]}

    @staticmethod
    async def get_location_issues_heatmap() -> Dict[str, Any]:
        """
        Get location × issue count heatmap data.
        """
        pipeline = [
            {"$match": {"complaint_groups": {"$ne": []}}},
            {"$unwind": "$complaint_groups"},
            {
                "$group": {
                    "_id": {
                        "location": "$survey_location",
                        "issue": "$complaint_groups",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": 500},
        ]
        results = await SurveyResponse.aggregate(pipeline).to_list()
        return {
            "data": [
                {
                    "location": r["_id"]["location"],
                    "issue": r["_id"]["issue"],
                    "count": r["count"],
                }
                for r in results
            ]
        }