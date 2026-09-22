from typing import Optional, List, Any
from datetime import datetime
from beanie import PydanticObjectId

from app.models.user import User
from app.models.user_scope import UserScope
from app.models.uploaded_file import UploadedFile


def is_scope_valid_now(scope: Optional[UserScope]) -> bool:
    """Check if the scope is temporally valid based on valid_from and valid_until."""
    if not scope:
        return True
    now = datetime.utcnow()
    if scope.valid_from and now < scope.valid_from:
        return False
    if scope.valid_until and now > scope.valid_until:
        return False
    return True


async def get_user_scope(user: User) -> Optional[UserScope]:
    """
    Get user scope document.
    Super admins are always unrestricted (returns None).
    If a non-super-admin has no UserScope document, returns None (unrestricted for backward compatibility).
    """
    if not user or user.role == "super_admin":
        return None
    return await UserScope.find_one(UserScope.user_id == user.id)


async def resolve_scope_file_ids(
    scope: Optional[UserScope],
    user_id: Optional[PydanticObjectId] = None
) -> Optional[List[PydanticObjectId]]:
    """
    Translates region/country/IB filters into a list of allowed file_ids by querying UploadedFile.
    Also restricts to assigned_admin_id if user_id is provided.
    Returns None if unrestricted, or a List[PydanticObjectId] of allowed file IDs (can be empty list []).
    """
    if scope is None and user_id is None:
        return None

    if scope is not None and not is_scope_valid_now(scope):
        return []

    file_query = {}
    if user_id is not None:
        file_query["assigned_admin_id"] = user_id

    if scope is not None:
        # If any non-all dimension has empty list, user sees nothing
        if (not scope.all_regions and not scope.region_ids) or \
           (not scope.all_countries and not scope.country_ids) or \
           (not scope.all_ib_versions and not scope.ib_version_ids):
            return []

        if not scope.all_regions:
            file_query["region_id"] = {"$in": scope.region_ids}
        if not scope.all_countries:
            file_query["country_id"] = {"$in": scope.country_ids}
        if not scope.all_ib_versions:
            file_query["ib_version_id"] = {"$in": scope.ib_version_ids}

    # If all file dimensions are unrestricted and no user_id restriction
    if not file_query:
        return None

    files = await UploadedFile.find(file_query).to_list()
    return [f.id for f in files]


def apply_scope_to_survey_query(
    query: dict,
    scope: Optional[UserScope],
    allowed_file_ids: Optional[List[PydanticObjectId]] = None,
) -> dict:
    """
    Merges allowed_file_ids into a survey query dict.
    Region/Country/IB scope is enforced via file_id restriction.
    Brand/City scope is NOT applied here — it only controls which options
    appear in the filter-options dropdown (see responses.py filter-options).
    """
    q = dict(query or {})

    if scope is not None and not is_scope_valid_now(scope):
        q["file_id"] = {"$in": []}
        return q

    # Apply allowed_file_ids restriction (derived from region/country/IB scope)
    if allowed_file_ids is not None:
        if "file_id" in q:
            existing_fid = q["file_id"]
            if isinstance(existing_fid, dict) and "$in" in existing_fid:
                req_ids = existing_fid["$in"]
                intersection = [fid for fid in req_ids if fid in allowed_file_ids]
                q["file_id"] = {"$in": intersection}
            elif isinstance(existing_fid, (PydanticObjectId, str)):
                fid_obj = PydanticObjectId(existing_fid) if isinstance(existing_fid, str) else existing_fid
                if fid_obj in allowed_file_ids:
                    q["file_id"] = fid_obj
                else:
                    q["file_id"] = {"$in": []}
        else:
            q["file_id"] = {"$in": allowed_file_ids}

    return q



def apply_scope_to_file_query(
    query: dict,
    scope: Optional[UserScope],
    user_id: Optional[PydanticObjectId] = None
) -> dict:
    """
    Merges region/country/IB filters and assigned_admin_id into an UploadedFile query dict.
    """
    q = dict(query or {})

    if user_id is not None:
        q["assigned_admin_id"] = user_id

    if scope is None:
        return q

    if not is_scope_valid_now(scope):
        q["_id"] = {"$in": []}
        return q

    # Region filter
    if not scope.all_regions:
        allowed = scope.region_ids or []
        if not allowed:
            q["region_id"] = {"$in": []}
        elif "region_id" in q:
            req = q["region_id"]
            if isinstance(req, (PydanticObjectId, str)):
                req_obj = PydanticObjectId(req) if isinstance(req, str) else req
                q["region_id"] = req_obj if req_obj in allowed else {"$in": []}
            elif isinstance(req, dict) and "$in" in req:
                q["region_id"] = {"$in": [rid for rid in req["$in"] if rid in allowed]}
        else:
            q["region_id"] = {"$in": allowed}

    # Country filter
    if not scope.all_countries:
        allowed = scope.country_ids or []
        if not allowed:
            q["country_id"] = {"$in": []}
        elif "country_id" in q:
            req = q["country_id"]
            if isinstance(req, (PydanticObjectId, str)):
                req_obj = PydanticObjectId(req) if isinstance(req, str) else req
                q["country_id"] = req_obj if req_obj in allowed else {"$in": []}
            elif isinstance(req, dict) and "$in" in req:
                q["country_id"] = {"$in": [cid for cid in req["$in"] if cid in allowed]}
        else:
            q["country_id"] = {"$in": allowed}

    # IB version filter
    if not scope.all_ib_versions:
        allowed = scope.ib_version_ids or []
        if not allowed:
            q["ib_version_id"] = {"$in": []}
        elif "ib_version_id" in q:
            req = q["ib_version_id"]
            if isinstance(req, (PydanticObjectId, str)):
                req_obj = PydanticObjectId(req) if isinstance(req, str) else req
                q["ib_version_id"] = req_obj if req_obj in allowed else {"$in": []}
            elif isinstance(req, dict) and "$in" in req:
                q["ib_version_id"] = {"$in": [ibid for ibid in req["$in"] if ibid in allowed]}
        else:
            q["ib_version_id"] = {"$in": allowed}

    return q


def is_value_in_scope(scope: Optional[UserScope], dimension: str, value_id_or_str: Any) -> bool:
    """
    Single-value check for scope validation (e.g. upload permission).
    Returns True if unrestricted or value is permitted under scope.
    """
    if scope is None:
        return True

    if not is_scope_valid_now(scope):
        return False

    if dimension == "region":
        if scope.all_regions:
            return True
        val_obj = PydanticObjectId(value_id_or_str) if isinstance(value_id_or_str, str) else value_id_or_str
        return val_obj in (scope.region_ids or [])

    if dimension == "country":
        if scope.all_countries:
            return True
        val_obj = PydanticObjectId(value_id_or_str) if isinstance(value_id_or_str, str) else value_id_or_str
        return val_obj in (scope.country_ids or [])

    if dimension == "ib_version":
        if scope.all_ib_versions:
            return True
        val_obj = PydanticObjectId(value_id_or_str) if isinstance(value_id_or_str, str) else value_id_or_str
        return val_obj in (scope.ib_version_ids or [])

    if dimension == "brand":
        if scope.all_brands:
            return True
        return str(value_id_or_str) in (scope.brand_models or [])

    if dimension == "city":
        if scope.all_cities:
            return True
        return str(value_id_or_str) in (scope.survey_locations or [])

    return False
