from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from beanie import PydanticObjectId

from app.models.user import User
from app.models.user_scope import UserScope
from app.middleware.auth import (
    get_super_admin, hash_password, get_current_user
)

router = APIRouter(prefix="/users", tags=["User Management"])


class UserScopePayload(BaseModel):
    all_regions: bool = True
    region_ids: List[str] = []

    all_countries: bool = True
    country_ids: List[str] = []

    all_ib_versions: bool = True
    ib_version_ids: List[str] = []

    all_brands: bool = True
    brand_models: List[str] = []

    all_cities: bool = True
    survey_locations: List[str] = []

    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None


class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str
    role: str = "admin"
    scope: Optional[UserScopePayload] = None


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    scope: Optional[UserScopePayload] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


def scope_to_dict(s: Optional[UserScope]) -> Optional[dict]:
    if not s:
        return None
    return {
        "id": str(s.id),
        "user_id": str(s.user_id),
        "all_regions": s.all_regions,
        "region_ids": [str(rid) for rid in s.region_ids],
        "all_countries": s.all_countries,
        "country_ids": [str(cid) for cid in s.country_ids],
        "all_ib_versions": s.all_ib_versions,
        "ib_version_ids": [str(ibid) for ibid in s.ib_version_ids],
        "all_brands": s.all_brands,
        "brand_models": s.brand_models,
        "all_cities": s.all_cities,
        "survey_locations": s.survey_locations,
        "valid_from": s.valid_from,
        "valid_until": s.valid_until,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def user_to_dict(u: User) -> dict:
    return {
        "id": str(u.id),
        "username": u.username,
        "email": u.email,
        "full_name": u.full_name,
        "role": u.role,
        "is_active": u.is_active,
        "last_login": u.last_login,
        "created_at": u.created_at,
        "updated_at": u.updated_at,
    }


async def save_or_update_scope(uid: PydanticObjectId, payload: UserScopePayload) -> Optional[UserScope]:
    existing = await UserScope.find_one(UserScope.user_id == uid)
    now = datetime.utcnow()
    reg_ids = [PydanticObjectId(rid) for rid in payload.region_ids if rid]
    c_ids = [PydanticObjectId(cid) for cid in payload.country_ids if cid]
    ib_ids = [PydanticObjectId(ibid) for ibid in payload.ib_version_ids if ibid]

    if existing:
        existing.all_regions = payload.all_regions
        existing.region_ids = reg_ids
        existing.all_countries = payload.all_countries
        existing.country_ids = c_ids
        existing.all_ib_versions = payload.all_ib_versions
        existing.ib_version_ids = ib_ids
        existing.all_brands = payload.all_brands
        existing.brand_models = payload.brand_models
        existing.all_cities = payload.all_cities
        existing.survey_locations = payload.survey_locations
        existing.valid_from = payload.valid_from
        existing.valid_until = payload.valid_until
        existing.updated_at = now
        await existing.save()
        return existing
    else:
        new_scope = UserScope(
            user_id=uid,
            all_regions=payload.all_regions,
            region_ids=reg_ids,
            all_countries=payload.all_countries,
            country_ids=c_ids,
            all_ib_versions=payload.all_ib_versions,
            ib_version_ids=ib_ids,
            all_brands=payload.all_brands,
            brand_models=payload.brand_models,
            all_cities=payload.all_cities,
            survey_locations=payload.survey_locations,
            valid_from=payload.valid_from,
            valid_until=payload.valid_until,
            created_at=now,
            updated_at=now,
        )
        await new_scope.insert()
        return new_scope


@router.get("")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[str] = None,
    is_active: Optional[bool] = None,
    _: User = Depends(get_super_admin),
):
    query = {}
    if search:
        query["$or"] = [
            {"username": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"full_name": {"$regex": search, "$options": "i"}},
        ]
    if role:
        query["role"] = role
    if is_active is not None:
        query["is_active"] = is_active

    skip = (page - 1) * page_size
    total = await User.find(query).count()
    users = await User.find(query).skip(skip).limit(page_size).to_list()

    return {
        "data": [user_to_dict(u) for u in users],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size,
    }


@router.post("", status_code=201)
async def create_user(
    data: CreateUserRequest,
    _: User = Depends(get_super_admin),
):
    existing = await User.find_one(
        {"$or": [{"username": data.username}, {"email": data.email}]}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Username or email already exists")

    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    await user.insert()

    if data.scope is not None and user.role != "super_admin":
        await save_or_update_scope(user.id, data.scope)

    return user_to_dict(user)


@router.get("/{user_id}")
async def get_user(user_id: str, _: User = Depends(get_super_admin)):
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user_to_dict(user)


@router.put("/{user_id}")
async def update_user(
    user_id: str,
    data: UpdateUserRequest,
    _: User = Depends(get_super_admin),
):
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = data.model_dump(exclude_none=True, exclude={"scope"})
    update_data["updated_at"] = datetime.utcnow()
    await user.update({"$set": update_data})
    await user.sync()

    if data.scope is not None and user.role != "super_admin":
        await save_or_update_scope(user.id, data.scope)

    return user_to_dict(user)


@router.delete("/{user_id}")
async def delete_user(user_id: str, _: User = Depends(get_super_admin)):
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "super_admin":
        raise HTTPException(status_code=400, detail="Cannot delete Super Admin")
    
    # Also delete associated user scope
    existing_scope = await UserScope.find_one(UserScope.user_id == user.id)
    if existing_scope:
        await existing_scope.delete()

    await user.delete()
    return {"message": "User deleted successfully"}


@router.get("/{user_id}/scope")
async def get_user_scope_endpoint(user_id: str, _: User = Depends(get_super_admin)):
    s = await UserScope.find_one(UserScope.user_id == PydanticObjectId(user_id))
    return scope_to_dict(s)


@router.put("/{user_id}/scope")
async def upsert_user_scope_endpoint(
    user_id: str,
    payload: UserScopePayload,
    _: User = Depends(get_super_admin),
):
    uid = PydanticObjectId(user_id)
    u = await User.get(uid)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    scope = await save_or_update_scope(uid, payload)
    return scope_to_dict(scope)


@router.delete("/{user_id}/scope")
async def clear_user_scope_endpoint(user_id: str, _: User = Depends(get_super_admin)):
    uid = PydanticObjectId(user_id)
    existing = await UserScope.find_one(UserScope.user_id == uid)
    if existing:
        await existing.delete()
    return {"message": "Scope cleared"}


@router.put("/{user_id}/toggle-status")
async def toggle_status(user_id: str, _: User = Depends(get_super_admin)):
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user.update({"$set": {
        "is_active": not user.is_active,
        "updated_at": datetime.utcnow(),
    }})
    await user.sync()
    return {"is_active": user.is_active}


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    data: ResetPasswordRequest,
    _: User = Depends(get_super_admin),
):
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    await user.update({"$set": {
        "password_hash": hash_password(data.new_password),
        "updated_at": datetime.utcnow(),
    }})
    return {"message": "Password reset successfully"}
