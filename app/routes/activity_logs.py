from fastapi import APIRouter, Depends, Query
from typing import Optional
from beanie import PydanticObjectId

from app.models.user import User
from app.models.activity_log import ActivityLog
from app.middleware.auth import get_super_admin

router = APIRouter(prefix="/activity-logs", tags=["Activity Logs"])


@router.get("")
async def list_activity_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: Optional[str] = None,
    action: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    _: User = Depends(get_super_admin),
):
    from app.utils.datetime_utils import parse_date_filter
    query = {}
    if user_id:
        query["user_id"] = PydanticObjectId(user_id)
    if action:
        query["action"] = action
    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = parse_date_filter(date_from)
        if date_to:
            date_filter["$lte"] = parse_date_filter(date_to)
        query["created_at"] = date_filter

    skip = (page - 1) * page_size
    total = await ActivityLog.find(query).count()
    logs = await ActivityLog.find(query).sort("-created_at").skip(skip).limit(page_size).to_list()

    return {
        "data": [
            {
                "id": str(log.id),
                "user_id": str(log.user_id) if log.user_id else None,
                "username": log.username,
                "action": log.action,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": log.created_at,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }
