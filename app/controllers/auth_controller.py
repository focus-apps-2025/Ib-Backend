"""
Auth controller - Business logic for authentication.
"""
from datetime import datetime
from typing import Dict, Any
from fastapi import Request, HTTPException
from beanie import PydanticObjectId
from loguru import logger

from app.models.user import User
from app.models.activity_log import ActivityLog
from app.middleware.auth import (
    hash_password, verify_password, 
    create_access_token, create_refresh_token, decode_token
)
from app.config.settings import settings


class AuthController:
    """Controller for authentication operations."""
    
    @staticmethod
    async def login(username: str, password: str, request: Request) -> Dict[str, Any]:
        """
        Authenticate user and return tokens.
        """
        # Find user by username or email
        user = await User.find_one(
            {"$or": [{"username": username}, {"email": username}]}
        )
        
        if not user or not verify_password(password, user.password_hash):
            logger.warning(f"Failed login attempt for username: {username}")
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

    @staticmethod
    async def refresh_token(refresh_token: str) -> Dict[str, Any]:
        """
        Refresh access token using refresh token.
        """
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        user = await User.get(PydanticObjectId(payload["sub"]))
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found")

        token_data = {"sub": str(user.id), "role": user.role}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data),
            "token_type": "bearer",
        }

    @staticmethod
    async def get_current_user(user_id: str) -> User:
        """
        Get current user by ID.
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user or not user.is_active:
            raise HTTPException(status_code=401, detail="User not found or inactive")
        return user

    @staticmethod
    async def change_password(user_id: str, current_password: str, new_password: str) -> Dict[str, Any]:
        """
        Change user password.
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        if not verify_password(current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
            
        new_hash = hash_password(new_password)
        await user.update({"$set": {
            "password_hash": new_hash,
            "updated_at": datetime.utcnow(),
        }})
        
        return {"message": "Password changed successfully"}

    @staticmethod
    async def logout(user: User, request: Request) -> Dict[str, Any]:
        """
        Logout user and log activity.
        """
        ip = request.client.host if request.client else "unknown"
        await ActivityLog(
            user_id=user.id,
            username=user.username,
            action="logout",
            details={"description": f"{user.full_name} logged out"},
            ip_address=ip,
        ).insert()
        
        return {"message": "Logged out successfully"}