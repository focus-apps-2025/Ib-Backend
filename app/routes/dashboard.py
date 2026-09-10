import re
from fastapi import APIRouter, Depends
from typing import Optional, Any, List, Dict

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


async def _build_full_query(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
):
    """Build full MongoDB query incorporating file_id, brand, location, dates, search."""
    query = await _build_file_query(file_id, region_id, country_id, ib_version_id)
    if brand_model and brand_model != "All Brands":
        query["brand_model"] = {"$regex": f"^{re.escape(brand_model)}$", "$options": "i"}
    if survey_location:
        query["survey_location"] = {"$regex": survey_location, "$options": "i"}
    if date_from:
        query["survey_date"] = {"$gte": date_from}
    if date_to:
        if "survey_date" in query:
            query["survey_date"]["$lte"] = date_to
        else:
            query["survey_date"] = {"$lte": date_to}
    if search:
        query["$or"] = [
            {"brand_model": {"$regex": search, "$options": "i"}},
            {"survey_location": {"$regex": search, "$options": "i"}},
        ]
    return query


@router.get("/top-issues-by-nps")
async def get_top_issues_by_nps(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get top 10 issues per NPS category (Promoters = Yes, Passives = Maybe, Detractors = No).
    """
    from app.models.survey_response import SurveyResponse

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    pipeline = [
        {"$match": {**query, "recommend_category": {"$in": ["Yes", "Maybe", "No"]}}},
        {"$project": {"recommend_category": 1, "complaint_groups": 1}},
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
                    "category": "$recommend_category",
                    "issue": "$complaint_groups"
                },
                "count": {"$sum": 1}
            }
        }
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    counts_by_cat = {"Yes": {}, "Maybe": {}, "No": {}}
    total_by_cat = {"Yes": 0, "Maybe": 0, "No": 0}

    for r in results:
        cat = r["_id"]["category"]
        issue = r["_id"]["issue"]
        cnt = r["count"]
        if cat in counts_by_cat and issue and issue != "Blank":
            counts_by_cat[cat][issue] = cnt
            total_by_cat[cat] += cnt

    def build_top(cat_key: str):
        cat_counts = counts_by_cat[cat_key]
        tot = total_by_cat[cat_key]
        sorted_issues = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        return [
            {
                "issue": issue,
                "count": count,
                "percentage": round((count / tot * 100), 1) if tot > 0 else 0
            }
            for issue, count in sorted_issues
        ]

    return {
        "promoters": {"issues": build_top("Yes")},
        "passives": {"issues": build_top("Maybe")},
        "detractors": {"issues": build_top("No")},
    }


@router.get("/top-passive-topics-by-nps")
async def get_top_passive_topics_by_nps(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get top 10 passive (good) topics per NPS category (Promoters = Yes, Passives = Maybe, Detractors = No).
    """
    from app.models.survey_response import SurveyResponse

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    pipeline = [
        {"$match": {**query, "recommend_category": {"$in": ["Yes", "Maybe", "No"]}}},
        {
            "$project": {
                "recommend_category": 1,
                "passive_entries": {
                    "$objectToArray": {"$ifNull": ["$passive_data", {}]}
                }
            }
        },
        {"$unwind": "$passive_entries"},
        {
            "$project": {
                "recommend_category": 1,
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
                                        "options": "i"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "category": "$recommend_category",
                    "topic": "$topic"
                },
                "count": {"$sum": "$count"}
            }
        }
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    counts_by_cat = {"Yes": {}, "Maybe": {}, "No": {}}
    total_by_cat = {"Yes": 0, "Maybe": 0, "No": 0}

    for r in results:
        cat = r["_id"]["category"]
        topic = r["_id"]["topic"]
        cnt = r["count"]
        if cat in counts_by_cat and topic and cnt > 0 and topic != "Blank":
            counts_by_cat[cat][topic] = cnt
            total_by_cat[cat] += cnt

    def build_top(cat_key: str):
        cat_counts = counts_by_cat[cat_key]
        tot = total_by_cat[cat_key]
        sorted_topics = sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        return [
            {
                "topic": topic,
                "count": count,
                "percentage": round((count / tot * 100), 1) if tot > 0 else 0
            }
            for topic, count in sorted_topics
        ]

    return {
        "promoters": {"topics": build_top("Yes")},
        "passives": {"topics": build_top("Maybe")},
        "detractors": {"topics": build_top("No")},
    }


@router.get("/brand-nps-feedback")
async def get_brand_nps_feedback(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get per-brand NPS-segmented feedback for:
    - Overall
    - Promoters (Yes)
    - Passives (Maybe)
    - Detractors (No)
    Returns total respondent base, top 10 passive topics, and top 10 issues for each brand and category.
    """
    from app.models.survey_response import SurveyResponse
    from collections import defaultdict

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    raw_brands = await SurveyResponse.distinct("brand_model", filter=query if query else None)
    BRANDS = sorted(set(clean_brand_name(b) for b in raw_brands if b and b != "Blank"))

    # Pipeline for Issues per brand and NPS category
    issues_pipeline = [
        {"$match": {**query, "brand_model": {"$in": raw_brands}}},
        {"$project": {
            "brand": "$brand_model",
            "category": {"$ifNull": ["$recommend_category", "Unknown"]},
            "complaint_groups": 1
        }},
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
                    "brand": "$brand",
                    "category": "$category",
                    "issue": "$complaint_groups"
                },
                "count": {"$sum": 1}
            }
        }
    ]
    issues_results = await SurveyResponse.aggregate(issues_pipeline).to_list(length=None)

    # Pipeline for Passive Topics per brand and NPS category
    passive_pipeline = [
        {"$match": {**query, "brand_model": {"$in": raw_brands}}},
        {
            "$project": {
                "brand": "$brand_model",
                "category": {"$ifNull": ["$recommend_category", "Unknown"]},
                "passive_entries": {
                    "$objectToArray": {"$ifNull": ["$passive_data", {}]}
                }
            }
        },
        {"$unwind": "$passive_entries"},
        {
            "$project": {
                "brand": 1,
                "category": 1,
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
                                        "options": "i"
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": {
                    "brand": "$brand",
                    "category": "$category",
                    "topic": "$topic"
                },
                "count": {"$sum": "$count"}
            }
        }
    ]
    passive_results = await SurveyResponse.aggregate(passive_pipeline).to_list(length=None)

    # Pipeline for Respondent Bases per brand and category
    base_pipeline = [
        {"$match": {**query, "brand_model": {"$in": raw_brands}}},
        {
            "$group": {
                "_id": {
                    "brand": "$brand_model",
                    "category": "$recommend_category"
                },
                "count": {"$sum": 1}
            }
        }
    ]
    base_results = await SurveyResponse.aggregate(base_pipeline).to_list(length=None)

    # Aggregate base counts
    brand_bases = defaultdict(lambda: {"overall": 0, "Yes": 0, "Maybe": 0, "No": 0})
    for r in base_results:
        b = clean_brand_name(r["_id"]["brand"])
        cat = r["_id"]["category"]
        cnt = r["count"]
        brand_bases[b]["overall"] += cnt
        if cat in ["Yes", "Maybe", "No"]:
            brand_bases[b][cat] += cnt

    # Aggregate Issues
    brand_issues = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in issues_results:
        b = clean_brand_name(r["_id"]["brand"])
        cat = r["_id"]["category"]
        issue = r["_id"]["issue"]
        cnt = r["count"]
        if issue and issue != "Blank":
            brand_issues[b]["overall"][issue] += cnt
            if cat in ["Yes", "Maybe", "No"]:
                brand_issues[b][cat][issue] += cnt

    # Aggregate Passive Topics
    brand_topics = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in passive_results:
        b = clean_brand_name(r["_id"]["brand"])
        cat = r["_id"]["category"]
        topic = r["_id"]["topic"]
        cnt = r["count"]
        if topic and topic != "Blank" and cnt > 0:
            brand_topics[b]["overall"][topic] += cnt
            if cat in ["Yes", "Maybe", "No"]:
                brand_topics[b][cat][topic] += cnt

    CAT_MAP = {
        "overall": "overall",
        "Yes": "promoters",
        "Maybe": "passives",
        "No": "detractors"
    }

    output_brands = []
    for b in BRANDS:
        bases = brand_bases[b]
        categories_data = {}
        for cat_code, cat_name in CAT_MAP.items():
            base_val = bases[cat_code]
            
            top_topics_dict = brand_topics[b][cat_code]
            sorted_topics = sorted(top_topics_dict.items(), key=lambda x: x[1], reverse=True)[:25]
            topics_list = []
            for t, cnt in sorted_topics:
                if cat_code == "overall":
                    pct = round((cnt / base_val * 100), 1) if base_val > 0 else 0
                else:
                    tot_t = brand_topics[b]["overall"].get(t, cnt)
                    pct = round((cnt / tot_t * 100), 1) if tot_t > 0 else 0
                topics_list.append({
                    "topic": t,
                    "count": cnt,
                    "percentage": pct
                })

            top_issues_dict = brand_issues[b][cat_code]
            sorted_issues = sorted(top_issues_dict.items(), key=lambda x: x[1], reverse=True)[:25]
            issues_list = []
            for i, cnt in sorted_issues:
                if cat_code == "overall":
                    pct = round((cnt / base_val * 100), 1) if base_val > 0 else 0
                else:
                    tot_i = brand_issues[b]["overall"].get(i, cnt)
                    pct = round((cnt / tot_i * 100), 1) if tot_i > 0 else 0
                issues_list.append({
                    "issue": i,
                    "count": cnt,
                    "percentage": pct
                })

            categories_data[cat_name] = {
                "base": base_val,
                "topics": topics_list,
                "issues": issues_list
            }

        output_brands.append({
            "brand": b,
            "categories": categories_data
        })

    return {"brands": output_brands}



@router.get("/service-frequency")
async def get_service_frequency(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get Service Frequency analysis for:
    - KMS Frequency (Column BQ)
    - Time Frequency (Column BP)
    Includes total counts, percentages, and brand-wise breakdowns.
    """
    from app.models.survey_response import SurveyResponse
    from collections import defaultdict
    import re

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": "$brand_model",
                "kms_val": {"$ifNull": ["$service_freq_kms", "$full_data.BQ"]},
                "time_val": {"$ifNull": ["$service_freq_time", "$full_data.BP"]}
            }
        }
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    def is_valid_freq(val: Any) -> bool:
        if val is None:
            return False
        s = str(val).strip()
        if not s or s.lower() in ("blank", "nan", "none", "null", "-", "...."):
            return False
        if re.match(r"^submit\s?form", s, re.I):
            return False
        return True

    kms_counts = defaultdict(int)
    kms_brand_counts = defaultdict(lambda: defaultdict(int))
    kms_brand_totals = defaultdict(int)
    total_kms_responses = 0

    time_counts = defaultdict(int)
    time_brand_counts = defaultdict(lambda: defaultdict(int))
    time_brand_totals = defaultdict(int)
    total_time_responses = 0

    for r in results:
        b = clean_brand_name(r.get("brand"))
        
        kms_v = r.get("kms_val")
        if is_valid_freq(kms_v):
            kms_str = str(kms_v).strip()
            kms_counts[kms_str] += 1
            kms_brand_counts[b][kms_str] += 1
            kms_brand_totals[b] += 1
            total_kms_responses += 1

        time_v = r.get("time_val")
        if is_valid_freq(time_v):
            time_str = str(time_v).strip()
            time_counts[time_str] += 1
            time_brand_counts[b][time_str] += 1
            time_brand_totals[b] += 1
            total_time_responses += 1

    def extract_num(s: str) -> float:
        m = re.search(r"(\d+(?:\.\d+)?)", s)
        return float(m.group(1)) if m else 999999.0

    sorted_kms = sorted(kms_counts.items(), key=lambda x: extract_num(x[0]))
    kms_categories = [
        {
            "category": cat,
            "count": cnt,
            "percentage": round((cnt / total_kms_responses * 100), 1) if total_kms_responses > 0 else 0.0
        }
        for cat, cnt in sorted_kms
    ]

    kms_brand_breakdown = []
    for b in sorted(kms_brand_totals.keys()):
        b_total = kms_brand_totals[b]
        b_cats = [
            {
                "category": cat,
                "count": cnt,
                "percentage": round((cnt / b_total * 100), 1) if b_total > 0 else 0.0
            }
            for cat, cnt in sorted(kms_brand_counts[b].items(), key=lambda x: extract_num(x[0]))
        ]
        kms_brand_breakdown.append({
            "brand": b,
            "total": b_total,
            "categories": b_cats
        })

    sorted_time = sorted(time_counts.items(), key=lambda x: extract_num(x[0]))
    time_categories = [
        {
            "category": cat,
            "count": cnt,
            "percentage": round((cnt / total_time_responses * 100), 1) if total_time_responses > 0 else 0.0
        }
        for cat, cnt in sorted_time
    ]

    time_brand_breakdown = []
    for b in sorted(time_brand_totals.keys()):
        b_total = time_brand_totals[b]
        b_cats = [
            {
                "category": cat,
                "count": cnt,
                "percentage": round((cnt / b_total * 100), 1) if b_total > 0 else 0.0
            }
            for cat, cnt in sorted(time_brand_counts[b].items(), key=lambda x: extract_num(x[0]))
        ]
        time_brand_breakdown.append({
            "brand": b,
            "total": b_total,
            "categories": b_cats
        })

    return {
        "kms_frequency": {
            "total_responses": total_kms_responses,
            "categories": kms_categories,
            "brand_breakdown": kms_brand_breakdown
        },
        "time_frequency": {
            "total_responses": total_time_responses,
            "categories": time_categories,
            "brand_breakdown": time_brand_breakdown
        }
    }


@router.get("/service-nps")
async def get_service_nps(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get Service NPS Analysis for:
    - Column BN: Workshop Type ("Authorized Workshop" vs "PGM (Private Garage Mechanic)")
    - Column BR: Recommendation ("Yes" vs "No")
    - Column BS: NPS Score (0-10 scale: 9-10 Promoters, 7-8 Passives, 0-6 Detractors)
    Returns separate metrics & brand breakdowns for Authorized Workshop and PGM.
    """
    from app.models.survey_response import SurveyResponse
    from collections import defaultdict
    import re

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": "$brand_model",
                "nps_score_field": "$nps_score",
                "workshop_val": {
                    "$ifNull": [
                        "$service_workshop_type",
                        "$full_data.BN",
                        "$full_data.Q1-1 WHERE DO YOU GET YOUR VEHICLE SERVICED?"
                    ]
                },
                "recommend_val": {
                    "$ifNull": [
                        "$service_recommend",
                        "$full_data.BR",
                        "$full_data.A1. Will you recommend / tell / advise your friends or family members for servicing their vehicle at Authorized Service workshop / Authorized Dealer?"
                    ]
                },
                "nps_val": {
                    "$ifNull": [
                        "$service_nps_score",
                        "$full_data.BS"
                    ]
                }
            }
        }
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    def parse_workshop(val: Any) -> Optional[str]:
        if val is None:
            return None
        s = str(val).strip().lower()
        if not s or s in ("blank", "nan", "none", "null", "-", "....") or re.match(r"^submit\s?form", s):
            return None
        if "authorized" in s or "dealer" in s:
            return "authorized"
        if "pgm" in s or "private" in s or "garage" in s or "mechanic" in s:
            return "pgm"
        return None

    def parse_nps_category(score_val: Any, nps_field: Any) -> Optional[str]:
        if score_val is not None:
            try:
                s_num = float(score_val)
                if 9.0 <= s_num <= 10.0:
                    return "promoter"
                elif 7.0 <= s_num <= 8.99:
                    return "passive"
                elif 0.0 <= s_num <= 6.99:
                    return "detractor"
            except (ValueError, TypeError):
                pass
            
            s_str = str(score_val).strip().lower()
            if s_str in ("yes", "promoter", "definitely recommend", "1"):
                return "promoter"
            elif s_str in ("may be", "maybe", "passive", "less likely recommend", "more likely recommend"):
                return "passive"
            elif s_str in ("no", "detractor", "will not at all recommend", "0"):
                return "detractor"

        if nps_field is not None:
            try:
                s_num = float(nps_field)
                if 9.0 <= s_num <= 10.0:
                    return "promoter"
                elif 7.0 <= s_num <= 8.99:
                    return "passive"
                elif 0.0 <= s_num <= 6.99:
                    return "detractor"
            except (ValueError, TypeError):
                pass

        return None

    def parse_recommend(val: Any, cat_val: Optional[str]) -> Optional[str]:
        if val is not None:
            s = str(val).strip().lower()
            if not s or s in ("blank", "nan", "none", "null", "-"):
                pass
            elif s.startswith("yes") or s == "1" or s == "promoter":
                return "Yes"
            elif s.startswith("no") or s == "0" or "not" in s:
                return "No"
        if cat_val in ("promoter", "passive"):
            return "Yes"
        if cat_val == "detractor":
            return "No"
        return None

    def get_numeric_score(score_val: Any, nps_field: Any, cat_val: Optional[str]) -> Optional[float]:
        if score_val is not None:
            try:
                s_num = float(score_val)
                if 0.0 <= s_num <= 10.0:
                    return s_num
            except (ValueError, TypeError):
                pass
        if nps_field is not None:
            try:
                s_num = float(nps_field)
                if 0.0 <= s_num <= 10.0:
                    return s_num
            except (ValueError, TypeError):
                pass
        if cat_val == "promoter":
            return 9.5
        elif cat_val == "passive":
            return 7.5
        elif cat_val == "detractor":
            return 3.0
        return None

    def init_group():
        return {
            "total": 0,
            "recommend": defaultdict(int),
            "nps_cat": defaultdict(int),
            "scores": [],
            "brands": defaultdict(lambda: {
                "total": 0,
                "recommend": defaultdict(int),
                "nps_cat": defaultdict(int),
                "scores": []
            })
        }

    groups = {
        "authorized": init_group(),
        "pgm": init_group()
    }

    for r in results:
        b = clean_brand_name(r.get("brand"))
        w_type = parse_workshop(r.get("workshop_val"))
        if not w_type or w_type not in groups:
            continue

        grp = groups[w_type]
        grp["total"] += 1
        grp["brands"][b]["total"] += 1

        cat = parse_nps_category(r.get("nps_val"), r.get("nps_score_field"))
        rec = parse_recommend(r.get("recommend_val"), cat)
        if rec:
            grp["recommend"][rec] += 1
            grp["brands"][b]["recommend"][rec] += 1

        num_score = get_numeric_score(r.get("nps_val"), r.get("nps_score_field"), cat)
        if num_score is not None:
            grp["scores"].append(num_score)
            grp["brands"][b]["scores"].append(num_score)

        if cat:
            grp["nps_cat"][cat] += 1
            grp["brands"][b]["nps_cat"][cat] += 1

    def format_group_result(grp_data: dict) -> dict:
        total_resp = grp_data["total"]

        rec_yes = grp_data["recommend"]["Yes"]
        rec_no = grp_data["recommend"]["No"]
        rec_total = rec_yes + rec_no
        rec_yes_pct = round((rec_yes / rec_total * 100), 1) if rec_total > 0 else 0.0
        rec_no_pct = round((rec_no / rec_total * 100), 1) if rec_total > 0 else 0.0

        prom = grp_data["nps_cat"]["promoter"]
        passiv = grp_data["nps_cat"]["passive"]
        detr = grp_data["nps_cat"]["detractor"]
        nps_total = len(grp_data["scores"])

        prom_pct = round((prom / nps_total * 100), 1) if nps_total > 0 else 0.0
        passiv_pct = round((passiv / nps_total * 100), 1) if nps_total > 0 else 0.0
        detr_pct = round((detr / nps_total * 100), 1) if nps_total > 0 else 0.0

        net_nps = round(prom_pct - detr_pct, 1)
        avg_score = round(sum(grp_data["scores"]) / nps_total, 1) if nps_total > 0 else 0.0

        brand_breakdown = []
        for brand_name in sorted(grp_data["brands"].keys()):
            b_data = grp_data["brands"][brand_name]
            b_total = b_data["total"]

            b_rec_yes = b_data["recommend"]["Yes"]
            b_rec_no = b_data["recommend"]["No"]
            b_rec_total = b_rec_yes + b_rec_no
            b_rec_yes_pct = round((b_rec_yes / b_rec_total * 100), 1) if b_rec_total > 0 else 0.0
            b_rec_no_pct = round((b_rec_no / b_rec_total * 100), 1) if b_rec_total > 0 else 0.0

            b_prom = b_data["nps_cat"]["promoter"]
            b_passiv = b_data["nps_cat"]["passive"]
            b_detr = b_data["nps_cat"]["detractor"]
            b_nps_total = len(b_data["scores"])

            b_prom_pct = round((b_prom / b_nps_total * 100), 1) if b_nps_total > 0 else 0.0
            b_passiv_pct = round((b_passiv / b_nps_total * 100), 1) if b_nps_total > 0 else 0.0
            b_detr_pct = round((b_detr / b_nps_total * 100), 1) if b_nps_total > 0 else 0.0

            b_net_nps = round(b_prom_pct - b_detr_pct, 1)
            b_avg_score = round(sum(b_data["scores"]) / b_nps_total, 1) if b_nps_total > 0 else 0.0

            brand_breakdown.append({
                "brand": brand_name,
                "total_responses": b_total,
                "recommend_yes": b_rec_yes,
                "recommend_no": b_rec_no,
                "recommend_yes_pct": b_rec_yes_pct,
                "recommend_no_pct": b_rec_no_pct,
                "promoters": b_prom,
                "passives": b_passiv,
                "detractors": b_detr,
                "promoters_pct": b_prom_pct,
                "passives_pct": b_passiv_pct,
                "detractors_pct": b_detr_pct,
                "nps_score": b_net_nps,
                "avg_score": b_avg_score
            })

        return {
            "total_responses": total_resp,
            "recommendation": {
                "total": rec_total,
                "yes_count": rec_yes,
                "yes_pct": rec_yes_pct,
                "no_count": rec_no,
                "no_pct": rec_no_pct
            },
            "nps_distribution": {
                "total": nps_total,
                "promoters_count": prom,
                "promoters_pct": prom_pct,
                "passives_count": passiv,
                "passives_pct": passiv_pct,
                "detractors_count": detr,
                "detractors_pct": detr_pct,
                "nps_score": net_nps,
                "avg_score": avg_score
            },
            "brand_breakdown": brand_breakdown
        }

    return {
        "authorized": format_group_result(groups["authorized"]),
        "pgm": format_group_result(groups["pgm"])
    }


@router.get("/service-benefits-betterments")
async def get_service_benefits_betterments(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get Benefits (OI-OU) & Betterments/Issues (OV-PJ) analysis for:
    - Authorized Service Workshop vs PGM (Private Garage Mechanic) (Column BN)
    - Overall Brand-wise Breakdown
    - NPS Segmentation (Promoters 9-10, Passives 7-8, Detractors 0-6) (Column BS)
    """
    from app.models.survey_response import SurveyResponse
    from app.utils.column_mapping import COLUMN_HEADERS_MAP, col_letter_to_index, index_to_col_letter
    from collections import defaultdict
    import re

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": "$brand_model",
                "nps_score_field": "$nps_score",
                "workshop_val": {
                    "$ifNull": [
                        "$service_workshop_type",
                        "$full_data.BN",
                        "$full_data.Q1-1 WHERE DO YOU GET YOUR VEHICLE SERVICED?"
                    ]
                },
                "nps_val": {
                    "$ifNull": [
                        "$service_nps_score",
                        "$full_data.BS"
                    ]
                },
                "full_data": "$full_data"
            }
        }
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    oi_ou_cols = [index_to_col_letter(i) for i in range(col_letter_to_index("OI"), col_letter_to_index("OU") + 1)]
    ov_pj_cols = [index_to_col_letter(i) for i in range(col_letter_to_index("OV"), col_letter_to_index("PJ") + 1)]

    benefit_topics = {
        "OI": "Resolution of Problem is good",
        "OJ": "Parts availability & quality",
        "OK": "Skilled Manpower is available in workshop",
        "OL": "Washing Quality",
        "OM": "Happy with Service Adviser Behaviour",
        "ON": "Cost & Explanation was good",
        "OO": "Easy of Payment Method available",
        "OP": "Warranty Policy is good",
        "OQ": "Waiting Time was adequate",
        "OR": "Satisfied with Customer Lounge Amenities",
        "OS": "Extension of Operating Hours is very supportive",
        "OT": "Workshop Facilities",
        "OU": "Convenience of Location",
    }

    issue_topics = {
        "OV": "Complaints not resolved",
        "OW": "Parts availability issues",
        "OX": "Parts availability issues",
        "OY": "Parts availability issues",
        "OZ": "Improve Skilled Manpower",
        "PA": "Washing Quality issues",
        "PB": "Service Adviser Behaviour issues",
        "PC": "Not satisfied with Cost & Explanation",
        "PD": "Payment Method issues",
        "PE": "Warranty Policy issues",
        "PF": "Waiting Time is more",
        "PG": "Improve Customer Lounge Amenities",
        "PH": "Extend Operating Hours",
        "PI": "Improve Workshop Facilities",
        "PJ": "Convenience of Location issues",
    }

    def parse_workshop(val: Any) -> str:
        if val is None:
            return "authorized"
        s = str(val).strip().lower()
        if "pgm" in s or "private" in s or "garage" in s or "mechanic" in s:
            return "pgm"
        return "authorized"

    def parse_nps_category(score_val: Any, nps_field: Any) -> str:
        if score_val is not None:
            try:
                s_num = float(score_val)
                if 9.0 <= s_num <= 10.0:
                    return "promoter"
                elif 7.0 <= s_num <= 8.99:
                    return "passive"
                elif 0.0 <= s_num <= 6.99:
                    return "detractor"
            except (ValueError, TypeError):
                pass
            s_str = str(score_val).strip().lower()
            if s_str in ("yes", "promoter", "definitely recommend", "1"):
                return "promoter"
            elif s_str in ("may be", "maybe", "passive"):
                return "passive"
            elif s_str in ("no", "detractor", "0"):
                return "detractor"
        if nps_field is not None:
            try:
                s_num = float(nps_field)
                if 9.0 <= s_num <= 10.0:
                    return "promoter"
                elif 7.0 <= s_num <= 8.99:
                    return "passive"
                elif 0.0 <= s_num <= 6.99:
                    return "detractor"
            except (ValueError, TypeError):
                pass
        return "passive"

    def init_section():
        return {
            "total_responses": 0,
            "overall": {
                "benefits": defaultdict(int),
                "issues": defaultdict(int),
                "brand_benefits": defaultdict(lambda: defaultdict(int)),
                "brand_issues": defaultdict(lambda: defaultdict(int)),
            },
            "promoter": {
                "benefits": defaultdict(int),
                "issues": defaultdict(int),
                "brand_benefits": defaultdict(lambda: defaultdict(int)),
                "brand_issues": defaultdict(lambda: defaultdict(int)),
            },
            "passive": {
                "benefits": defaultdict(int),
                "issues": defaultdict(int),
                "brand_benefits": defaultdict(lambda: defaultdict(int)),
                "brand_issues": defaultdict(lambda: defaultdict(int)),
            },
            "detractor": {
                "benefits": defaultdict(int),
                "issues": defaultdict(int),
                "brand_benefits": defaultdict(lambda: defaultdict(int)),
                "brand_issues": defaultdict(lambda: defaultdict(int)),
            },
        }

    sections = {
        "authorized": init_section(),
        "pgm": init_section(),
    }

    for r in results:
        b = clean_brand_name(r.get("brand"))
        w_type = parse_workshop(r.get("workshop_val"))
        nps_cat = parse_nps_category(r.get("nps_val"), r.get("nps_score_field"))
        fd = r.get("full_data") or {}

        sec = sections[w_type]
        sec["total_responses"] += 1

        # Check Benefits (OI-OU)
        for col in oi_ou_cols:
            topic = benefit_topics.get(col, COLUMN_HEADERS_MAP.get(col, col))
            val = fd.get(col) or fd.get(COLUMN_HEADERS_MAP.get(col, ""))
            if not val:
                hdr = COLUMN_HEADERS_MAP.get(col, "")
                if hdr:
                    for k, v in fd.items():
                        if hdr[:25] in k:
                            val = v
                            break
            if val and str(val).strip() and str(val).strip().lower() not in ("nan", "none", "0", "false", "no", "-"):
                sec["overall"]["benefits"][topic] += 1
                sec["overall"]["brand_benefits"][b][topic] += 1
                sec[nps_cat]["benefits"][topic] += 1
                sec[nps_cat]["brand_benefits"][b][topic] += 1

        # Check Issues (OV-PJ)
        for col in ov_pj_cols:
            topic = issue_topics.get(col, COLUMN_HEADERS_MAP.get(col, col))
            val = fd.get(col) or fd.get(COLUMN_HEADERS_MAP.get(col, ""))
            if not val:
                hdr = COLUMN_HEADERS_MAP.get(col, "")
                if hdr:
                    for k, v in fd.items():
                        if hdr[:25] in k:
                            val = v
                            break
            if val and str(val).strip() and str(val).strip().lower() not in ("nan", "none", "0", "false", "no", "-"):
                sec["overall"]["issues"][topic] += 1
                sec["overall"]["brand_issues"][b][topic] += 1
                sec[nps_cat]["issues"][topic] += 1
                sec[nps_cat]["brand_issues"][b][topic] += 1

    def format_sub_analysis(sub_data: dict) -> dict:
        top_b = [
            {"topic": k, "count": v}
            for k, v in sorted(sub_data["benefits"].items(), key=lambda x: x[1], reverse=True)[:25]
        ]
        top_i = [
            {"topic": k, "count": v}
            for k, v in sorted(sub_data["issues"].items(), key=lambda x: x[1], reverse=True)[:25]
        ]
        
        brand_b = {}
        for brand, topic_counts in sub_data["brand_benefits"].items():
            brand_b[brand] = [
                {"topic": k, "count": v}
                for k, v in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:25]
            ]
            
        brand_i = {}
        for brand, topic_counts in sub_data["brand_issues"].items():
            brand_i[brand] = [
                {"topic": k, "count": v}
                for k, v in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)[:25]
            ]

        return {
            "top_benefits": top_b,
            "top_issues": top_i,
            "brand_benefits": brand_b,
            "brand_issues": brand_i,
        }

    def format_section(sec_data: dict) -> dict:
        return {
            "sample_size": sec_data["total_responses"],
            "overall": format_sub_analysis(sec_data["overall"]),
            "promoter": format_sub_analysis(sec_data["promoter"]),
            "passive": format_sub_analysis(sec_data["passive"]),
            "detractor": format_sub_analysis(sec_data["detractor"]),
        }

    return {
        "data": {
            "authorized": format_section(sections["authorized"]),
            "pgm": format_section(sections["pgm"])
        }
    }


@router.get("/brand-comparison")
async def brand_comparison(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Brand-wise comparison between Passive (Good) feedback and Issues (Complaints).
    Returns for each brand: passive_count, issues_count, total_responses.
    """
    from app.models.survey_response import SurveyResponse

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

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

    from app.services.excel_processor import is_junk_value

    # Merge into per-brand structure
    brands = {}
    for r in passive_results:
        brand = r["_id"]["brand"] or "Unknown"
        topic = r["_id"]["topic"] or ""
        if brand == "Blank" or not topic or is_junk_value(topic):
            continue
        brands.setdefault(brand, {"brand": brand, "passive_topics": {}, "issues_topics": {}})
        brands[brand]["passive_topics"][topic] = r["count"]

    for r in issues_results:
        brand = r["_id"]["brand"] or "Unknown"
        topic = r["_id"]["topic"] or ""
        if brand == "Blank" or not topic or is_junk_value(topic):
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
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
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
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
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
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
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
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
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
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
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
            row[b] = cnt
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

    # ── 6. Location & Model wise Sample Sizes (Col D, E, T) ───────
    sample_size_pipeline = [
        {"$match": query},
        {
            "$project": {
                "city": {"$trim": {"input": {"$ifNull": ["$survey_location", {"$ifNull": ["$full_data.D", ""]}]}}},
                "brand_raw": {"$trim": {"input": {"$ifNull": ["$brand_model", {"$ifNull": ["$full_data.E", ""]}]}}},
                "tenure_raw": {"$trim": {"input": {"$ifNull": ["$duration_of_usage", {"$ifNull": ["$full_data.T", ""]}]}}}
            }
        },
        {"$match": {"city": {"$ne": ""}}}
    ]

    sample_size_docs = await SurveyResponse.aggregate(sample_size_pipeline).to_list(length=10000)

    # Extraction Logic for Column T: extract string before '('
    def clean_tenure(val):
        if not val:
            return "3-6 months"
        s = str(val).strip()
        if "(" in s:
            s = s.split("(")[0].strip()
        return s if s else "3-6 months"

    # Extraction Logic for Column E: Brand / Model
    def norm_brand_group(b_raw):
        if not b_raw:
            return "TVS HLX125"
        b_str = str(b_raw).strip()
        b_upper = b_str.upper()
        if "BAJAJ" in b_upper:
            return "Bajaj BM 125 / Bajaj CT 125"
        if "TVS" in b_upper:
            return "TVS HLX125"
        return b_str

    ss_counts = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    ss_cities_set = set()
    ss_brands_set = set()
    ss_tenures_set = set()

    for doc in sample_size_docs:
        c_name = doc.get("city", "").strip()
        if not c_name:
            continue
        b_grp = norm_brand_group(doc.get("brand_raw"))
        t_clean = clean_tenure(doc.get("tenure_raw"))

        ss_cities_set.add(c_name)
        ss_brands_set.add(b_grp)
        ss_tenures_set.add(t_clean)
        ss_counts[c_name][b_grp][t_clean] += 1

    sample_cities = sorted(list(ss_cities_set)) if ss_cities_set else ["Freetown", "Bo", "Kenema", "Makeni"]
    sample_brands = ["TVS HLX125", "Bajaj BM 125 / Bajaj CT 125"] if set(["TVS HLX125", "Bajaj BM 125 / Bajaj CT 125"]).issubset(ss_brands_set) else (sorted(list(ss_brands_set)) if ss_brands_set else ["TVS HLX125", "Bajaj BM 125 / Bajaj CT 125"])
    
    # Sort tenures e.g. 3-6 months, 6-12 months
    def tenure_sort_key(t):
        if "3" in t:
            return 1
        if "6" in t:
            return 2
        return 3

    sample_tenures = sorted(list(ss_tenures_set), key=tenure_sort_key) if ss_tenures_set else ["3-6 months", "6-12 months"]

    sample_table = []
    brand_tenure_totals = defaultdict(lambda: defaultdict(int))
    brand_totals_overall = defaultdict(int)
    total_grand = 0

    for c_name in sample_cities:
        row = {"city": c_name}
        row_grand = 0
        for b in sample_brands:
            b_tot = 0
            for t in sample_tenures:
                cnt = ss_counts[c_name][b][t]
                row[f"{b}_{t}"] = cnt
                brand_tenure_totals[b][t] += cnt
                b_tot += cnt
            row[f"{b}_total"] = b_tot
            brand_totals_overall[b] += b_tot
            row_grand += b_tot

        row["grand_total"] = row_grand
        sample_table.append(row)
        total_grand += row_grand

    # Grand Total row
    ss_grand_row = {"city": "Grand Total"}
    for b in sample_brands:
        b_tot = 0
        for t in sample_tenures:
            t_tot = brand_tenure_totals[b][t]
            ss_grand_row[f"{b}_{t}"] = t_tot
            b_tot += t_tot
        ss_grand_row[f"{b}_total"] = b_tot
    ss_grand_row["grand_total"] = total_grand
    sample_table.append(ss_grand_row)

    sample_size_data = {
        "cities": sample_cities,
        "brands": sample_brands,
        "tenures": sample_tenures,
        "table": sample_table,
    }

    # ── 7. Vehicle Usage Purpose (Column R) ────────────────────────
    usage_pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
                "raw_usage": {
                    "$trim": {
                        "input": {
                            "$ifNull": [
                                "$full_data.R",
                                {"$ifNull": ["$full_data.r", {"$ifNull": ["$purpose_of_usage", ""]}]}
                            ]
                        }
                    }
                }
            }
        },
        {"$match": {"brand": {"$in": BRANDS}, "raw_usage": {"$ne": ""}}},
        {
            "$group": {
                "_id": {"brand": "$brand", "usage": "$raw_usage"},
                "count": {"$sum": 1}
            }
        }
    ]

    usage_results = await SurveyResponse.aggregate(usage_pipeline).to_list(length=1000)

    def normalize_usage(val):
        if not val:
            return "Others"
        v = str(val).strip()
        vl = v.lower()
        if "taxi" in vl or "commercial" in vl or "passenger" in vl or "okada" in vl:
            return "Commercial / Taxi"
        if "personal" in vl or "private" in vl or "family" in vl:
            return "Personal Transport"
        if "business" in vl or "work" in vl or "office" in vl:
            return "Business"
        if "delivery" in vl or "goods" in vl or "cargo" in vl:
            return "Goods Delivery"
        if "rental" in vl or "lease" in vl:
            return "Rental / Lease"
        return v.title()

    usage_counts = {b: defaultdict(int) for b in BRANDS}
    usage_totals_overall = defaultdict(int)
    usage_brand_totals = {b: 0 for b in BRANDS}

    for r in usage_results:
        b = r["_id"]["brand"]
        raw = r["_id"]["usage"]
        cnt = r["count"]

        if b in BRANDS and raw:
            norm = normalize_usage(raw)
            usage_counts[b][norm] += cnt
            usage_totals_overall[norm] += cnt
            usage_brand_totals[b] += cnt

    sorted_usages = sorted(usage_totals_overall.items(), key=lambda x: -x[1])
    top_usages = [u for u, _ in sorted_usages[:5]]
    usage_categories = top_usages if top_usages else ["Commercial / Taxi", "Personal Transport", "Business", "Others"]
    if "Others" not in usage_categories and len(sorted_usages) > 5:
        usage_categories.append("Others")

    final_usage_counts = {b: {u: 0 for u in usage_categories} for b in BRANDS}
    for b in BRANDS:
        for u, cnt in usage_counts[b].items():
            if u in usage_categories:
                final_usage_counts[b][u] += cnt
            else:
                if "Others" in usage_categories:
                    final_usage_counts[b]["Others"] += cnt

    usage_table = []
    usage_chart = []
    usage_grand_total_overall = sum(usage_brand_totals[b] for b in BRANDS)

    for cat in usage_categories:
        row = {"category": cat}
        for b in BRANDS:
            cnt = final_usage_counts[b][cat]
            total = usage_brand_totals[b]
            pct = round((cnt / total * 100), 1) if total else 0
            row[b] = cnt
            row[f"{b}_pct"] = pct
            row[f"{b}_count"] = cnt
        cat_total_cnt = sum(final_usage_counts[b][cat] for b in BRANDS)
        row["total"] = round((cat_total_cnt / usage_grand_total_overall * 100), 1) if usage_grand_total_overall else 0
        usage_table.append(row)

        chart_row = {"category": cat}
        for b in BRANDS:
            cnt = final_usage_counts[b][cat]
            total = usage_brand_totals[b]
            chart_row[f"{b}_count"] = cnt
            chart_row[f"{b}_pct"] = round((cnt / total * 100), 1) if total else 0
        usage_chart.append(chart_row)

    usage_grand = {"category": "Grand Total"}
    for b in BRANDS:
        usage_grand[b] = 100.0
        usage_grand[f"{b}_pct"] = 100.0
        usage_grand[f"{b}_count"] = usage_brand_totals[b]
    usage_grand["total"] = 100.0
    usage_table.append(usage_grand)

    vehicle_usage_data = {
        "categories": usage_categories,
        "category_header": "Vehicle usage",
        "brands": BRANDS,
        "table": usage_table,
        "chart": usage_chart
    }

    return {
        "age_group": age_group_data,
        "age_city": age_city_data,
        "mode_of_purchase": mode_of_purchase_data,
        "ownership": ownership_data,
        "profession": profession_data,
        "location_model_sample_size": sample_size_data,
        "vehicle_usage": vehicle_usage_data,
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


@router.get("/nps")
async def get_nps_data(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get NPS data including recommendation metrics, city-wise grids, and duration of usage segmentation.
    """
    from app.models.survey_response import SurveyResponse
    from collections import defaultdict

    query = await _build_file_query(file_id, region_id, country_id, ib_version_id)
    raw_brands = await SurveyResponse.distinct("brand_model", filter=query if query else None)
    BRANDS = sorted(set(clean_brand_name(b) for b in raw_brands if b and b != "Blank"))

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": {"$ifNull": ["$brand_model", "Unknown"]},
                "city": {"$trim": {"input": {"$ifNull": ["$survey_location", ""]}}},
                "recommend_vehicle": {"$trim": {"input": {"$toLower": {"$ifNull": ["$recommend_vehicle", ""]}}}},
                "recommend_category": "$recommend_category",
                "duration_of_usage": {"$trim": {"input": {"$ifNull": ["$duration_of_usage", ""]}}}
            }
        },
        {"$match": {"brand": {"$in": BRANDS}}}
    ]
    
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)
    
    # 1. recommend_vehicle_pie: brand-wise yes/no
    # 2. recommend_category_bar: brand-wise yes/maybe/no
    # 3. city_grid: city -> brand -> yes/maybe/no
    # 4. city_duration_segmentation: city -> duration -> brand -> yes/maybe/no
    
    overall_recommend = defaultdict(lambda: {"yes": 0, "no": 0, "total": 0})
    overall_category = defaultdict(lambda: {"Yes": 0, "Maybe": 0, "No": 0, "total": 0})
    city_category = defaultdict(lambda: defaultdict(lambda: {"Yes": 0, "Maybe": 0, "No": 0}))
    city_duration_category = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {"Yes": 0, "Maybe": 0, "No": 0})))
    
    for r in results:
        b = clean_brand_name(r.get("brand"))
        if b not in BRANDS:
            continue
            
        rv = r.get("recommend_vehicle", "")
        if "yes" in rv:
            overall_recommend[b]["yes"] += 1
            overall_recommend[b]["total"] += 1
        elif "no" in rv:
            overall_recommend[b]["no"] += 1
            overall_recommend[b]["total"] += 1
            
        rc = r.get("recommend_category")
        if rc in ["Yes", "Maybe", "No"]:
            overall_category[b][rc] += 1
            overall_category[b]["total"] += 1
            
            c = r.get("city", "")
            if c and c != "Blank":
                city_category[c][b][rc] += 1
                
            d = r.get("duration_of_usage", "")
            if c and c != "Blank" and d and d != "Blank":
                city_duration_category[c][d][b][rc] += 1
                
    # Format outputs
    recommend_vehicle_pie = []
    for b in BRANDS:
        if overall_recommend[b]["total"] > 0:
            recommend_vehicle_pie.append({
                "brand": b,
                "yes": overall_recommend[b]["yes"],
                "no": overall_recommend[b]["no"]
            })
            
    recommend_category_bar = []
    for b in BRANDS:
        if overall_category[b]["total"] > 0:
            recommend_category_bar.append({
                "brand": b,
                "yes": overall_category[b]["Yes"],
                "maybe": overall_category[b]["Maybe"],
                "no": overall_category[b]["No"]
            })
            
    city_grid = []
    for c, brands_data in city_category.items():
        row = {"city": c}
        has_data = False
        for b in BRANDS:
            if b in brands_data:
                row[f"{b}_Yes"] = brands_data[b]["Yes"]
                row[f"{b}_Maybe"] = brands_data[b]["Maybe"]
                row[f"{b}_No"] = brands_data[b]["No"]
                if any(v > 0 for v in brands_data[b].values()):
                    has_data = True
            else:
                row[f"{b}_Yes"] = 0
                row[f"{b}_Maybe"] = 0
                row[f"{b}_No"] = 0
        if has_data:
            city_grid.append(row)
            
    city_duration_segmentation = []
    for c, durations_data in city_duration_category.items():
        durations_list = []
        for d, brands_data in durations_data.items():
            segment_data = []
            for b in BRANDS:
                if b in brands_data and any(v > 0 for v in brands_data[b].values()):
                    segment_data.append({
                        "brand": b,
                        "yes": brands_data[b]["Yes"],
                        "maybe": brands_data[b]["Maybe"],
                        "no": brands_data[b]["No"]
                    })
            if segment_data:
                durations_list.append({
                    "duration": d,
                    "data": segment_data
                })
        if durations_list:
            durations_list.sort(key=lambda x: x["duration"])
            city_duration_segmentation.append({
                "city": c,
                "durations": durations_list
            })
            
    city_duration_segmentation.sort(key=lambda x: x["city"])

    return {
        "brands": BRANDS,
        "recommend_vehicle_pie": recommend_vehicle_pie,
        "recommend_category_bar": recommend_category_bar,
        "city_grid": city_grid,
        "city_duration_segmentation": city_duration_segmentation
    }


@router.get("/service-satisfaction")
async def get_service_satisfaction(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    brand_model: Optional[str] = None,
    survey_location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get Service Satisfaction analysis for Authorized Service Workshops across brands.
    Filters: BN == "Authorized Workshop"
    Columns: CF (5A) - CO (5J), CP (6), CQ (7), CS (9), CT (10).
    """
    from app.models.survey_response import SurveyResponse
    from collections import defaultdict
    import re

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, brand_model, survey_location, date_from, date_to, search
    )

    pipeline = [
        {"$match": query},
        {
            "$project": {
                "brand": "$brand_model",
                "workshop_val": {
                    "$ifNull": [
                        "$service_workshop_type",
                        "$full_data.BN",
                        "$full_data.Q1-1 WHERE DO YOU GET YOUR VEHICLE SERVICED?"
                    ]
                },
                "full_data": "$full_data"
            }
        }
    ]
    results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    def parse_workshop(val: Any) -> bool:
        if val is None:
            return False
        s = str(val).strip().lower()
        if not s or s in ("blank", "nan", "none", "null", "-", "....") or re.match(r"^submit\s?form", s):
            return False
        return "authorized" in s or "dealer" in s

    def parse_yes_no(val: Any) -> Optional[str]:
        if val is None:
            return None
        s = str(val).strip().lower()
        if not s or s in ("blank", "nan", "none", "null", "-", "....", "not applicable", "n/a") or re.match(r"^submit\s?form", s):
            return None
        if "not ok" in s or s.startswith("no") or s == "0" or s == "n" or s == "false":
            return "No"
        return "Yes"

    metric_defs = [
        {"key": "5A", "col": "CF", "question": "5A) Have you received Service reminder call", "prefix": "5a"},
        {"key": "5B", "col": "CG", "question": "5B) Appointment given", "prefix": "5b"},
        {"key": "5C", "col": "CH", "question": "5C) Vehicle test drive taken while making job cards to understand the complaints", "prefix": "5c"},
        {"key": "5D", "col": "CI", "question": "5D) Customer lounge Facilities", "prefix": "5d"},
        {"key": "5E", "col": "CJ", "question": "5E) Staff behaviour", "prefix": "5e"},
        {"key": "5F", "col": "CK", "question": "5F) All complaints reported are resolved", "prefix": "5f"},
        {"key": "5G", "col": "CL", "question": "5G) Fairness of charges", "prefix": "5g"},
        {"key": "5H", "col": "CM", "question": "5H) Explanation of Work done", "prefix": "5h"},
        {"key": "5I", "col": "CN", "question": "5I) Washing quality", "prefix": "5i"},
        {"key": "5J", "col": "CO", "question": "5J) Test drive offered before billing", "prefix": "5j"},
    ]

    section_defs = {
        "6": {"col": "CP", "question": "6. Are you satisfied with Vehicle Performance after service? (VPS)", "prefix": "6."},
        "7": {"col": "CQ", "question": "7. Currently are you facing any issues / complaints in vehicle?", "prefix": "7."},
        "8": {"col": "CR", "question": "8. Have you reported this issue to the Service advisor during Job card making during your last Visit?", "prefix": "8."},
        "9": {"col": "CS", "question": "9. Fixing problems First Time Right", "prefix": "9."},
        "10": {"col": "CT", "question": "10. Delivery as per promised time", "prefix": "10."},
    }

    def extract_val(fd: dict, col: str, prefix: str) -> Any:
        if not isinstance(fd, dict):
            return None
        if col in fd and fd[col] is not None:
            return fd[col]
        for k, v in fd.items():
            if not k:
                continue
            k_str = str(k).strip().lower()
            p_str = prefix.lower()
            if k_str == col.lower() or k_str.startswith(p_str) or k_str.startswith(f"a{p_str}"):
                if v is not None:
                    return v
        return None

    brand_base_counts = defaultdict(int)
    metric_counts = {m["key"]: defaultdict(lambda: {"Yes": 0, "No": 0, "filled": 0}) for m in metric_defs}
    section_counts = {s_key: defaultdict(lambda: {"Yes": 0, "No": 0, "filled": 0}) for s_key in section_defs}

    for r in results:
        if not parse_workshop(r.get("workshop_val")):
            continue

        b = clean_brand_name(r.get("brand"))
        fd = r.get("full_data") or {}

        brand_base_counts[b] += 1

        for m in metric_defs:
            v = extract_val(fd, m["col"], m["prefix"])
            yn = parse_yes_no(v)
            if yn:
                metric_counts[m["key"]][b]["filled"] += 1
                metric_counts[m["key"]][b][yn] += 1

        for s_key, s_def in section_defs.items():
            v = extract_val(fd, s_def["col"], s_def["prefix"])
            yn = parse_yes_no(v)
            if yn:
                section_counts[s_key][b]["filled"] += 1
                section_counts[s_key][b][yn] += 1

    sorted_brands = sorted(brand_base_counts.keys())

    formatted_metrics = []
    for m in metric_defs:
        m_key = m["key"]
        brand_data = []
        for b in sorted_brands:
            base = brand_base_counts[b]
            f_cnt = metric_counts[m_key][b]["filled"]
            y_cnt = metric_counts[m_key][b]["Yes"]
            n_cnt = metric_counts[m_key][b]["No"]
            tot_denom = f_cnt if f_cnt > 0 else base
            brand_data.append({
                "brand": b,
                "base_count": base,
                "filled_count": f_cnt if f_cnt > 0 else base,
                "yes_count": y_cnt,
                "yes_pct": round((y_cnt / tot_denom * 100), 1) if tot_denom > 0 else 0.0,
                "no_count": n_cnt,
                "no_pct": round((n_cnt / tot_denom * 100), 1) if tot_denom > 0 else 0.0,
            })
        formatted_metrics.append({
            "key": m_key,
            "column": m["col"],
            "question": m["question"],
            "brand_data": brand_data
        })

    formatted_sections = {}
    for s_key, s_def in section_defs.items():
        brand_data = []
        for b in sorted_brands:
            base = brand_base_counts[b]
            y_cnt = section_counts[s_key][b]["Yes"]
            n_cnt = section_counts[s_key][b]["No"]
            ans_tot = y_cnt + n_cnt
            brand_data.append({
                "brand": b,
                "base_count": base,
                "total_count": ans_tot if ans_tot > 0 else base,
                "yes_count": y_cnt,
                "yes_pct": round((y_cnt / ans_tot * 100), 1) if ans_tot > 0 else (round((y_cnt / base * 100), 1) if base > 0 else 0.0),
                "no_count": n_cnt,
                "no_pct": round((n_cnt / ans_tot * 100), 1) if ans_tot > 0 else (round((n_cnt / base * 100), 1) if base > 0 else 0.0),
            })
        formatted_sections[s_key] = {
            "key": s_key,
            "column": s_def["col"],
            "question": s_def["question"],
            "brand_data": brand_data
        }

    brand_bases_list = [{"brand": b, "base_count": brand_base_counts[b]} for b in sorted_brands]

    return {
        "metrics": formatted_metrics,
        "sections": formatted_sections,
        "brand_bases": brand_bases_list,
    }


@router.get("/ib-summary-table")
async def get_ib_summary_table(
    file_id: Optional[str] = None,
    region_id: Optional[str] = None,
    country_id: Optional[str] = None,
    ib_version_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    search: Optional[str] = None,
    _: User = Depends(get_admin_or_super),
):
    """
    Get IB-wise overall summary table data including:
    - IB Version Name
    - Region & Country details
    - Total Uploaded Files & Status
    - Total Sample Size (Respondents)
    - NPS Breakdown (Promoters, Passives, Detractors, Avg NPS Score)
    - Total Issues & Benefits mentioned
    - Brands covered
    """
    from app.models.survey_response import SurveyResponse
    from app.models.uploaded_file import UploadedFile
    from app.models.ib_version import IBVersion
    from app.models.region import Region
    from app.models.country import Country
    from beanie import PydanticObjectId
    from collections import defaultdict

    ib_versions = await IBVersion.find_all().to_list()
    regions = {str(r.id): r.name for r in await Region.find_all().to_list()}
    countries = {str(c.id): c.name for c in await Country.find_all().to_list()}

    query = await _build_full_query(
        file_id, region_id, country_id, ib_version_id, None, None, date_from, date_to, search
    )

    file_filter = {"status": "completed"}
    if region_id:
        file_filter["region_id"] = PydanticObjectId(region_id)
    if country_id:
        file_filter["country_id"] = PydanticObjectId(country_id)
    if ib_version_id:
        file_filter["ib_version_id"] = PydanticObjectId(ib_version_id)
        
    completed_files = await UploadedFile.find(file_filter).to_list()
    file_to_ib = {f.id: str(f.ib_version_id) if f.ib_version_id else "default" for f in completed_files}
    file_to_region = {f.id: regions.get(str(f.region_id), "Default") for f in completed_files}
    file_to_country = {f.id: countries.get(str(f.country_id), "Default") for f in completed_files}

    pipeline = [
        {"$match": query if query else {}},
        {
            "$project": {
                "file_id": 1,
                "brand_model": 1,
                "nps_score": 1,
                "recommend_category": 1,
                "prod_cat": {
                    "$cond": [
                        {"$ne": ["$recommend_category", None]},
                        "$recommend_category",
                        {
                            "$cond": [
                                {"$gte": ["$nps_score", 9]},
                                "Yes",
                                {
                                    "$cond": [
                                        {"$gte": ["$nps_score", 7]},
                                        "Maybe",
                                        {
                                            "$cond": [
                                                {"$gte": ["$nps_score", 0]},
                                                "No",
                                                None
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                "service_cat": {
                    "$let": {
                        "vars": {
                            "s_rec": {"$toLower": {"$trim": {"input": {"$ifNull": ["$service_recommend", {"$ifNull": ["$full_data.BR", {"$ifNull": ["$full_data.A1. Will you recommend / tell / advise your friends or family members for servicing their vehicle at Authorized Service workshop / Authorized Dealer?", ""]}]}]}}}},
                            "s_num": {"$ifNull": ["$service_nps_score", "$full_data.BS"]}
                        },
                        "in": {
                            "$cond": [
                                {"$in": ["$$s_rec", ["yes", "promoter", "definitely recommend", "1"]]},
                                "Yes",
                                {
                                    "$cond": [
                                        {"$in": ["$$s_rec", ["may be", "maybe", "passive", "less likely recommend", "more likely recommend"]]},
                                        "Maybe",
                                        {
                                            "$cond": [
                                                {"$in": ["$$s_rec", ["no", "detractor", "will not at all recommend", "0"]]},
                                                "No",
                                                {
                                                    "$cond": [
                                                        {"$gte": ["$$s_num", 9]},
                                                        "Yes",
                                                        {
                                                            "$cond": [
                                                                {"$gte": ["$$s_num", 7]},
                                                                "Maybe",
                                                                {
                                                                    "$cond": [
                                                                        {"$gte": ["$$s_num", 0]},
                                                                        "No",
                                                                        None
                                                                    ]
                                                                }
                                                            ]
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                },
                "issue_count": {
                    "$size": {
                        "$filter": {
                            "input": {"$ifNull": ["$complaint_groups", []]},
                            "as": "issue",
                            "cond": {
                                "$not": {
                                    "$regexMatch": {
                                        "input": "$$issue",
                                        "regex": "^submitform",
                                        "options": "i"
                                    }
                                }
                            }
                        }
                    }
                },
                "benefit_count": {
                    "$size": {
                        "$objectToArray": {"$ifNull": ["$passive_data", {}]}
                    }
                }
            }
        },
        {
            "$group": {
                "_id": "$file_id",
                "total_responses": {"$sum": 1},
                "brands": {"$addToSet": "$brand_model"},
                "prod_promoters": {"$sum": {"$cond": [{"$eq": ["$prod_cat", "Yes"]}, 1, 0]}},
                "prod_passives": {"$sum": {"$cond": [{"$eq": ["$prod_cat", "Maybe"]}, 1, 0]}},
                "prod_detractors": {"$sum": {"$cond": [{"$eq": ["$prod_cat", "No"]}, 1, 0]}},
                "serv_promoters": {"$sum": {"$cond": [{"$eq": ["$service_cat", "Yes"]}, 1, 0]}},
                "serv_passives": {"$sum": {"$cond": [{"$eq": ["$service_cat", "Maybe"]}, 1, 0]}},
                "serv_detractors": {"$sum": {"$cond": [{"$eq": ["$service_cat", "No"]}, 1, 0]}},
                "avg_nps": {"$avg": "$nps_score"},
                "total_issues": {"$sum": "$issue_count"},
                "total_benefits": {"$sum": "$benefit_count"},
            }
        }
    ]

    agg_results = await SurveyResponse.aggregate(pipeline).to_list(length=None)

    ib_stats = defaultdict(lambda: {
        "file_count": 0,
        "total_responses": 0,
        "brands": set(),
        "prod_promoters": 0,
        "prod_passives": 0,
        "prod_detractors": 0,
        "serv_promoters": 0,
        "serv_passives": 0,
        "serv_detractors": 0,
        "nps_scores": [],
        "total_issues": 0,
        "total_benefits": 0,
        "regions": set(),
        "countries": set(),
    })

    for row in agg_results:
        f_id = row["_id"]
        ib_id = file_to_ib.get(f_id, "default")
        reg = file_to_region.get(f_id)
        cntry = file_to_country.get(f_id)

        stats = ib_stats[ib_id]
        stats["file_count"] += 1
        stats["total_responses"] += row["total_responses"]
        for b in row["brands"]:
            if b and b != "Blank":
                stats["brands"].add(clean_brand_name(b))
        stats["prod_promoters"] += row.get("prod_promoters", 0)
        stats["prod_passives"] += row.get("prod_passives", 0)
        stats["prod_detractors"] += row.get("prod_detractors", 0)
        stats["serv_promoters"] += row.get("serv_promoters", 0)
        stats["serv_passives"] += row.get("serv_passives", 0)
        stats["serv_detractors"] += row.get("serv_detractors", 0)
        if row["avg_nps"] is not None:
            stats["nps_scores"].append(row["avg_nps"])
        stats["total_issues"] += row["total_issues"]
        stats["total_benefits"] += row["total_benefits"]
        if reg: stats["regions"].add(reg)
        if cntry: stats["countries"].add(cntry)

    summary_rows = []
    ib_dict = {str(ib.id): ib.name for ib in ib_versions}

    for ib_id, stats in ib_stats.items():
        ib_name = ib_dict.get(ib_id, "Standard IB Version")
        tot = stats["total_responses"]

        # Product NPS calculation
        p_prom = stats["prod_promoters"]
        p_pass = stats["prod_passives"]
        p_detr = stats["prod_detractors"]
        p_tot = p_prom + p_pass + p_detr or tot
        p_prom_pct = round((p_prom / p_tot * 100)) if p_tot > 0 else 0
        p_pass_pct = round((p_pass / p_tot * 100)) if p_tot > 0 else 0
        p_detr_pct = round((p_detr / p_tot * 100)) if p_tot > 0 else 0
        p_nps_score = p_prom_pct - p_detr_pct

        # Service NPS calculation
        s_prom = stats["serv_promoters"]
        s_pass = stats["serv_passives"]
        s_detr = stats["serv_detractors"]
        s_tot = s_prom + s_pass + s_detr or tot
        s_prom_pct = round((s_prom / s_tot * 100)) if s_tot > 0 else 0
        s_pass_pct = round((s_pass / s_tot * 100)) if s_tot > 0 else 0
        s_detr_pct = round((s_detr / s_tot * 100)) if s_tot > 0 else 0
        s_nps_score = s_prom_pct - s_detr_pct

        summary_rows.append({
            "ib_version_id": ib_id,
            "ib_version_name": ib_name,
            "regions": sorted(list(stats["regions"])) or ["All Regions"],
            "countries": sorted(list(stats["countries"])) or ["All Countries"],
            "file_count": stats["file_count"],
            "total_responses": tot,
            "brand_count": len(stats["brands"]),
            "brands": sorted(list(stats["brands"])),
            "product_nps": {
                "promoters": p_prom,
                "promoters_pct": p_prom_pct,
                "passives": p_pass,
                "passives_pct": p_pass_pct,
                "detractors": p_detr,
                "detractors_pct": p_detr_pct,
                "nps_score": p_nps_score,
            },
            "service_nps": {
                "promoters": s_prom,
                "promoters_pct": s_prom_pct,
                "passives": s_pass,
                "passives_pct": s_pass_pct,
                "detractors": s_detr,
                "detractors_pct": s_detr_pct,
                "nps_score": s_nps_score,
            },
            "promoters": p_prom,
            "promoters_pct": p_prom_pct,
            "passives": p_pass,
            "passives_pct": p_pass_pct,
            "detractors": p_detr,
            "detractors_pct": p_detr_pct,
            "nps_score": p_nps_score,
            "total_issues": stats["total_issues"],
            "total_benefits": stats["total_benefits"],
            "status": "OK / Active",
        })

    summary_rows.sort(key=lambda x: x["ib_version_name"])

    return {
        "summary": summary_rows,
        "total_ib_versions": len(summary_rows),
        "total_responses": sum(r["total_responses"] for r in summary_rows),
        "total_issues": sum(r["total_issues"] for r in summary_rows),
        "total_benefits": sum(r["total_benefits"] for r in summary_rows),
    }

