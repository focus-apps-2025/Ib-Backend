"""
Datetime utilities.
"""
from datetime import datetime, timedelta, date
from typing import Optional, Tuple
import pytz


def utc_now() -> datetime:
    """
    Get current UTC datetime.
    """
    return datetime.utcnow()


def get_date_range(period: str) -> Tuple[datetime, datetime]:
    """
    Get date range for common periods.
    """
    now = utc_now()
    
    if period == "today":
        start = datetime(now.year, now.month, now.day)
        end = start + timedelta(days=1)
    elif period == "yesterday":
        start = datetime(now.year, now.month, now.day) - timedelta(days=1)
        end = start + timedelta(days=1)
    elif period == "last_7_days":
        start = now - timedelta(days=7)
        end = now
    elif period == "last_30_days":
        start = now - timedelta(days=30)
        end = now
    elif period == "last_90_days":
        start = now - timedelta(days=90)
        end = now
    elif period == "this_month":
        start = datetime(now.year, now.month, 1)
        next_month = start + timedelta(days=32)
        end = datetime(next_month.year, next_month.month, 1)
    elif period == "last_month":
        first = datetime(now.year, now.month, 1) - timedelta(days=1)
        start = datetime(first.year, first.month, 1)
        end = datetime(now.year, now.month, 1)
    else:
        # Default to last 30 days
        start = now - timedelta(days=30)
        end = now
        
    return start, end


def parse_date_safe(date_str: Optional[str]) -> Optional[datetime]:
    """
    Safely parse date string.
    """
    if not date_str:
        return None
        
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


def parse_date_filter(date_str: Optional[str]) -> Optional[datetime]:
    """
    Parse a filter date string into a datetime.

    Accepts:
      - "YYYY-MM"  (month granularity; resolves to the 1st of that month)
      - "YYYY-MM-DD"
      - Full ISO 8601 datetimes (as produced by ``datetime.isoformat()``).

    Returns ``None`` for empty or unparseable input.
    """
    if not date_str:
        return None
    s = date_str.strip()
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        pass
    try:
        return datetime.strptime(s, "%Y-%m")
    except ValueError:
        pass
    return None


def get_age_group(age: Optional[float]) -> str:
    """
    Get age group string.
    """
    if age is None:
        return "Unknown"
    if age < 18:
        return "Under 18"
    if age < 25:
        return "18-24"
    if age < 35:
        return "25-34"
    if age < 45:
        return "35-44"
    if age < 55:
        return "45-54"
    if age < 65:
        return "55-64"
    return "65+"


def time_delta_str(seconds: int) -> str:
    """
    Format time delta in human-readable string.
    """
    if seconds < 60:
        return f"{seconds} seconds"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minutes"
    if seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hours"
    days = seconds // 86400
    return f"{days} days"