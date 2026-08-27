"""
User schemas - User management request/response models.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class CreateUserRequest(BaseModel):
    """Create user request schema."""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1)
    role: str = Field("admin", pattern="^(admin|super_admin)$")


class UpdateUserRequest(BaseModel):
    """Update user request schema."""
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = Field(None, pattern="^(admin|super_admin)$")


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""
    new_password: str = Field(..., min_length=8)


class UserResponse(BaseModel):
    """User response schema."""
    id: str
    username: str
    email: EmailStr
    full_name: str
    role: str
    is_active: bool
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    """User list response schema."""
    data: list[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int