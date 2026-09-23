"""
Upload controller - Business logic for file upload processing.
"""
import os
import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, AsyncGenerator
from datetime import datetime
from fastapi import HTTPException, UploadFile
from beanie import PydanticObjectId
from loguru import logger


from app.models.user import User
from app.models.uploaded_file import UploadedFile
from app.models.region import Region
from app.models.country import Country
from app.models.ib_version import IBVersion
from app.models.survey_response import SurveyResponse
from app.models.issue_analysis import IssueAnalysis
from app.config.settings import settings
from app.config.redis import get_redis


class UploadController:
    """Controller for file upload operations."""
    
    @staticmethod
    async def upload_excel(
        region_id: str,
        country_id: str,
        ib_version_id: str,
        file: UploadFile,
        current_user: User,
    ) -> Dict[str, Any]:
        """
        Process Excel file upload and start background processing.
        """
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

        # Create DB record
        upload_record = UploadedFile(
            region_id=PydanticObjectId(region_id),
            country_id=PydanticObjectId(country_id),
            ib_version_id=PydanticObjectId(ib_version_id),
            uploaded_by=current_user.id,
            file_name=file.filename,
            file_path=file_path,
            file_size=len(content),
            status="processing",
        )
        await upload_record.insert()
        file_id = str(upload_record.id)

        # Dispatch Celery job
        try:
            from app.jobs.excel_processor_job import process_excel_file
            task = process_excel_file.apply_async(
                args=[file_id, file_path, region_id, country_id, ib_version_id],
                queue="excel",
            )
            await upload_record.update({"$set": {"celery_task_id": task.id}})
            logger.info(f"Celery task dispatched for file {file_id}: {task.id}")
        except Exception as e:
            logger.error(f"Celery dispatch failed, processing synchronously: {e}")
            # Fallback to synchronous processing
            from app.jobs.excel_processor_job import process_excel_file
            process_excel_file(file_id, file_path, region_id, country_id, ib_version_id)

        return {
            "file_id": file_id,
            "file_name": file.filename,
            "status": "processing",
            "message": "File uploaded. Processing started in background.",
        }

    @staticmethod
    async def list_uploads(
        page: int,
        page_size: int,
        status: Optional[str],
        current_user: User,
    ) -> Dict[str, Any]:
        """
        List uploads with pagination and filtering.
        """
        query = {}
        if current_user.role == "admin":
            query["uploaded_by"] = current_user.id
        if status:
            query["status"] = status

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
            assigned_admin = await UserModel.get(f.assigned_admin_id) if f.assigned_admin_id else None

            result.append({
                "id": str(f.id),
                "file_name": f.file_name,
                "file_size": f.file_size,
                "region_id": str(f.region_id),
                "region_name": region.name if region else "",
                "country_id": str(f.country_id),
                "country_name": country.name if country else "",
                "ib_version_id": str(f.ib_version_id),
                "ib_version_name": ib.name if ib else "",
                "uploaded_by": str(f.uploaded_by),
                "uploader_name": uploader.full_name if uploader else "",
                "assigned_admin_id": str(f.assigned_admin_id) if f.assigned_admin_id else None,
                "assigned_admin_name": assigned_admin.full_name if assigned_admin else "",
                "assigned_admin_username": assigned_admin.username if assigned_admin else "",
                "assigned_admin_email": assigned_admin.email if assigned_admin else "",
                "total_records": f.total_records,
                "processed_records": f.processed_records,
                "status": f.status,
                "error_message": f.error_message,
                "celery_task_id": f.celery_task_id,
                "upload_started_at": f.upload_started_at,
                "upload_completed_at": f.upload_completed_at,
                "created_at": f.created_at,
            })

        return {
            "data": result,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @staticmethod
    async def get_upload_progress(file_id: str) -> AsyncGenerator[str, None]:
        """
        Get real-time upload progress via SSE.
        """
        r = get_redis()
        max_iterations = 300  # 5 minutes timeout
        iteration = 0
        
        while iteration < max_iterations:
            if r:
                progress_data = await r.hgetall(f"upload_progress:{file_id}")
            else:
                # Fallback: read from DB
                upload = await UploadedFile.get(PydanticObjectId(file_id))
                if upload:
                    progress_data = {
                        "status": upload.status,
                        "processed_records": str(upload.processed_records),
                        "total_records": str(upload.total_records),
                        "progress": str(
                            round(upload.processed_records / upload.total_records * 100, 1)
                            if upload.total_records else 0
                        ),
                    }
                else:
                    progress_data = {}

            if progress_data:
                yield f"data: {json.dumps(progress_data)}\n\n"
                if progress_data.get("status") in ("completed", "failed", "partial"):
                    break
            await asyncio.sleep(1)
            iteration += 1

    @staticmethod
    async def delete_upload(file_id: str, current_user: User) -> Dict[str, Any]:
        """
        Delete upload and all associated data.
        """
        upload = await UploadedFile.get(PydanticObjectId(file_id))
        if not upload:
            raise HTTPException(status_code=404, detail="Upload not found")

        # Check permissions
        if current_user.role == "admin" and str(upload.uploaded_by) != str(current_user.id):
            raise HTTPException(status_code=403, detail="You can only delete your own uploads")

        # Delete associated survey responses
        await SurveyResponse.find({"file_id": upload.id}).delete()

        # Delete issue analysis
        await IssueAnalysis.find({"file_id": upload.id}).delete()

        # Delete the file
        try:
            os.remove(upload.file_path)
        except Exception as e:
            logger.warning(f"Failed to delete file {upload.file_path}: {e}")

        await upload.delete()
        logger.info(f"Upload deleted: {file_id}")
        return {"message": "Upload and all associated data deleted"}