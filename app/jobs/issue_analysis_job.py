"""
Celery background job for issue analysis computation.
"""
import asyncio
from datetime import datetime
from loguru import logger
from app.config.celery import celery_app


@celery_app.task(bind=True, name="app.jobs.issue_analysis_job.compute_issue_analysis")
def compute_issue_analysis(self, file_id: str, region_id: str = None,
                           country_id: str = None, ib_version_id: str = None):
    """
    Background task to compute issue analysis for a file.
    """
    import motor.motor_asyncio
    from beanie import init_beanie, PydanticObjectId
    from app.config.settings import settings
    from app.models.survey_response import SurveyResponse
    from app.models.issue_analysis import IssueAnalysis, AnalysisSummary
    from app.services.excel_processor import compute_issue_analysis as compute_analysis

    async def _run():
        # Setup async Mongo connection
        client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URL)
        db = client[settings.MONGODB_DB_NAME]

        from app.models.user import User
        from app.models.region import Region
        from app.models.country import Country
        from app.models.ib_version import IBVersion
        from app.models.uploaded_file import UploadedFile
        from app.models.survey_response import SurveyResponse
        from app.models.issue_mapping import IssueMapping
        from app.models.issue_analysis import IssueAnalysis
        from app.models.activity_log import ActivityLog
        from app.models.user_preference import UserPreference
        from app.models.system_setting import SystemSetting

        await init_beanie(database=db, document_models=[
            User, Region, Country, IBVersion, UploadedFile,
            SurveyResponse, IssueMapping, IssueAnalysis,
            ActivityLog, UserPreference, SystemSetting,
        ])

        # Fetch all responses for this file
        responses = await SurveyResponse.find(
            {"file_id": PydanticObjectId(file_id)}
        ).to_list()

        if not responses:
            logger.warning(f"No responses found for file {file_id}")
            return

        # Convert to dict format for analysis
        response_dicts = []
        for r in responses:
            response_dicts.append({
                "complaint_groups": r.complaint_groups,
                "full_data": r.full_data,
            })

        # Compute analysis
        logger.info(f"Computing issue analysis for {len(responses)} responses")
        issue_summaries = compute_analysis(response_dicts, list(response_dicts[0]["full_data"].keys()))

        # Save analysis
        sorted_issues = sorted(issue_summaries, key=lambda x: x["total_complaints"], reverse=True)

        # Get file metadata
        file = await UploadedFile.get(PydanticObjectId(file_id))
        if not file:
            logger.error(f"File {file_id} not found")
            return

        analysis = IssueAnalysis(
            file_id=PydanticObjectId(file_id),
            region_id=file.region_id if not region_id else PydanticObjectId(region_id),
            country_id=file.country_id if not country_id else PydanticObjectId(country_id),
            ib_version_id=file.ib_version_id if not ib_version_id else PydanticObjectId(ib_version_id),
            issues=sorted_issues,
            summary=AnalysisSummary(
                total_issues_reported=sum(i["total_complaints"] for i in issue_summaries),
                unique_issues=sum(1 for i in issue_summaries if i["total_complaints"] > 0),
                most_common_issue=sorted_issues[0]["issue_name"] if sorted_issues else None,
                least_common_issue=sorted_issues[-1]["issue_name"] if sorted_issues else None,
                issues_per_record=round(
                    sum(i["total_complaints"] for i in issue_summaries) / len(responses), 2
                ) if len(responses) else 0,
            ),
            generated_at=datetime.utcnow(),
        )
        await analysis.insert()

        logger.success(f"Issue analysis completed for file {file_id}")
        client.close()

    asyncio.run(_run())