import os
import asyncio
import json
from pathlib import Path
from typing import Optional, AsyncGenerator
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from beanie import PydanticObjectId

from app.models.user import User
from app.models.uploaded_file import UploadedFile
from app.models.region import Region
from app.models.country import Country
from app.models.ib_version import IBVersion
from app.middleware.auth import get_admin_or_super, get_current_user
from app.middleware.scope import ScopedUser, get_scoped_user
from app.config.settings import settings

router = APIRouter(prefix="/upload", tags=["Excel Upload"])


def file_to_dict(f: UploadedFile, region_name="", country_name="", ib_name="",
                 uploader_name="") -> dict:
    return {
        "id": str(f.id),
        "file_name": f.file_name,
        "file_size": f.file_size,
        "region_id": str(f.region_id),
        "region_name": region_name,
        "country_id": str(f.country_id),
        "country_name": country_name,
        "ib_version_id": str(f.ib_version_id),
        "ib_version_name": ib_name,
        "uploaded_by": str(f.uploaded_by),
        "uploader_name": uploader_name,
        "total_records": f.total_records,
        "processed_records": f.processed_records,
        "status": f.status,
        "error_message": f.error_message,
        "upload_started_at": f.upload_started_at,
        "upload_completed_at": f.upload_completed_at,
    }


@router.post("")
async def upload_excel(
    background_tasks: BackgroundTasks,
    region_id: str = Form(...),
    country_id: str = Form(...),
    ib_version_id: str = Form(...),
    assigned_admin_id: Optional[str] = Form(None),
    file: UploadFile = File(...),
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    # Validate scope permission first
    scoped_user.assert_upload_allowed(region_id, country_id, ib_version_id)

    # Validate IDs
    region = await Region.get(PydanticObjectId(region_id))
    country = await Country.get(PydanticObjectId(country_id))
    ib_version = await IBVersion.get(PydanticObjectId(ib_version_id))
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")
    if not ib_version:
        raise HTTPException(status_code=404, detail="IB Version not found")

    # File type check
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .xls files are allowed")

    # Size check
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File size {size_mb:.1f}MB exceeds limit of {settings.MAX_FILE_SIZE_MB}MB",
        )

    # Save file
    upload_dir = Path(settings.UPLOAD_DIR)
    upload_dir.mkdir(exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{timestamp}_{file.filename.replace(' ', '_')}"
    file_path = str(upload_dir / safe_name)

    with open(file_path, "wb") as f_out:
        f_out.write(content)

    # Determine assigned_admin_id
    if scoped_user.user.role == "super_admin":
        admin_to_assign = PydanticObjectId(assigned_admin_id) if assigned_admin_id else None
    else:
        admin_to_assign = scoped_user.user.id

    # Create DB record
    upload_record = UploadedFile(
        region_id=PydanticObjectId(region_id),
        country_id=PydanticObjectId(country_id),
        ib_version_id=PydanticObjectId(ib_version_id),
        uploaded_by=scoped_user.user.id,
        assigned_admin_id=admin_to_assign,
        file_name=file.filename,
        file_path=file_path,
        file_size=len(content),
        status="processing",
    )
    await upload_record.insert()
    file_id = str(upload_record.id)

    # Launch processor in a background task
    from app.jobs.excel_processor_job import process_excel_file_async
    background_tasks.add_task(
        process_excel_file_async,
        file_id,
        file_path,
        region_id,
        country_id,
        ib_version_id,
    )

    return {
        "file_id": file_id,
        "file_name": file.filename,
        "status": "processing",
        "message": "File uploaded. Processing started in background.",
    }


@router.get("")
async def list_uploads(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status: Optional[str] = None,
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    query = {}
    if status:
        query["status"] = status

    # Merge user file scope into query
    query = scoped_user.apply_to_file_query(query)

    skip = (page - 1) * page_size
    total = await UploadedFile.find(query).count()
    files = await UploadedFile.find(query).sort("-created_at").skip(skip).limit(page_size).to_list()

    result = []
    for f in files:
        region = await Region.get(f.region_id)
        country = await Country.get(f.country_id)
        ib = await IBVersion.get(f.ib_version_id)
        from app.models.user import User as UserModel
        uploader = await UserModel.get(f.uploaded_by)
        result.append(file_to_dict(
            f,
            region_name=region.name if region else "",
            country_name=country.name if country else "",
            ib_name=ib.name if ib else "",
            uploader_name=uploader.full_name if uploader else "",
        ))

    return {
        "data": result,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


@router.get("/{file_id}/progress")
async def get_upload_progress(
    file_id: str,
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    """SSE endpoint — real-time upload progress."""
    async def event_generator() -> AsyncGenerator[str, None]:
        max_iterations = 300  # 5 minutes timeout
        iteration = 0
        while iteration < max_iterations:
            upload = await UploadedFile.get(PydanticObjectId(file_id))
            if upload:
                total = upload.total_records or 0
                processed = upload.processed_records or 0
                progress_data = {
                    "status": upload.status,
                    "processed_records": str(processed),
                    "total_records": str(total),
                    "progress": str(
                        round(processed / total * 100, 1) if total else 0
                    ),
                    "message": f"Processing {processed}/{total} records...",
                    "error_message": upload.error_message or "",
                }
                yield f"data: {json.dumps(progress_data)}\n\n"
                if upload.status in ("completed", "failed", "partial"):
                    break
            await asyncio.sleep(2)
            iteration += 1

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{file_id}")
async def delete_upload(
    file_id: str,
    scoped_user: ScopedUser = Depends(get_scoped_user),
):
    upload = await UploadedFile.get(PydanticObjectId(file_id))
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found")

    # Reject if outside user scope
    scoped_user.assert_upload_allowed(upload.region_id, upload.country_id, upload.ib_version_id)

    # Delete associated survey responses
    from app.models.survey_response import SurveyResponse
    await SurveyResponse.find({"file_id": upload.id}).delete()

    # Delete issue analysis
    from app.models.issue_analysis import IssueAnalysis
    await IssueAnalysis.find({"file_id": upload.id}).delete()

    # Delete the file
    try:
        os.remove(upload.file_path)
    except Exception:
        pass

    await upload.delete()
    return {"message": "Upload and all associated data deleted"}
