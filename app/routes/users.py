from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime
from beanie import PydanticObjectId

from app.models.user import User
from app.middleware.auth import (
    get_super_admin, hash_password, get_current_user
)

router = APIRouter(prefix="/users", tags=["User Management"])


class CreateUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str
    role: str = "admin"


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


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
    update_data = data.model_dump(exclude_none=True)
    update_data["updated_at"] = datetime.utcnow()
    await user.update({"$set": update_data})
    await user.sync()
    return user_to_dict(user)


@router.delete("/{user_id}")
async def delete_user(user_id: str, _: User = Depends(get_super_admin)):
    user = await User.get(PydanticObjectId(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.role == "super_admin":
        raise HTTPException(status_code=400, detail="Cannot delete Super Admin")
    await user.delete()
    return {"message": "User deleted successfully"}


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
