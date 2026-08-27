from fastapi import APIRouter, Depends
from typing import Optional

from app.models.user import User
from app.middleware.auth import get_admin_or_super

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
async def dashboard_stats(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """Combined dashboard summary stats."""
    from app.models.survey_response import SurveyResponse
    from app.models.uploaded_file import UploadedFile
    from app.models.issue_analysis import IssueAnalysis
    from beanie import PydanticObjectId

    file_ids = []
    if file_id:
        file_ids = [PydanticObjectId(file_id)]
    elif region_id or country_id or ib_version_id:
        file_query = {}
        if region_id:
            file_query["region_id"] = PydanticObjectId(region_id)
        if country_id:
            file_query["country_id"] = PydanticObjectId(country_id)
        if ib_version_id:
            file_query["ib_version_id"] = PydanticObjectId(ib_version_id)
        files = await UploadedFile.find({**file_query, "status": "completed"}).to_list()
        file_ids = [f.id for f in files]

    query = {}
    if file_ids:
        query["file_id"] = {"$in": file_ids}
    elif region_id or country_id or ib_version_id:
        # Filters specified but no matching completed uploads → return empty
        query["file_id"] = {"$in": []}

    total_records = await SurveyResponse.find(query).count()
    brands = await SurveyResponse.distinct("brand_model", filter=query if query else None)
    locations = await SurveyResponse.distinct("survey_location", filter=query if query else None)
    total_uploads = await UploadedFile.find(
        {"status": "completed", **({"region_id": PydanticObjectId(region_id)} if region_id else {}),
         **({"country_id": PydanticObjectId(country_id)} if country_id else {}),
         **({"ib_version_id": PydanticObjectId(ib_version_id)} if ib_version_id else {})}
    ).count()

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "nps_score": 1,
                "complaint_count": {
                    "$size": {
                        "$filter": {
                            "input": {"$ifNull": ["$complaint_groups", []]},
                            "as": "issue",
                            "cond": {
                                "$not": {
                                    "$regexMatch": {
                                        "input": "$$issue",
                                        "regex": "^submitform",
                                        "options": "i",
                                    }
                                }
                            },
                        }
                    }
                },
            }
        },
        {"$group": {
            "_id": None,
            "avg_nps": {"$avg": "$nps_score"},
            "total_complaints": {"$sum": "$complaint_count"},
        }},
    ]
    agg = await SurveyResponse.aggregate(pipeline).to_list()
    stats = agg[0] if agg else {}

    return {
        "total_records": total_records,
        "total_uploads": total_uploads,
        "total_brands": len([b for b in brands if b and b != "Blank"]),
        "unique_locations": len([l for l in locations if l and l != "Blank"]),
        "average_nps": round(stats.get("avg_nps") or 0, 1),
        "total_complaints": stats.get("total_complaints", 0),
    }


@router.get("/charts/brand-distribution")
async def brand_distribution(_: User = Depends(get_admin_or_super)):
    from app.models.survey_response import SurveyResponse
    pipeline = [
        {"$group": {"_id": "$brand_model", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list()
    return {"data": [{"label": r["_id"] or "Unknown", "count": r["count"]} for r in results]}


@router.get("/charts/nps-distribution")
async def nps_distribution(_: User = Depends(get_admin_or_super)):
    from app.models.survey_response import SurveyResponse
    pipeline = [
        {"$match": {"nps_score": {"$ne": None}}},
        {"$group": {"_id": "$nps_score", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list()
    return {"data": [{"score": r["_id"], "count": r["count"]} for r in results]}


@router.get("/charts/location-issues")
async def location_issues_heatmap(_: User = Depends(get_admin_or_super)):
    """Heatmap: location × issue count."""
    from app.models.survey_response import SurveyResponse
    pipeline = [
        {"$match": {"complaint_groups": {"$ne": []}}},
        {"$unwind": "$complaint_groups"},
        {
            "$match": {
                "complaint_groups": {
                    "$not": {"$regex": "^submitform", "$options": "i"}
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "location": "$survey_location",
                    "issue": "$complaint_groups",
                },
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": 500},
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list()
    return {
        "data": [
            {
                "location": r["_id"]["location"],
                "issue": r["_id"]["issue"],
                "count": r["count"],
            }
            for r in results
        ]
    }


async def _build_file_query(
    file_id: Optional[str],
    region_id: Optional[str],
    country_id: Optional[str],
    ib_version_id: Optional[str],
):
    """Build a file_id $in query from the given filters."""
    from app.models.uploaded_file import UploadedFile
    from beanie import PydanticObjectId

    file_ids = []
    if file_id:
        file_ids = [PydanticObjectId(file_id)]
    elif region_id or country_id or ib_version_id:
        file_query = {}
        if region_id:
            file_query["region_id"] = PydanticObjectId(region_id)
        if country_id:
            file_query["country_id"] = PydanticObjectId(country_id)
        if ib_version_id:
            file_query["ib_version_id"] = PydanticObjectId(ib_version_id)
        files = await UploadedFile.find({**file_query, "status": "completed"}).to_list()
        file_ids = [f.id for f in files]

    query = {}
    if file_ids:
        query["file_id"] = {"$in": file_ids}
    elif region_id or country_id or ib_version_id:
        # Filters specified but no matching completed uploads → return empty
        query["file_id"] = {"$in": []}
    return query


@router.get("/brand-comparison")
async def brand_comparison(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Brand-wise comparison between Passive (Good) feedback and Issues (Complaints).
    Returns for each brand: passive_count, issues_count, total_responses.
    """
    from app.models.survey_response import SurveyResponse

    query = await _build_file_query(file_id, region_id, country_id, ib_version_id)

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand_model": 1,
                "complaint_groups": 1,
                "passive_values": {
                    "$filter": {
                        "input": {
                            "$reduce": {
                                "input": {"$objectToArray": {"$ifNull": ["$passive_data", {}]}},
                                "initialValue": [],
                                "in": {"$concatArrays": ["$$value", "$$this.v"]},
                            }
                        },
                        "as": "val",
                        "cond": {
                            "$not": {
                                "$regexMatch": {
                                    "input": "$$val",
                                    "regex": "^submitform",
                                    "options": "i",
                                }
                            }
                        },
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$brand_model",
                "total_responses": {"$sum": 1},
                "passive_count": {"$sum": {"$size": "$passive_values"}},
                "issues_count": {
                    "$sum": {
                        "$size": {
                            "$filter": {
                                "input": {"$ifNull": ["$complaint_groups", []]},
                                "as": "issue",
                                "cond": {
                                    "$not": {
                                        "$regexMatch": {
                                            "input": "$$issue",
                                            "regex": "^submitform",
                                            "options": "i",
                                        }
                                    }
                                },
                            }
                        }
                    }
                },
            }
        },
        {"$sort": {"total_responses": -1}},
        {"$limit": 50},
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list()

    data = []
    for r in results:
        brand = r["_id"] or "Unknown"
        if brand == "Blank":
            continue
        data.append({
            "brand": brand,
            "passive_count": r.get("passive_count", 0),
            "issues_count": r.get("issues_count", 0),
            "total_responses": r.get("total_responses", 0),
        })

    return {"data": data}


@router.get("/passive-topics")
async def passive_topics(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Count of positive feedback per topic (from passive_data).
    Sorted by count descending.
    """
    from app.models.survey_response import SurveyResponse

    query = await _build_file_query(file_id, region_id, country_id, ib_version_id)

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "passive_entries": {
                    "$objectToArray": {"$ifNull": ["$passive_data", {}]}
                }
            }
        },
        {"$unwind": "$passive_entries"},
        {
            "$project": {
                "topic": "$passive_entries.k",
                "count": {
                    "$size": {
                        "$filter": {
                            "input": "$passive_entries.v",
                            "as": "val",
                            "cond": {
                                "$not": {
                                    "$regexMatch": {
                                        "input": "$$val",
                                        "regex": "^submitform",
                                        "options": "i",
                                    }
                                }
                            },
                        }
                    }
                },
            }
        },
        {
            "$group": {
                "_id": "$topic",
                "count": {"$sum": "$count"},
            }
        },
        {"$sort": {"count": -1}},
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list()

    data = [
        {"topic": r["_id"] or "Unknown", "count": r.get("count", 0)}
        for r in results
    ]

    return {"data": data}


@router.get("/brand-topics")
async def brand_topics(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Per-brand topic breakdown for both passive (good) feedback and issues (complaints).
    Returns for each brand: passive_topics {topic: count}, issues_topics {issue: count}.
    """
    from app.models.survey_response import SurveyResponse

    query = await _build_file_query(file_id, region_id, country_id, ib_version_id)

    # Passive topics per brand
    passive_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand_model": 1,
                "passive_entries": {
                    "$objectToArray": {"$ifNull": ["$passive_data", {}]}
                },
            }
        },
        {"$unwind": "$passive_entries"},
        {
            "$project": {
                "brand": "$brand_model",
                "topic": "$passive_entries.k",
                "count": {
                    "$size": {
                        "$filter": {
                            "input": "$passive_entries.v",
                            "as": "val",
                            "cond": {
                                "$not": {
                                    "$regexMatch": {
                                        "input": "$$val",
                                        "regex": "^submitform",
                                        "options": "i",
                                    }
                                }
                            },
                        }
                    }
                },
            }
        },
        {
            "$group": {
                "_id": {"brand": "$brand", "topic": "$topic"},
                "count": {"$sum": "$count"},
            }
        },
        {"$sort": {"count": -1}},
    ]
    passive_results = await SurveyResponse.aggregate(passive_pipeline).to_list()

    # Issues topics per brand
    issues_pipeline = [
        {"$match": query},
        {"$unwind": "$complaint_groups"},
        {
            "$match": {
                "complaint_groups": {
                    "$not": {"$regex": "^submitform", "$options": "i"}
                }
            }
        },
        {
            "$group": {
                "_id": {"brand": "$brand_model", "topic": "$complaint_groups"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
    ]
    issues_results = await SurveyResponse.aggregate(issues_pipeline).to_list()

    # Merge into per-brand structure
    brands = {}
    for r in passive_results:
        brand = r["_id"]["brand"] or "Unknown"
        topic = r["_id"]["topic"] or ""
        if brand == "Blank" or not topic or topic.lower().startswith("submitform"):
            continue
        brands.setdefault(brand, {"brand": brand, "passive_topics": {}, "issues_topics": {}})
        brands[brand]["passive_topics"][topic] = r["count"]

    for r in issues_results:
        brand = r["_id"]["brand"] or "Unknown"
        topic = r["_id"]["topic"] or ""
        if brand == "Blank" or not topic or topic.lower().startswith("submitform"):
            continue
        brands.setdefault(brand, {"brand": brand, "passive_topics": {}, "issues_topics": {}})
        brands[brand]["issues_topics"][topic] = r["count"]

    return {"data": list(brands.values())}


# ============================================================
# ANALYTICS ENDPOINT — 5 detailed visualizations for the new Dashboard tab
# ============================================================

AGE_GROUPS = ["Less than 20", "20-30", "30-40", "40-50", "50-60"]

MODE_PURCHASE_ORDER = ["New", "Second Hand", "0 km", "Pre-owned"]
OWNERSHIP_ORDER = ["Own", "Hired (Rent)", "Rented", "Company"]


def _age_group_from_age(age):
    """Map a numeric age to an age group label."""
    if age is None:
        return None
    try:
        age = float(age)
    except (ValueError, TypeError):
        return None
    if age < 20:
        return "Less than 20"
    if age < 30:
        return "20-30"
    if age < 40:
        return "30-40"
    if age < 50:
        return "40-50"
    if age < 60:
        return "50-60"
    return None  # Age >= 60 excluded from the 5 defined groups


def _normalize_mode_purchase(val):
    if not val:
        return None
    v = str(val).strip().lower()
    if v in ("new", "brand new"):
        return "New"
    if v in ("second hand", "secondhand", "used", "old"):
        return "Second Hand"
    if v in ("0 km", "0km"):
        return "0 km"
    if v in ("pre-owned", "preowned"):
        return "Pre-owned"
    return None


def _normalize_ownership(val):
    if not val:
        return None
    v = str(val).strip().lower()
    if v in ("own", "owned", "self"):
        return "Own"
    if v in ("hired", "rent", "rented", "rental"):
        return "Hired (Rent)"
    return None


def clean_brand_name(brand_model):
    """Normalise a raw ``brand_model`` value into a canonical brand label.

    This mirrors the logic used in ``app.routes.issues`` so that brand names
    are consistent across every endpoint.
    """
    if not brand_model:
        return "Unknown"
    return str(brand_model).strip()


@router.get("/analytics")
async def dashboard_analytics(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Detailed dashboard analytics using MongoDB aggregation pipelines:
    age group, age×city, mode of purchase, ownership, and profession breakdowns per brand.
    """
    from app.models.survey_response import SurveyResponse
    from collections import defaultdict

    query = await _build_file_query(file_id, region_id, country_id, ib_version_id)
    # Fetch distinct brands from the DB (normalised) instead of hardcoding
    raw_brands = await SurveyResponse.distinct(
        "brand_model", filter=query if query else None
    )
    BRANDS = sorted(set(clean_brand_name(b) for b in raw_brands if b and b != "Blank"))
    AGE_GROUPS = ["Less than 20", "20-30", "30-40", "40-50", "50-60"]

    # ── 1. Age Group Distribution ─────────────────────────────────
    age_group_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {
                    "$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "TVS|HLX", "options": "i"}},
                        "TVS HLX 125",
                        {
                            "$cond": [
                                {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "Bajaj", "options": "i"}},
                                "Bajaj BM 125 / Bajaj CT 125",
                                {"$ifNull": ["$brand_model", "Unknown"]}
                            ]
                        }
                    ]
                },
                "age_group": {
                    "$let": {
                        "vars": {
                            "m_val": {"$trim": {"input": {"$ifNull": ["$user_age_group", {"$ifNull": ["$full_data.M", ""]}]}}}
                        },
                        "in": {
                            "$cond": [
                                {"$ne": ["$$m_val", ""]},
                                "$$m_val",
                                {
                                    "$switch": {
                                        "branches": [
                                            {"case": {"$lt": ["$user_age", 20]}, "then": "Less than 20"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 20]}, {"$lt": ["$user_age", 30]}]}, "then": "20-30"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 30]}, {"$lt": ["$user_age", 40]}]}, "then": "30-40"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 40]}, {"$lt": ["$user_age", 50]}]}, "then": "40-50"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 50]}, {"$lt": ["$user_age", 60]}]}, "then": "50-60"}
                                        ],
                                        "default": None
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        },
        {"$match": {"age_group": {"$in": AGE_GROUPS}, "brand": {"$in": BRANDS}}},
        {
            "$group": {
                "_id": {"brand": "$brand", "category": "$age_group"},
                "count": {"$sum": 1}
            }
        }
    ]

    age_results = await SurveyResponse.aggregate(age_group_pipeline).to_list(length=1000)
    
    age_counts = {b: {c: 0 for c in AGE_GROUPS} for b in BRANDS}
    age_brand_totals = {b: 0 for b in BRANDS}
    for r in age_results:
        b = r["_id"]["brand"]
        cat = r["_id"]["category"]
        cnt = r["count"]
        if b in BRANDS and cat in AGE_GROUPS:
            age_counts[b][cat] = cnt
            age_brand_totals[b] += cnt

    age_table = []
    age_chart = []
    for cat in AGE_GROUPS:
        row = {"category": cat}
        for b in BRANDS:
            cnt = age_counts[b][cat]
            total = age_brand_totals[b]
            row[b] = cnt
            row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        row["total"] = sum(age_counts[b][cat] for b in BRANDS)
        age_table.append(row)

        chart_row = {"category": cat}
        for b in BRANDS:
            cnt = age_counts[b][cat]
            total = age_brand_totals[b]
            chart_row[f"{b}_count"] = cnt
            chart_row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        age_chart.append(chart_row)

    age_grand = {"category": "Grand Total"}
    for b in BRANDS:
        age_grand[b] = age_brand_totals[b]
        age_grand[f"{b}_pct"] = 100.0 if age_brand_totals[b] else 0
    age_grand["total"] = sum(age_brand_totals[b] for b in BRANDS)
    age_table.append(age_grand)

    age_group_data = {
        "categories": AGE_GROUPS,
        "category_header": "Age Group",
        "brands": BRANDS,
        "table": age_table,
        "chart": age_chart
    }

    # ── 2. % of People Based on Age Group and City ────────────────
    age_city_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {
                    "$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "TVS|HLX", "options": "i"}},
                        "TVS HLX 125",
                        {
                            "$cond": [
                                {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "Bajaj", "options": "i"}},
                                "Bajaj BM 125 / Bajaj CT 125",
                                {"$ifNull": ["$brand_model", "Unknown"]}
                            ]
                        }
                    ]
                },
                "city": {"$trim": {"input": {"$ifNull": ["$survey_location", ""]}}},
                "age_group": {
                    "$let": {
                        "vars": {
                            "m_val": {"$trim": {"input": {"$ifNull": ["$user_age_group", {"$ifNull": ["$full_data.M", ""]}]}}}
                        },
                        "in": {
                            "$cond": [
                                {"$ne": ["$$m_val", ""]},
                                "$$m_val",
                                {
                                    "$switch": {
                                        "branches": [
                                            {"case": {"$lt": ["$user_age", 20]}, "then": "Less than 20"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 20]}, {"$lt": ["$user_age", 30]}]}, "then": "20-30"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 30]}, {"$lt": ["$user_age", 40]}]}, "then": "30-40"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 40]}, {"$lt": ["$user_age", 50]}]}, "then": "40-50"},
                                            {"case": {"$and": [{"$gte": ["$user_age", 50]}, {"$lt": ["$user_age", 60]}]}, "then": "50-60"}
                                        ],
                                        "default": None
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        },
        {
            "$match": {
                "brand": {"$in": BRANDS},
                "city": {"$ne": "", "$type": "string"},
                "age_group": {"$in": AGE_GROUPS}
            }
        },
        {
            "$group": {
                "_id": {
                    "city": "$city",
                    "age_group": "$age_group",
                    "brand": "$brand"
                },
                "count": {"$sum": 1}
            }
        }
    ]

    age_city_results = await SurveyResponse.aggregate(age_city_pipeline).to_list(length=2000)
    
    cities = sorted(list(set(r["_id"]["city"] for r in age_city_results if r["_id"]["city"])))
    
    city_counts = {}
    city_brand_totals = {}
    overall_brand_totals = {b: 0 for b in BRANDS}

    for city in cities:
        city_counts[city] = {ag: {b: 0 for b in BRANDS} for ag in AGE_GROUPS}
        city_brand_totals[city] = {b: 0 for b in BRANDS}

    for r in age_city_results:
        city = r["_id"]["city"]
        ag = r["_id"]["age_group"]
        b = r["_id"]["brand"]
        cnt = r["count"]

        if city in city_counts and ag in city_counts[city] and b in BRANDS:
            city_counts[city][ag][b] = cnt
            city_brand_totals[city][b] += cnt
            overall_brand_totals[b] += cnt

    age_city_table = []
    age_city_chart = []
    age_city_categories = []

    for city in cities:
        has_data = any(city_brand_totals[city][b] > 0 for b in BRANDS)
        if not has_data:
            continue
        for ag in AGE_GROUPS:
            cat_label = f"{city}|{ag}"
            age_city_categories.append(cat_label)

            row = {"category": cat_label}
            for b in BRANDS:
                cnt = city_counts[city][ag][b]
                city_total = city_brand_totals[city][b]
                row[b] = cnt
                row[f"{b}_pct"] = round((cnt / city_total * 100), 1) if city_total else 0
            row["total"] = sum(city_counts[city][ag][b] for b in BRANDS)
            age_city_table.append(row)

            chart_row = {"category": cat_label}
            for b in BRANDS:
                cnt = city_counts[city][ag][b]
                city_total = city_brand_totals[city][b]
                chart_row[f"{b}_count"] = cnt
                chart_row[f"{b}_pct"] = round((cnt / city_total * 100), 1) if city_total else 0
            age_city_chart.append(chart_row)

    age_city_grand = {"category": "Grand Total"}
    for b in BRANDS:
        age_city_grand[b] = overall_brand_totals[b]
        age_city_grand[f"{b}_pct"] = 100.0 if overall_brand_totals[b] else 0
    age_city_grand["total"] = sum(overall_brand_totals[b] for b in BRANDS)
    age_city_table.append(age_city_grand)

    age_city_data = {
        "categories": age_city_categories,
        "category_header": "City & Age Group",
        "brands": BRANDS,
        "table": age_city_table,
        "chart": age_city_chart
    }

    # ── 3. Mode of Purchase ───────────────────────────────────────
    mode_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {
                    "$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "TVS|HLX", "options": "i"}},
                        "TVS HLX 125",
                        {
                            "$cond": [
                                {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "Bajaj", "options": "i"}},
                                "Bajaj BM 125 / Bajaj CT 125",
                                {"$ifNull": ["$brand_model", "Unknown"]}
                            ]
                        }
                    ]
                },
                "mode": {
                    "$let": {
                        "vars": {
                            "m_raw": {"$trim": {"input": {"$toLower": {"$ifNull": ["$mode_of_purchase", ""]}}}}
                        },
                        "in": {
                            "$cond": [
                                {"$in": ["$$m_raw", ["new", "brand new"]]},
                                "New",
                                {
                                    "$cond": [
                                        {"$in": ["$$m_raw", ["second hand", "secondhand", "used", "old"]]},
                                        "Second Hand",
                                        None
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        },
        {"$match": {"brand": {"$in": BRANDS}, "mode": {"$in": ["New", "Second Hand"]}}},
        {
            "$group": {
                "_id": {"brand": "$brand", "category": "$mode"},
                "count": {"$sum": 1}
            }
        }
    ]

    mode_results = await SurveyResponse.aggregate(mode_pipeline).to_list(length=1000)
    MODES = ["New", "Second Hand"]
    mode_counts = {b: {m: 0 for m in MODES} for b in BRANDS}
    mode_brand_totals = {b: 0 for b in BRANDS}

    for r in mode_results:
        b = r["_id"]["brand"]
        cat = r["_id"]["category"]
        cnt = r["count"]
        if b in BRANDS and cat in MODES:
            mode_counts[b][cat] = cnt
            mode_brand_totals[b] += cnt

    mode_table = []
    mode_chart = []
    for cat in MODES:
        row = {"category": cat}
        for b in BRANDS:
            cnt = mode_counts[b][cat]
            total = mode_brand_totals[b]
            row[b] = cnt
            row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        row["total"] = sum(mode_counts[b][cat] for b in BRANDS)
        mode_table.append(row)

        chart_row = {"category": cat}
        for b in BRANDS:
            cnt = mode_counts[b][cat]
            total = mode_brand_totals[b]
            chart_row[f"{b}_count"] = cnt
            chart_row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        mode_chart.append(chart_row)

    mode_grand = {"category": "Grand Total"}
    for b in BRANDS:
        mode_grand[b] = mode_brand_totals[b]
        mode_grand[f"{b}_pct"] = 100.0 if mode_brand_totals[b] else 0
    mode_grand["total"] = sum(mode_brand_totals[b] for b in BRANDS)
    mode_table.append(mode_grand)

    mode_of_purchase_data = {
        "categories": MODES,
        "category_header": "Mode of Purchase",
        "brands": BRANDS,
        "table": mode_table,
        "chart": mode_chart
    }

    # ── 4. Ownership ─────────────────────────────────────────────
    ownership_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {
                    "$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "TVS|HLX", "options": "i"}},
                        "TVS HLX 125",
                        {
                            "$cond": [
                                {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "Bajaj", "options": "i"}},
                                "Bajaj BM 125 / Bajaj CT 125",
                                {"$ifNull": ["$brand_model", "Unknown"]}
                            ]
                        }
                    ]
                },
                "owner": {
                    "$let": {
                        "vars": {
                            "o_raw": {"$trim": {"input": {"$toLower": {"$ifNull": ["$ownership", ""]}}}}
                        },
                        "in": {
                            "$cond": [
                                {"$in": ["$$o_raw", ["own", "owned", "self"]]},
                                "Own",
                                {
                                    "$cond": [
                                        {"$in": ["$$o_raw", ["hired", "rent", "rented", "rental"]]},
                                        "Hired (Rent)",
                                        None
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        },
        {"$match": {"brand": {"$in": BRANDS}, "owner": {"$in": ["Own", "Hired (Rent)"]}}},
        {
            "$group": {
                "_id": {"brand": "$brand", "category": "$owner"},
                "count": {"$sum": 1}
            }
        }
    ]

    ownership_results = await SurveyResponse.aggregate(ownership_pipeline).to_list(length=1000)
    OWNERSHIPS = ["Own", "Hired (Rent)"]
    ownership_counts = {b: {o: 0 for o in OWNERSHIPS} for b in BRANDS}
    ownership_brand_totals = {b: 0 for b in BRANDS}

    for r in ownership_results:
        b = r["_id"]["brand"]
        cat = r["_id"]["category"]
        cnt = r["count"]
        if b in BRANDS and cat in OWNERSHIPS:
            ownership_counts[b][cat] = cnt
            ownership_brand_totals[b] += cnt

    ownership_table = []
    ownership_chart = []
    for cat in OWNERSHIPS:
        row = {"category": cat}
        for b in BRANDS:
            cnt = ownership_counts[b][cat]
            total = ownership_brand_totals[b]
            row[b] = cnt
            row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        row["total"] = sum(ownership_counts[b][cat] for b in BRANDS)
        ownership_table.append(row)

        chart_row = {"category": cat}
        for b in BRANDS:
            cnt = ownership_counts[b][cat]
            total = ownership_brand_totals[b]
            chart_row[f"{b}_count"] = cnt
            chart_row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        ownership_chart.append(chart_row)

    ownership_grand = {"category": "Grand Total"}
    for b in BRANDS:
        ownership_grand[b] = ownership_brand_totals[b]
        ownership_grand[f"{b}_pct"] = 100.0 if ownership_brand_totals[b] else 0
    ownership_grand["total"] = sum(ownership_brand_totals[b] for b in BRANDS)
    ownership_table.append(ownership_grand)

    ownership_data = {
        "categories": OWNERSHIPS,
        "category_header": "Ownership Type",
        "brands": BRANDS,
        "table": ownership_table,
        "chart": ownership_chart
    }

    # ── 5. User Profession ────────────────────────────────────────
    profession_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {
                    "$cond": [
                        {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "TVS|HLX", "options": "i"}},
                        "TVS HLX 125",
                        {
                            "$cond": [
                                {"$regexMatch": {"input": {"$ifNull": ["$brand_model", ""]}, "regex": "Bajaj", "options": "i"}},
                                "Bajaj BM 125 / Bajaj CT 125",
                                {"$ifNull": ["$brand_model", "Unknown"]}
                            ]
                        }
                    ]
                },
                "raw_prof": {"$trim": {"input": {"$ifNull": ["$full_data.N", ""]}}}
            }
        },
        {"$match": {"brand": {"$in": BRANDS}, "raw_prof": {"$ne": ""}}},
        {
            "$group": {
                "_id": {"brand": "$brand", "profession": "$raw_prof"},
                "count": {"$sum": 1}
            }
        }
    ]

    prof_results = await SurveyResponse.aggregate(profession_pipeline).to_list(length=1000)

    def normalize_prof(val):
        if not val:
            return "Others"
        v = str(val).strip()
        vl = v.lower()
        if "taxi" in vl or "taxu" in vl or "drivet" in vl or "ryder" in vl:
            return "Taxi driver"
        if "business" in vl:
            return "Business"
        if "trader" in vl:
            return "Trader"
        if "banker" in vl:
            return "Banker"
        if "baker" in vl:
            return "Baker"
        if "student" in vl:
            return "Student"
        return v.title()

    prof_counts = {b: defaultdict(int) for b in BRANDS}
    prof_totals_overall = defaultdict(int)
    prof_brand_totals = {b: 0 for b in BRANDS}

    for r in prof_results:
        b = r["_id"]["brand"]
        raw = r["_id"]["profession"]
        cnt = r["count"]

        if b in BRANDS and raw:
            norm = normalize_prof(raw)
            prof_counts[b][norm] += cnt
            prof_totals_overall[norm] += cnt
            prof_brand_totals[b] += cnt

    sorted_profs = sorted(prof_totals_overall.items(), key=lambda x: -x[1])
    top_5 = [p for p, _ in sorted_profs[:5]]
    categories = top_5 + ["Others"]

    final_prof_counts = {b: {p: 0 for p in categories} for b in BRANDS}
    for b in BRANDS:
        for p, cnt in prof_counts[b].items():
            if p in top_5:
                final_prof_counts[b][p] += cnt
            else:
                final_prof_counts[b]["Others"] += cnt

    prof_table = []
    prof_chart = []
    grand_total_overall = sum(prof_brand_totals[b] for b in BRANDS)

    for cat in categories:
        row = {"category": cat}
        for b in BRANDS:
            cnt = final_prof_counts[b][cat]
            total = prof_brand_totals[b]
            pct = round((cnt / total * 100), 1) if total else 0
            row[b] = pct
            row[f"{b}_pct"] = pct
            row[f"{b}_count"] = cnt
        cat_total_cnt = sum(final_prof_counts[b][cat] for b in BRANDS)
        row["total"] = round((cat_total_cnt / grand_total_overall * 100), 1) if grand_total_overall else 0
        prof_table.append(row)

        chart_row = {"category": cat}
        for b in BRANDS:
            cnt = final_prof_counts[b][cat]
            total = prof_brand_totals[b]
            chart_row[f"{b}_count"] = cnt
            chart_row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        prof_chart.append(chart_row)

    prof_grand = {"category": "Grand Total"}
    for b in BRANDS:
        prof_grand[b] = 100.0
        prof_grand[f"{b}_pct"] = 100.0
        prof_grand[f"{b}_count"] = prof_brand_totals[b]
    prof_grand["total"] = 100.0
    prof_table.append(prof_grand)

    profession_data = {
        "categories": categories,
        "category_header": "Profession",
        "brands": BRANDS,
        "table": prof_table,
        "chart": prof_chart
    }

    return {
        "age_group": age_group_data,
        "age_city": age_city_data,
        "mode_of_purchase": mode_of_purchase_data,
        "ownership": ownership_data,
        "profession": profession_data,
    }


@router.get("/age-distribution")
async def get_age_distribution(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    res = await dashboard_analytics(file_id, region_id, country_id, ib_version_id)
    return res["age_group"]


@router.get("/age-city-brand")
async def get_age_city_brand(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    res = await dashboard_analytics(file_id, region_id, country_id, ib_version_id)
    return res["age_city"]


@router.get("/purchase-ownership")
async def get_purchase_ownership(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    res = await dashboard_analytics(file_id, region_id, country_id, ib_version_id)
    return {
        "mode_of_purchase": res["mode_of_purchase"],
        "ownership": res["ownership"]
    }


@router.get("/profession-distribution")
async def get_profession_distribution(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    res = await dashboard_analytics(file_id, region_id, country_id, ib_version_id)
    return res["profession"]
