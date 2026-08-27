"""
User controller - Business logic for user management.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.user import User
from app.middleware.auth import hash_password


class UserController:
    """Controller for user management operations."""
    
    @staticmethod
    async def list_users(
        page: int = 1,
        page_size: int = 25,
        search: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        List users with pagination and filters.
        """
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
            "data": [UserController._user_to_dict(u) for u in users],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    @staticmethod
    async def create_user(
        username: str,
        email: str,
        password: str,
        full_name: str,
        role: str = "admin",
    ) -> Dict[str, Any]:
        """
        Create a new user.
        """
        existing = await User.find_one(
            {"$or": [{"username": username}, {"email": email}]}
        )
        if existing:
            raise HTTPException(status_code=400, detail="Username or email already exists")

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
        )
        await user.insert()
        logger.info(f"User created: {username}")
        return UserController._user_to_dict(user)

    @staticmethod
    async def get_user(user_id: str) -> Dict[str, Any]:
        """
        Get user by ID.
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserController._user_to_dict(user)

    @staticmethod
    async def update_user(
        user_id: str,
        full_name: Optional[str] = None,
        email: Optional[str] = None,
        role: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Update user details.
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        update_data = {}
        if full_name:
            update_data["full_name"] = full_name
        if email:
            update_data["email"] = email
        if role:
            update_data["role"] = role
        update_data["updated_at"] = datetime.utcnow()
        
        await user.update({"$set": update_data})
        await user.sync()
        logger.info(f"User updated: {user_id}")
        return UserController._user_to_dict(user)

    @staticmethod
    async def delete_user(user_id: str) -> Dict[str, Any]:
        """
        Delete user.
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        if user.role == "super_admin":
            raise HTTPException(status_code=400, detail="Cannot delete Super Admin")
            
        await user.delete()
        logger.info(f"User deleted: {user_id}")
        return {"message": "User deleted successfully"}

    @staticmethod
    async def toggle_user_status(user_id: str) -> Dict[str, Any]:
        """
        Toggle user active status.
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        await user.update({"$set": {
            "is_active": not user.is_active,
            "updated_at": datetime.utcnow(),
        }})
        await user.sync()
        logger.info(f"User status toggled: {user_id} -> active={user.is_active}")
        return {"is_active": user.is_active}

    @staticmethod
    async def reset_password(user_id: str, new_password: str) -> Dict[str, Any]:
        """
        Reset user password (admin only).
        """
        user = await User.get(PydanticObjectId(user_id))
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
            
        await user.update({"$set": {
            "password_hash": hash_password(new_password),
            "updated_at": datetime.utcnow(),
        }})
        logger.info(f"Password reset for user: {user_id}")
        return {"message": "Password reset successfully"}

    @staticmethod
    def _user_to_dict(user: User) -> Dict[str, Any]:
        """
        Convert User model to dictionary.
        """
        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "is_active": user.is_active,
            "last_login": user.last_login,
            "created_at": user.created_at,
            "updated_at": user.updated_at,
        }