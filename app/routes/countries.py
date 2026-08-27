from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from beanie import PydanticObjectId

from app.models.country import Country
from app.models.region import Region
from app.models.user import User
from app.middleware.auth import get_super_admin, get_current_user

router = APIRouter(prefix="/countries", tags=["Country Management"])


class CountryCreate(BaseModel):
    region_id: str
    name: str
    display_order: int = 0


class CountryUpdate(BaseModel):
    name: Optional[str] = None
    region_id: Optional[str] = None
    display_order: Optional[int] = None


class ReorderRequest(BaseModel):
    ids: List[str]


async def country_to_dict(c: Country) -> dict:
    region = await Region.get(c.region_id)
    return {
        "id": str(c.id),
        "region_id": str(c.region_id),
        "region_name": region.name if region else "Unknown",
        "name": c.name,
        "display_order": c.display_order,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


@router.get("")
async def list_countries(
    region_id: Optional[str] = None,
    _: User = Depends(get_current_user),
):
    query = {}
    if region_id:
        query["region_id"] = PydanticObjectId(region_id)
    countries = await Country.find(query).sort("+display_order").to_list()
    return {"data": [await country_to_dict(c) for c in countries], "total": len(countries)}


@router.get("/region/{region_id}")
async def get_countries_by_region(region_id: str, _: User = Depends(get_current_user)):
    countries = await Country.find(
        {"region_id": PydanticObjectId(region_id)}
    ).sort("+display_order").to_list()
    return {"data": [await country_to_dict(c) for c in countries]}


@router.post("", status_code=201)
async def create_country(data: CountryCreate, _: User = Depends(get_super_admin)):
    region = await Region.get(PydanticObjectId(data.region_id))
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")

    existing = await Country.find_one(
        {"region_id": PydanticObjectId(data.region_id), "name": data.name}
    )
    if existing:
        raise HTTPException(status_code=400, detail="Country already exists in this region")

    country = Country(
        region_id=PydanticObjectId(data.region_id),
        name=data.name,
        display_order=data.display_order,
    )
    await country.insert()
    return await country_to_dict(country)


@router.put("/{country_id}")
async def update_country(
    country_id: str,
    data: CountryUpdate,
    _: User = Depends(get_super_admin),
):
    country = await Country.get(PydanticObjectId(country_id))
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")
    update_data = data.model_dump(exclude_none=True)
    if "region_id" in update_data:
        update_data["region_id"] = PydanticObjectId(update_data["region_id"])
    update_data["updated_at"] = datetime.utcnow()
    await country.update({"$set": update_data})
    await country.sync()
    return await country_to_dict(country)


@router.delete("/{country_id}")
async def delete_country(country_id: str, _: User = Depends(get_super_admin)):
    country = await Country.get(PydanticObjectId(country_id))
    if not country:
        raise HTTPException(status_code=404, detail="Country not found")
    await country.delete()
    return {"message": "Country deleted successfully"}


@router.patch("/reorder")
async def reorder_countries(data: ReorderRequest, _: User = Depends(get_super_admin)):
    for order, country_id in enumerate(data.ids):
        await Country.find_one(Country.id == PydanticObjectId(country_id)).update(
            {"$set": {"display_order": order, "updated_at": datetime.utcnow()}}
        )
    return {"message": "Countries reordered"}
