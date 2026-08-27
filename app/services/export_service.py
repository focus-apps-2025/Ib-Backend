"""
Export service - Export data to various formats.
"""
import io
import csv
import json
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi.responses import StreamingResponse
from beanie import PydanticObjectId
from loguru import logger

from app.models.survey_response import SurveyResponse
from app.models.issue_analysis import IssueAnalysis
from app.models.uploaded_file import UploadedFile


class ExportService:
    """Service for exporting data."""
    
    @staticmethod
    async def export_to_csv(
        file_id: Optional[str] = None,
        brand_model: Optional[str] = None,
        max_records: int = 100000,
    ) -> StreamingResponse:
        """
        Export survey responses to CSV.
        """
        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)
        if brand_model:
            query["brand_model"] = {"$regex": brand_model, "$options": "i"}

        responses = await SurveyResponse.find(query).limit(max_records).to_list()

        async def generate():
            output = io.StringIO()
            writer = csv.writer(output)

            # Collect all column keys
            all_keys = set()
            for r in responses:
                all_keys.update(r.full_data.keys())
            sorted_keys = sorted(all_keys)

            writer.writerow([
                "id", "survey_date", "brand_model", "survey_location", 
                "nps_score", "complaint_groups"
            ] + sorted_keys)
            output.seek(0)
            yield output.read()
            output.truncate(0)
            output.seek(0)

            for r in responses:
                row = [
                    str(r.id),
                    r.survey_date.isoformat() if r.survey_date else "",
                    r.brand_model or "",
                    r.survey_location or "",
                    r.nps_score or "",
                    "|".join(r.complaint_groups),
                ] + [r.full_data.get(k, "") for k in sorted_keys]
                writer.writerow(row)
                output.seek(0)
                yield output.read()
                output.truncate(0)
                output.seek(0)

        return StreamingResponse(
            generate(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=survey_responses.csv"
            },
        )

    @staticmethod
    async def export_to_json(
        file_id: Optional[str] = None,
        include_analysis: bool = True,
    ) -> StreamingResponse:
        """
        Export data to JSON format.
        """
        query = {}
        if file_id:
            query["file_id"] = PydanticObjectId(file_id)

        responses = await SurveyResponse.find(query).to_list()
        
        data = {
            "exported_at": datetime.utcnow().isoformat(),
            "total_records": len(responses),
            "responses": [],
        }
        
        for r in responses:
            data["responses"].append({
                "id": str(r.id),
                "file_id": str(r.file_id),
                "survey_date": r.survey_date.isoformat() if r.survey_date else None,
                "survey_location": r.survey_location,
                "brand_model": r.brand_model,
                "vin_number": r.vin_number,
                "odometer_reading": r.odometer_reading,
                "user_name": r.user_name,
                "user_age": r.user_age,
                "user_profession": r.user_profession,
                "nps_score": r.nps_score,
                "complaint_groups": r.complaint_groups,
                "full_data": r.full_data,
                "complaint_data": r.complaint_data,
            })
            
        if include_analysis and file_id:
            analysis = await IssueAnalysis.find_one({"file_id": PydanticObjectId(file_id)})
            if analysis:
                data["analysis"] = {
                    "id": str(analysis.id),
                    "issues": [
                        {
                            "issue_name": issue.issue_name,
                            "total_complaints": issue.total_complaints,
                            "percentage": issue.percentage,
                            "follow_ups": [
                                {
                                    "question_text": fu.question_text,
                                    "column_letter": fu.column_letter,
                                    "total_responses": fu.total_responses,
                                    "answers": [
                                        {
                                            "value": a.value,
                                            "count": a.count,
                                            "percentage": a.percentage,
                                        }
                                        for a in fu.answers
                                    ],
                                }
                                for fu in issue.follow_ups
                            ],
                        }
                        for issue in analysis.issues
                    ],
                    "summary": {
                        "total_issues_reported": analysis.summary.total_issues_reported,
                        "unique_issues": analysis.summary.unique_issues,
                        "most_common_issue": analysis.summary.most_common_issue,
                        "least_common_issue": analysis.summary.least_common_issue,
                        "issues_per_record": analysis.summary.issues_per_record,
                    },
                    "generated_at": analysis.generated_at.isoformat(),
                }

        async def generate():
            yield json.dumps(data, default=str, indent=2)

        return StreamingResponse(
            generate(),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=survey_data.json"
            },
        )

    @staticmethod
    async def export_summary_report(file_id: str) -> StreamingResponse:
        """
        Export a summary report as JSON.
        """
        from app.services.analysis_service import AnalysisService
        
        # Get monthly report
        report = await AnalysisService.generate_monthly_report(file_id)
        
        # Get issue analysis
        analysis = await IssueAnalysis.find_one({"file_id": PydanticObjectId(file_id)})
        
        # Get file info
        file_obj = await UploadedFile.get(PydanticObjectId(file_id))
        
        summary = {
            "file_info": {
                "id": str(file_obj.id) if file_obj else None,
                "file_name": file_obj.file_name if file_obj else None,
                "uploaded_at": file_obj.upload_started_at.isoformat() if file_obj else None,
                "total_records": file_obj.total_records if file_obj else 0,
                "processed_records": file_obj.processed_records if file_obj else 0,
                "status": file_obj.status if file_obj else "unknown",
            },
            "monthly_report": report,
            "issue_analysis": {
                "total_issues": analysis.summary.total_issues_reported if analysis else 0,
                "unique_issues": analysis.summary.unique_issues if analysis else 0,
                "most_common": analysis.summary.most_common_issue if analysis else None,
                "least_common": analysis.summary.least_common_issue if analysis else None,
                "issues_per_record": analysis.summary.issues_per_record if analysis else 0,
            } if analysis else None,
            "generated_at": datetime.utcnow().isoformat(),
        }

        async def generate():
            yield json.dumps(summary, default=str, indent=2)

        return StreamingResponse(
            generate(),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=summary_report.json"
            },
        )