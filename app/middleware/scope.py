from dataclasses import dataclass
from typing import Optional, List, Any
from beanie import PydanticObjectId
from fastapi import Depends, HTTPException, status

from app.models.user import User
from app.models.user_scope import UserScope
from app.middleware.auth import get_admin_or_super
from app.services.scope_service import (
    get_user_scope, resolve_scope_file_ids,
    apply_scope_to_survey_query, apply_scope_to_file_query,
    is_value_in_scope
)


@dataclass
class ScopedUser:
    user: User
    scope: Optional[UserScope]
    allowed_file_ids: Optional[List[PydanticObjectId]]

    def apply_to_query(self, query: dict = None) -> dict:
        """Merge scope constraints into a survey response query dict."""
        return apply_scope_to_survey_query(query or {}, self.scope, self.allowed_file_ids)

    def apply_to_file_query(self, query: dict = None) -> dict:
        """Merge scope constraints into an UploadedFile query dict."""
        user_id = self.user.id if self.user.role != "super_admin" else None
        return apply_scope_to_file_query(query or {}, self.scope, user_id)

    def assert_upload_allowed(self, region_id: Any, country_id: Any, ib_version_id: Any):
        """Assert target region/country/IB version are within user's scope or raise 403."""
        if self.user.role == "super_admin":
            return
        if not is_value_in_scope(self.scope, "region", region_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload forbidden: region is outside user scope",
            )
        if not is_value_in_scope(self.scope, "country", country_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload forbidden: country is outside user scope",
            )
        if not is_value_in_scope(self.scope, "ib_version", ib_version_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload forbidden: IB version is outside user scope",
            )


async def get_scoped_user(current_user: User = Depends(get_admin_or_super)) -> ScopedUser:
    """
    FastAPI dependency yielding ScopedUser object.
    Every data-returning route uses Depends(get_scoped_user).
    """
    if current_user.role == "super_admin":
        return ScopedUser(user=current_user, scope=None, allowed_file_ids=None)

    scope = await get_user_scope(current_user)
    allowed_file_ids = await resolve_scope_file_ids(scope, current_user.id)
    return ScopedUser(user=current_user, scope=scope, allowed_file_ids=allowed_file_ids)
