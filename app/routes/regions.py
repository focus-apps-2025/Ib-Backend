from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from beanie import PydanticObjectId

from app.models.region import Region
from app.models.country import Country
from app.models.user import User
from app.middleware.auth import get_super_admin, get_current_user

router = APIRouter(prefix="/regions", tags=["Region Management"])


class RegionCreate(BaseModel):
    name: str
    display_order: int = 0


class RegionUpdate(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None


class ReorderRequest(BaseModel):
    ids: List[str]  # ordered list of region IDs


def region_to_dict(r: Region, country_count: int = 0) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "display_order": r.display_order,
        "country_count": country_count,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
    }


@router.get("")
async def list_regions(_: User = Depends(get_current_user)):
    regions = await Region.find_all().sort("+display_order").to_list()
    result = []
    for r in regions:
        count = await Country.find({"region_id": r.id}).count()
        result.append(region_to_dict(r, count))
    return {"data": result, "total": len(result)}


@router.post("", status_code=201)
async def create_region(data: RegionCreate, _: User = Depends(get_super_admin)):
    existing = await Region.find_one({"name": data.name})
    if existing:
        raise HTTPException(status_code=400, detail="Region already exists")
    region = Region(**data.model_dump())
    await region.insert()
    return region_to_dict(region)


@router.put("/{region_id}")
async def update_region(
    region_id: str,
    data: RegionUpdate,
    _: User = Depends(get_super_admin),
):
    region = await Region.get(PydanticObjectId(region_id))
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    update_data = data.model_dump(exclude_none=True)
    update_data["updated_at"] = datetime.utcnow()
    await region.update({"$set": update_data})
    await region.sync()
    return region_to_dict(region)


@router.delete("/{region_id}")
async def delete_region(region_id: str, _: User = Depends(get_super_admin)):
    region = await Region.get(PydanticObjectId(region_id))
    if not region:
        raise HTTPException(status_code=404, detail="Region not found")
    country_count = await Country.find({"region_id": region.id}).count()
    if country_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete: {country_count} countries are linked to this region",
        )
    await region.delete()
    return {"message": "Region deleted successfully"}


@router.patch("/reorder")
async def reorder_regions(data: ReorderRequest, _: User = Depends(get_super_admin)):
    for order, region_id in enumerate(data.ids):
        await Region.find_one(Region.id == PydanticObjectId(region_id)).update(
            {"$set": {"display_order": order, "updated_at": datetime.utcnow()}}
        )
    return {"message": "Regions reordered successfully"}
