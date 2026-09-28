"""Shared helpers for turning the frontend multi-select filter params into MongoDB queries.

The dashboard filter bar (``frontend/src/components/dashboard/MultiSelectFilter``)
sends multi-select values comma-joined, e.g. ``?region_id=r1,r2`` or
``?brand_model=TVS%20Raider,Bajaj%20Pulsar``.
These helpers parse those strings into a single Mongo filter value:
- a scalar (``ObjectId`` / regex) when only one value was selected, preserving the
  previous single-select behaviour exactly, and
- ``{"$in": [...]}`` when several values were selected.
"""
import re

from beanie import PydanticObjectId


def id_match(value):
    """Mongo match value for a possibly comma-separated list of Mongo ids.

    Returns ``None`` for empty input, a single :class:`PydanticObjectId`, or
    ``{"$in": [ObjectId, ...]}`` for several ids.
    """
    if not value:
        return None
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if not parts:
        return None
    ids = [PydanticObjectId(p) for p in parts]
    if len(ids) == 1:
        return ids[0]
    return {"$in": ids}


def text_match(value, exact=False):
    """Mongo match value for a possibly comma-separated list of text values
    (brand models, survey locations, …).

    Returns ``None`` for empty input, a single case-insensitive regex object
    (as a plain regex string when passed straight into ``$match``/``find`` needs
    ``re.compile`` for ``$in``), or ``{"$in": [compiled regexes, ...]}`` for
    several values.

    When ``exact`` is ``True`` each value is anchored with ``^...$``.
    """
    if not value:
        return None
    parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if not parts:
        return None
    if len(parts) == 1:
        pattern = f"^{re.escape(parts[0])}$" if exact else re.escape(parts[0])
        return {"$regex": pattern, "$options": "i"}
    patterns = [
        re.compile(f"^{re.escape(p)}$" if exact else re.escape(p), re.IGNORECASE)
        for p in parts
    ]
    return {"$in": patterns}
