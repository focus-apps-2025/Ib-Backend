from beanie import Document, Indexed
from pydantic import EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from pymongo import IndexModel, ASCENDING


class ColumnVisibility(dict):
    pass


class UserPreferences(dict):
    pass


class User(Document):
    username: Indexed(str, unique=True)
    email: Indexed(EmailStr, unique=True)
    password_hash: str
    full_name: str
    role: str = "admin"  # 'super_admin' | 'admin'
    is_active: bool = True
    last_login: Optional[datetime] = None
    last_ip: Optional[str] = None
    last_user_agent: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "users"
        indexes = [
            IndexModel([("username", ASCENDING)], unique=True),
            IndexModel([("email", ASCENDING)], unique=True),
            IndexModel([("role", ASCENDING)]),
            IndexModel([("is_active", ASCENDING)]),
        ]
