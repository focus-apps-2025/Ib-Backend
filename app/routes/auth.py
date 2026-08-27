from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional

from app.models.user import User
from app.models.activity_log import ActivityLog
from app.middleware.auth import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/login")
async def login(data: LoginRequest, request: Request):
    # Find user by username or email
    user = await User.find_one(
        {"$or": [{"username": data.username}, {"email": data.username}]}
    )
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    # Update last login
    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")
    await user.update({"$set": {
        "last_login": datetime.utcnow(),
        "last_ip": ip,
        "last_user_agent": ua,
        "updated_at": datetime.utcnow(),
    }})

    # Activity log
    await ActivityLog(
        user_id=user.id,
        username=user.username,
        action="login",
        details={"description": f"{user.full_name} logged in"},
        ip_address=ip,
        user_agent=ua,
    ).insert()

    token_data = {"sub": str(user.id), "role": user.role}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
        "user": {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": user.is_active,
        },
    }


@router.post("/refresh-token")
async def refresh_token(data: RefreshRequest):
    payload = decode_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    from beanie import PydanticObjectId
    user = await User.get(PydanticObjectId(payload["sub"]))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found")

    token_data = {"sub": str(user.id), "role": user.role}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role,
        "is_active": current_user.is_active,
        "last_login": current_user.last_login,
        "preferences": current_user.preferences,
    }


@router.post("/logout")
async def logout(request: Request, current_user: User = Depends(get_current_user)):
    ip = request.client.host if request.client else "unknown"
    await ActivityLog(
        user_id=current_user.id,
        username=current_user.username,
        action="logout",
        details={"description": f"{current_user.full_name} logged out"},
        ip_address=ip,
    ).insert()
    return {"message": "Logged out successfully"}


@router.post("/change-password")
async def change_password(
    data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    new_hash = hash_password(data.new_password)
    await current_user.update({"$set": {
        "password_hash": new_hash,
        "updated_at": datetime.utcnow(),
    }})
    return {"message": "Password changed successfully"}
