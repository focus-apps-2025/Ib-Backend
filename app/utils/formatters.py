"""
Formatting utilities.
"""
from datetime import datetime
from typing import Any, Optional
import json


def format_date(date: Optional[datetime], format_str: str = "%Y-%m-%d") -> str:
    """
    Format datetime to string.
    """
    if not date:
        return ""
    return date.strftime(format_str)


def format_datetime(date: Optional[datetime]) -> str:
    """
    Format datetime to ISO string.
    """
    if not date:
        return ""
    return date.isoformat()


def format_number(value: Optional[float], decimals: int = 2) -> str:
    """
    Format number with specified decimal places.
    """
    if value is None:
        return "0"
    return f"{value:.{decimals}f}"


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format as percentage string.
    """
    return f"{value:.{decimals}f}%"


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format.
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate text to specified length.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix


def safe_json_loads(data: str, default: Any = None) -> Any:
    """
    Safely parse JSON string.
    """
    try:
        return json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return default


def to_camel_case(text: str) -> str:
    """
    Convert snake_case to camelCase.
    """
    parts = text.split('_')
    return parts[0] + ''.join(word.capitalize() for word in parts[1:])


def to_snake_case(text: str) -> str:
    """
    Convert camelCase to snake_case.
    """
    import re
    return re.sub(r'(?<!^)(?=[A-Z])', '_', text).lower()