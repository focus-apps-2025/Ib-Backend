import uuid
from datetime import datetime
from typing import Optional, Dict, List
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, status
from pydantic import BaseModel
from loguru import logger

from app.models.user import User
from app.models.market_feedback import MarketFeedback, PhotoItemSchema
from app.middleware.auth import get_admin_or_super, get_current_user
from app.services.s3_service import s3_service

router = APIRouter(prefix="/market-feedback", tags=["Market Feedback"])


class RemarkRequest(BaseModel):
    remark_key: str
    remark: str
    issue_name: Optional[str] = None
    sub_issue_title: Optional[str] = None


@router.get("")
async def get_all_market_feedback(_: User = Depends(get_current_user)):
    """Fetch all saved remarks and photo entries from MongoDB."""
    try:
        items = await MarketFeedback.find_all().to_list()
        remarks: Dict[str, str] = {}
        photos: Dict[str, List[dict]] = {}

        for item in items:
            if item.remark:
                remarks[item.remark_key] = item.remark
            if item.photos:
                photos[item.remark_key] = [p.dict() for p in item.photos]

        return {
            "success": True,
            "data": {
                "remarks": remarks,
                "photos": photos,
            }
        }
    except Exception as e:
        logger.error(f"Error fetching market feedback: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/remark")
async def save_remark(payload: RemarkRequest, _: User = Depends(get_admin_or_super)):
    """Save or update field remark for an issue sub-item."""
    try:
        doc = await MarketFeedback.find_one(MarketFeedback.remark_key == payload.remark_key)
        now = datetime.utcnow()

        if doc:
            doc.remark = payload.remark
            doc.updated_at = now
            if payload.issue_name:
                doc.issue_name = payload.issue_name
            if payload.sub_issue_title:
                doc.sub_issue_title = payload.sub_issue_title
            await doc.save()
        else:
            doc = MarketFeedback(
                remark_key=payload.remark_key,
                issue_name=payload.issue_name,
                sub_issue_title=payload.sub_issue_title,
                remark=payload.remark,
                photos=[],
                created_at=now,
                updated_at=now,
            )
            await doc.insert()

        return {
            "success": True,
            "data": {
                "remark_key": doc.remark_key,
                "remark": doc.remark,
            }
        }
    except Exception as e:
        logger.error(f"Error saving remark for {payload.remark_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/photo")
async def upload_photo(
    remark_key: str = Form(...),
    issue_name: Optional[str] = Form(None),
    sub_issue_title: Optional[str] = Form(None),
    file: UploadFile = File(...),
    _: User = Depends(get_admin_or_super),
):
    """Upload defect photo to AWS S3 and save metadata in MongoDB."""
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files can be uploaded.")

    try:
        contents = await file.read()
        s3_res = await s3_service.upload_file(
            file_bytes=contents,
            filename=file.filename,
            content_type=file.content_type,
            folder="market_feedback",
        )

        photo_id = f"photo_{int(datetime.utcnow().timestamp())}_{uuid.uuid4().hex[:6]}"
        date_str = datetime.utcnow().strftime("%b %d, %Y")

        new_photo = PhotoItemSchema(
            id=photo_id,
            url=s3_res["url"],
            name=file.filename,
            s3_key=s3_res["s3_key"],
            date=date_str,
            uploaded_at=datetime.utcnow(),
        )

        doc = await MarketFeedback.find_one(MarketFeedback.remark_key == remark_key)
        now = datetime.utcnow()

        if doc:
            doc.photos.append(new_photo)
            doc.updated_at = now
            if issue_name:
                doc.issue_name = issue_name
            if sub_issue_title:
                doc.sub_issue_title = sub_issue_title
            await doc.save()
        else:
            doc = MarketFeedback(
                remark_key=remark_key,
                issue_name=issue_name,
                sub_issue_title=sub_issue_title,
                remark="",
                photos=[new_photo],
                created_at=now,
                updated_at=now,
            )
            await doc.insert()

        return {
            "success": True,
            "data": {
                "remark_key": remark_key,
                "photo": new_photo.dict(),
                "photos": [p.dict() for p in doc.photos],
            }
        }
    except Exception as e:
        logger.error(f"Error uploading photo for {remark_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/photo/{remark_key}/{photo_id}")
async def delete_photo(
    remark_key: str,
    photo_id: str,
    _: User = Depends(get_admin_or_super),
):
    """Delete photo metadata from MongoDB and delete corresponding file from AWS S3."""
    try:
        doc = await MarketFeedback.find_one(MarketFeedback.remark_key == remark_key)
        if not doc:
            raise HTTPException(status_code=404, detail="Market feedback entry not found")

        target_photo = next((p for p in doc.photos if p.id == photo_id), None)
        if not target_photo:
            raise HTTPException(status_code=404, detail="Photo not found")

        # Remove from S3
        if target_photo.s3_key:
            await s3_service.delete_file(target_photo.s3_key)

        # Remove from MongoDB document
        doc.photos = [p for p in doc.photos if p.id != photo_id]
        doc.updated_at = datetime.utcnow()
        await doc.save()

        return {
            "success": True,
            "data": {
                "remark_key": remark_key,
                "photos": [p.dict() for p in doc.photos],
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting photo {photo_id} from {remark_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
