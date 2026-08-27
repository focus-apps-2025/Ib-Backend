"""
Analysis service - Advanced data analysis operations.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from beanie import PydanticObjectId
from loguru import logger

from app.models.survey_response import SurveyResponse
from app.models.issue_analysis import IssueAnalysis
from app.models.uploaded_file import UploadedFile


class AnalysisService:
    """Service for advanced data analysis."""
    
    @staticmethod
    async def generate_monthly_report(file_id: str) -> Dict[str, Any]:
        """
        Generate a monthly report for a file.
        """
        file_obj = await UploadedFile.get(PydanticObjectId(file_id))
        if not file_obj:
            return {"error": "File not found"}
            
        # Get all responses for this file
        responses = await SurveyResponse.find(
            {"file_id": PydanticObjectId(file_id)}
        ).to_list()
        
        if not responses:
            return {"error": "No responses found"}
            
        # Group by month
        monthly_data = {}
        for response in responses:
            if response.survey_date:
                month_key = response.survey_date.strftime("%Y-%m")
                if month_key not in monthly_data:
                    monthly_data[month_key] = {
                        "total_responses": 0,
                        "complaints": [],
                        "nps_scores": [],
                        "brands": set(),
                        "locations": set(),
                    }
                monthly_data[month_key]["total_responses"] += 1
                monthly_data[month_key]["complaints"].extend(response.complaint_groups)
                if response.nps_score:
                    monthly_data[month_key]["nps_scores"].append(response.nps_score)
                if response.brand_model:
                    monthly_data[month_key]["brands"].add(response.brand_model)
                if response.survey_location:
                    monthly_data[month_key]["locations"].add(response.survey_location)
        
        # Calculate statistics per month
        report = []
        for month, data in sorted(monthly_data.items()):
            total_complaints = len(data["complaints"])
            avg_nps = sum(data["nps_scores"]) / len(data["nps_scores"]) if data["nps_scores"] else 0
            
            # Get top complaints
            from collections import Counter
            complaint_counts = Counter(data["complaints"])
            top_complaints = complaint_counts.most_common(5)
            
            report.append({
                "month": month,
                "total_responses": data["total_responses"],
                "total_complaints": total_complaints,
                "avg_nps": round(avg_nps, 1),
                "unique_brands": len(data["brands"]),
                "unique_locations": len(data["locations"]),
                "top_complaints": [
                    {"issue": issue, "count": count}
                    for issue, count in top_complaints
                ],
            })
            
        return {
            "file_id": file_id,
            "file_name": file_obj.file_name,
            "total_months": len(report),
            "report": report,
        }
    
    @staticmethod
    async def get_brand_comparison(region_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Compare brands across metrics.
        """
        query = {}
        if region_id:
            files = await UploadedFile.find(
                {"region_id": PydanticObjectId(region_id)}
            ).to_list()
            file_ids = [f.id for f in files]
            if file_ids:
                query["file_id"] = {"$in": file_ids}
        
        pipeline = [
            {"$match": query},
            {"$match": {"brand_model": {"$ne": "Blank"}}},
            {
                "$group": {
                    "_id": "$brand_model",
                    "total_responses": {"$sum": 1},
                    "avg_nps": {"$avg": "$nps_score"},
                    "total_complaints": {"$sum": {"$size": "$complaint_groups"}},
                    "unique_locations": {"$addToSet": "$survey_location"},
                    "complaint_groups": {"$push": "$complaint_groups"},
                }
            },
            {"$sort": {"total_responses": -1}},
            {"$limit": 20},
        ]
        
        results = await SurveyResponse.aggregate(pipeline).to_list()
        
        # Process results
        brands = []
        for r in results:
            # Count unique complaints across all responses for this brand
            all_complaints = []
            for complaints in r["complaint_groups"]:
                all_complaints.extend(complaints)
            
            from collections import Counter
            complaint_counts = Counter(all_complaints)
            top_complaints = complaint_counts.most_common(5)
            
            brands.append({
                "brand": r["_id"],
                "total_responses": r["total_responses"],
                "avg_nps": round(r["avg_nps"] or 0, 1),
                "total_complaints": r["total_complaints"],
                "complaints_per_response": round(r["total_complaints"] / r["total_responses"], 2),
                "unique_locations": len(r["unique_locations"]),
                "top_complaints": [
                    {"issue": issue, "count": count}
                    for issue, count in top_complaints
                ],
            })
            
        return {"brands": brands}
    
    @staticmethod
    async def get_trend_analysis(file_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Get trend analysis for issues over time.
        """
        from app.models.survey_response import SurveyResponse
        
        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)
            
        # Get all responses with dates
        responses = await SurveyResponse.find(
            {**query, "survey_date": {"$ne": None}}
        ).to_list()
        
        if not responses:
            return {"error": "No data found"}
            
        # Group by issue and time
        trend_data = {}
        for response in responses:
            if response.survey_date:
                month_key = response.survey_date.strftime("%Y-%m")
                for issue in response.complaint_groups:
                    if issue not in trend_data:
                        trend_data[issue] = {}
                    if month_key not in trend_data[issue]:
                        trend_data[issue][month_key] = 0
                    trend_data[issue][month_key] += 1
        
        # Convert to chart-friendly format
        issues = sorted(trend_data.keys())
        months = sorted(set().union(*[d.keys() for d in trend_data.values()]))
        
        series = []
        for issue in issues:
            data = []
            for month in months:
                data.append(trend_data[issue].get(month, 0))
            series.append({
                "name": issue,
                "data": data,
            })
            
        return {
            "months": months,
            "series": series,
        }