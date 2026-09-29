"""
Excel processor — async background task.

Runs on FastAPI's BackgroundTasks, sharing the main uvicorn event loop.
CPU-heavy work is offloaded via run_in_threadpool so the event loop stays
free to serve the SSE progress stream.

Progress is tracked in two places:
  1. In-memory PROGRESS dict  → read by SSE for smooth live updates
  2. MongoDB UploadedFile doc → persisted once per chunk + at the end
"""
import json
from datetime import datetime
from loguru import logger
from fastapi.concurrency import run_in_threadpool

from app.config.settings import settings


# ─────────────────────────────────────────────────────────────
# In-memory progress store (per worker process)
# ─────────────────────────────────────────────────────────────
PROGRESS: dict = {}


def set_progress(file_id: str, **kwargs):
    PROGRESS.setdefault(file_id, {})
    PROGRESS[file_id].update(kwargs)


def get_progress(file_id: str) -> dict:
    return PROGRESS.get(file_id, {"status": "processing", "processed": 0, "total": 0})


def clear_progress(file_id: str):
    PROGRESS.pop(file_id, None)


# ─────────────────────────────────────────────────────────────
# Main job
# ─────────────────────────────────────────────────────────────
async def process_excel_file_async(
    file_id: str,
    file_path: str,
    region_id: str,
    country_id: str,
    ib_version_id: str,
):
    from beanie import PydanticObjectId
    from app.models.uploaded_file import UploadedFile
    from app.models.survey_response import SurveyResponse
    from app.models.issue_analysis import IssueAnalysis, AnalysisSummary
    from app.services.excel_processor import (
        validate_excel,
        extract_row_data,
        compute_issue_analysis,
        get_issue_column_range_mapping,
    )

    logger.info(f"[Job] Starting Excel processing for file_id={file_id}")

    # ── Helper: persist state to Mongo + mirror to memory ──────
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

        # Mirror into the in-memory store for SSE
        set_progress(
            file_id,
            status=status,
            processed=processed,
            total=total,
            error=error or "",
        )

    try:
        # ── 1. Validate Excel (sync, cheap) ────────────────────
        is_valid, error_msg, df = validate_excel(file_path)
        if not is_valid:
            await mark("failed", error=error_msg)
            logger.error(f"[Job] Validation failed: {error_msg}")
            return

        col_letters = list(df.columns)
        total_rows = len(df)

        # Initialize progress store so SSE sees "processing 0/total"
        set_progress(
            file_id,
            status="processing",
            processed=0,
            total=total_rows,
            message=f"Loaded {total_rows} rows",
        )
        await mark("processing", 0, total_rows)

        # ── 2. Load issue mapping ONCE for the whole job ───────
        issue_mapping = await get_issue_column_range_mapping()
        logger.info(f"[Job] Loaded issue mapping with {len(issue_mapping)} issues")

        # ── 3. Chunk-process rows ──────────────────────────────
        CHUNK_SIZE = settings.CHUNK_SIZE
        processed = 0
        failed_rows = []
        all_response_dicts = []

        def _build_chunk_docs(chunk_df, chunk_start, col_letters, issue_mapping, file_id_str):
            """Pure-CPU worker — runs in a thread, no DB, no await."""
            docs, dicts, failed = [], [], []
            oid = PydanticObjectId(file_id_str)
            for local_idx, (_, row) in enumerate(chunk_df.iterrows()):
                row_index = chunk_start + local_idx
                try:
                    extracted = extract_row_data(row, col_letters, issue_mapping)
                    doc = SurveyResponse(
                        file_id=oid,
                        row_index=row_index,
                        **extracted["key_fields"],
                        full_data=extracted["full_data"],
                        complaint_data=extracted["complaint_data"],
                        complaint_groups=extracted["complaint_groups"],
                        passive_data=extracted["passive_data"],
                    )
                    docs.append(doc)
                    dicts.append(extracted)
                except Exception as e:
                    failed.append({"row": row_index, "error": str(e)})
            return docs, dicts, failed

        for chunk_start in range(0, total_rows, CHUNK_SIZE):
            chunk_end = min(chunk_start + CHUNK_SIZE, total_rows)
            chunk = df.iloc[chunk_start:chunk_end]

            # Run CPU work off the event loop
            docs_to_insert, chunk_dicts, chunk_failed = await run_in_threadpool(
                _build_chunk_docs,
                chunk,
                chunk_start,
                col_letters,
                issue_mapping,
                file_id,
            )

            if docs_to_insert:
                try:
                    await SurveyResponse.insert_many(docs_to_insert, ordered=False)
                except Exception as e:
                    logger.error(f"Bulk insert failed: {e}")

            all_response_dicts.extend(chunk_dicts)
            failed_rows.extend(chunk_failed)

            processed = chunk_end

            # Mirror live progress into memory (cheap) + persist to Mongo
            set_progress(
                file_id,
                status="processing",
                processed=processed,
                total=total_rows,
                message=f"Processed {processed}/{total_rows}",
            )
            await mark("processing", processed, total_rows)

        # ── 4. Compute issue analysis (CPU-heavy) ──────────────
        try:
            issue_summaries = await run_in_threadpool(
                compute_issue_analysis,
                all_response_dicts,
                col_letters,
                issue_mapping,
            )
            sorted_issues = sorted(
                issue_summaries, key=lambda x: x["total_complaints"], reverse=True
            )

            analysis = IssueAnalysis(
                file_id=PydanticObjectId(file_id),
                region_id=PydanticObjectId(region_id),
                country_id=PydanticObjectId(country_id),
                ib_version_id=PydanticObjectId(ib_version_id),
                issues=sorted_issues,
                summary=AnalysisSummary(
                    total_issues_reported=sum(
                        i["total_complaints"] for i in issue_summaries
                    ),
                    unique_issues=sum(
                        1 for i in issue_summaries if i["total_complaints"] > 0
                    ),
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

        # ── 5. Finalise ────────────────────────────────────────
        final_status = "partial" if failed_rows else "completed"
        error_msg_final = json.dumps(failed_rows[:50]) if failed_rows else None
        await mark(final_status, processed, total_rows, error_msg_final)
        logger.success(
            f"[Job] File {file_id} processed: {processed} rows, status={final_status}"
        )

    except Exception as e:
        logger.error(f"[Job] Fatal error processing file {file_id}: {e}")
        await mark("failed", error=str(e))