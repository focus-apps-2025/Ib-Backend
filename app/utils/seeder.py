"""
Database seeder: creates initial Super Admin, Regions, Countries, IB Versions,
and 33 Issue Mappings on first startup.
"""
from datetime import datetime
from loguru import logger

from app.config.settings import settings
from app.middleware.auth import hash_password
from app.utils.column_mapping import (
    ISSUE_COLUMN_RANGE_MAPPING,
    index_to_col_letter,
    col_letter_to_index,
    get_question_text_for_column,
)


# ─── Seed Data ───────────────────────────────────────────────────────────────

REGIONS_DATA = [
    ("West Africa",     0),
    ("East Africa",     1),
    ("Asia",            2),
    ("Central America", 3),
    ("South America",   4),
    ("Central Africa",  5),
    ("Middle East",     6),
]

COUNTRIES_DATA = {
    "West Africa":     ["Ghana", "Benin", "Liberia", "Senegal", "Guinea", "Sierra Leone", "Ivory Coast", "Togo"],
    "East Africa":     ["Tanzania", "Kenya", "Uganda"],
    "Asia":            ["Nepal", "Sri Lanka"],
    "Central America": ["Guatemala"],
    "South America":   ["Colombia", "Argentina", "Peru", "Mexico"],
    "Central Africa":  ["Angola", "Cameroon"],
    "Middle East":     ["Turkey"],
}

IB_VERSIONS_DATA = ["IB1", "IB2", "IB3", "IB4", "IB5"]


async def seed_initial_data():
    from app.models.user import User
    from app.models.region import Region
    from app.models.country import Country
    from app.models.ib_version import IBVersion
    from app.models.issue_mapping import IssueMapping, FollowUp, ColumnRange

    seeded_anything = False

    # ── Super Admin ────────────────────────────────────────────────────────
    existing_admin = await User.find_one({"role": "super_admin"})
    if not existing_admin:
        super_admin = User(
            username=settings.SUPER_ADMIN_USERNAME,
            email=settings.SUPER_ADMIN_EMAIL,
            password_hash=hash_password(settings.SUPER_ADMIN_PASSWORD),
            full_name=settings.SUPER_ADMIN_FULLNAME,
            role="super_admin",
            is_active=True,
        )
        await super_admin.insert()
        logger.success(f"✅ Super Admin created: {settings.SUPER_ADMIN_EMAIL}")
        seeded_anything = True

    # ── Regions & Countries ───────────────────────────────────────────────
    for region_name, order in REGIONS_DATA:
        region = await Region.find_one({"name": region_name})
        if not region:
            region = Region(name=region_name, display_order=order)
            await region.insert()
            seeded_anything = True

        countries = COUNTRIES_DATA.get(region_name, [])
        for c_idx, country_name in enumerate(countries):
            existing_c = await Country.find_one(
                {"region_id": region.id, "name": country_name}
            )
            if not existing_c:
                await Country(
                    region_id=region.id,
                    name=country_name,
                    display_order=c_idx,
                ).insert()
                seeded_anything = True

    # ── IB Versions ───────────────────────────────────────────────────────
    for idx, ib_name in enumerate(IB_VERSIONS_DATA):
        existing_ib = await IBVersion.find_one({"name": ib_name})
        if not existing_ib:
            await IBVersion(name=ib_name, display_order=idx).insert()
            seeded_anything = True

    # ── 30 Issue Mappings ─────────────────────────────────────────────────
    for idx, (issue_name, range_info) in enumerate(ISSUE_COLUMN_RANGE_MAPPING.items()):
        start_idx = col_letter_to_index(range_info["start"])
        end_idx = col_letter_to_index(range_info["end"])

        follow_ups = [
            FollowUp(
                column_letter=index_to_col_letter(col_i),
                question_text=get_question_text_for_column(index_to_col_letter(col_i)),
                display_order=col_i - start_idx,
            )
            for col_i in range(start_idx, end_idx + 1)
        ]

        existing_issue = await IssueMapping.find_one({"issue_name": issue_name})
        if not existing_issue:
            await IssueMapping(
                issue_name=issue_name,
                display_order=idx,
                column_range=ColumnRange(
                    start=range_info["start"],
                    end=range_info["end"],
                    count=range_info["count"],
                ),
                follow_ups=follow_ups,
            ).insert()
            seeded_anything = True
        else:
            # Refresh question texts if needed
            needs_update = False
            current_follow_ups = {f.column_letter: f.question_text for f in existing_issue.follow_ups}
            new_follow_ups = {f.column_letter: f.question_text for f in follow_ups}
            if (
                len(existing_issue.follow_ups) != len(follow_ups)
                or any(current_follow_ups.get(col) != text for col, text in new_follow_ups.items())
            ):
                existing_issue.follow_ups = follow_ups
                existing_issue.column_range = ColumnRange(
                    start=range_info["start"],
                    end=range_info["end"],
                    count=range_info["count"],
                )
                await existing_issue.save()
                needs_update = True
            if needs_update:
                seeded_anything = True

    if seeded_anything:
        logger.success("✅ Database seeded successfully")
    else:
        logger.info("ℹ️  Database already seeded, skipping")
