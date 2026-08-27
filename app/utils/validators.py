"""
Validation utilities.
"""
import re
from typing import Optional, Any
from datetime import datetime


def validate_email(email: str) -> bool:
    """
    Validate email format.
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """
    Validate phone number format.
    """
    pattern = r'^\+?[1-9]\d{1,14}$'
    return bool(re.match(pattern, phone))


def validate_date_range(start_date: datetime, end_date: datetime) -> bool:
    """
    Validate that start date is before end date.
    """
    return start_date <= end_date


def validate_file_size(file_size: int, max_size_mb: int) -> bool:
    """
    Validate file size doesn't exceed limit.
    """
    return file_size <= max_size_mb * 1024 * 1024


def validate_file_extension(filename: str, allowed_extensions: list) -> bool:
    """
    Validate file extension.
    """
    ext = filename.lower().split('.')[-1] if '.' in filename else ''
    return ext in allowed_extensions


def is_blank_value(value: Any) -> bool:
    """
    Check if value is blank/empty.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() in ("", "Blank", "nan", "NaT", "None")
    if isinstance(value, (int, float)):
        return False
    return False