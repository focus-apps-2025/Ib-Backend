"""
Excel processor — async background task (no Celery, no Redis, no threading).
Runs on FastAPI's BackgroundTasks, sharing the main uvicorn event loop.
Progress tracked entirely in MongoDB via UploadedFile.
"""
import json
import asyncio
from datetime import datetime
from loguru import logger

from app.config.settings import settings


async def process_excel_file_async(file_id: str, file_path: str,
                                   region_id: str, country_id: str, ib_version_id: str):
    """
    Async background task: parse Excel, chunk-insert into MongoDB,
    compute issue analysis. This is the async version.
    """
    from beanie import PydanticObjectId
    from app.models.uploaded_file import UploadedFile
    from app.models.survey_response import SurveyResponse
    from app.models.issue_analysis import IssueAnalysis, AnalysisSummary
    from app.services.excel_processor import (
        validate_excel, extract_row_data, compute_issue_analysis,
    )

    logger.info(f"[Job] Starting Excel processing for file_id={file_id}")

    async def mark(status: str, processed: int = 0, total: int = 0, error: str = None):
        try:
            record = await UploadedFile.get(PydanticObjectId(file_id))
            if record:
                record.status = status
                record.processed_records = processed
                if total:
                    record.total_records = total
                if error is not None:
                    record.error_message = error
                if status in ("completed", "failed", "partial"):
                    record.upload_completed_at = datetime.utcnow()
                await record.save()
        except Exception as e:
            logger.warning(f"[Job] DB progress mark failed: {e}")

    try:
        # ── Validate Excel ────────────────────────────────────────────
        is_valid, error_msg, df = validate_excel(file_path)
        if not is_valid:
            await mark("failed", error=error_msg)
            logger.error(f"[Job] Validation failed: {error_msg}")
            return

        col_letters = list(df.columns)
        total_rows = len(df)
        await mark("processing", 0, total_rows)

        # ── Chunk-process rows ────────────────────────────────────────
        CHUNK_SIZE = settings.CHUNK_SIZE
        processed = 0
        failed_rows = []
        all_response_dicts = []

        for chunk_start in range(0, total_rows, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total_rows)
            chunk = df.iloc[chunk_start:chunk_end]

            docs_to_insert = []
            for local_idx, (_, row) in enumerate(chunk.iterrows()):
                row_index = chunk_start + local_idx
                try:
                    extracted =await  extract_row_data(row, col_letters)
                    doc = SurveyResponse(
                        file_id=PydanticObjectId(file_id),
                        row_index=row_index,
                        **extracted["key_fields"],
                        full_data=extracted["full_data"],
                        complaint_data=extracted["complaint_data"],
                        complaint_groups=extracted["complaint_groups"],
                        passive_data=extracted["passive_data"],
                    )
                    docs_to_insert.append(doc)
                    all_response_dicts.append(extracted)
                except Exception as e:
                    failed_rows.append({"row": row_index, "error": str(e)})
                    logger.warning(f"Row {row_index} failed: {e}")

            if docs_to_insert:
                try:
                    await SurveyResponse.insert_many(docs_to_insert, ordered=False)
                except Exception as e:
                    logger.error(f"Bulk insert failed: {e}")

            processed = chunk_end
            await mark("processing", processed, total_rows)

        # ── Compute issue analysis ────────────────────────────────────
        try:
            issue_summaries =await  compute_issue_analysis(all_response_dicts, col_letters)
            sorted_issues = sorted(issue_summaries, key=lambda x: x["total_complaints"], reverse=True)

            analysis = IssueAnalysis(
                file_id=PydanticObjectId(file_id),
                region_id=PydanticObjectId(region_id),
                country_id=PydanticObjectId(country_id),
                ib_version_id=PydanticObjectId(ib_version_id),
                issues=sorted_issues,
                summary=AnalysisSummary(
                    total_issues_reported=sum(i["total_complaints"] for i in issue_summaries),
                    unique_issues=sum(1 for i in issue_summaries if i["total_complaints"] > 0),
                    most_common_issue=sorted_issues[0]["issue_name"] if sorted_issues else None,
                    least_common_issue=sorted_issues[-1]["issue_name"] if sorted_issues else None,
                    issues_per_record=round(
                        sum(i["total_complaints"] for i in issue_summaries) / total_rows, 2
                    ) if total_rows else 0,
                ),
                generated_at=datetime.utcnow(),
            )
            await analysis.insert()
            logger.success(f"Issue analysis saved for file {file_id}")
        except Exception as e:
            logger.error(f"Issue analysis failed: {e}")

        # ── Finalise ──────────────────────────────────────────────────
        final_status = "partial" if failed_rows else "completed"
        error_msg_final = json.dumps(failed_rows[:50]) if failed_rows else None
        await mark(final_status, processed, total_rows, error_msg_final)
        logger.success(f"[Job] File {file_id} processed: {processed} rows, status={final_status}")

    except Exception as e:
        logger.error(f"[Job] Fatal error processing file {file_id}: {e}")
        await mark("failed", error=str(e))


def process_excel_file(file_id: str, file_path: str,
                       region_id: str, country_id: str, ib_version_id: str):
    """
    Synchronous wrapper for async background task.
    FastAPI BackgroundTasks requires synchronous functions.
    """
    # Create a new event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            process_excel_file_async(file_id, file_path, region_id, country_id, ib_version_id)
        )
    finally:
        loop.close()