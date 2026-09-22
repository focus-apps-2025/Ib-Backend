from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from beanie import PydanticObjectId

from app.models.ib_version import IBVersion
from app.models.user import User
from app.middleware.auth import get_super_admin, get_current_user

router = APIRouter(prefix="/ib-versions", tags=["IB Version Management"])


class IBVersionCreate(BaseModel):
    name: str
    display_order: int = 0


class IBVersionUpdate(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None


class ReorderRequest(BaseModel):
    ids: List[str]


from app.middleware.scope import ScopedUser, get_scoped_user


@router.get("")
async def list_ib_versions(scoped_user: ScopedUser = Depends(get_scoped_user)):
    scope = scoped_user.scope
    if scoped_user.user.role == "super_admin" or scope is None or scope.all_ib_versions:
        versions = await IBVersion.find_all().sort("+display_order").to_list()
    else:
        allowed = scope.ib_version_ids or []
        versions = await IBVersion.find({"_id": {"$in": allowed}}).sort("+display_order").to_list() if allowed else []

    return {
        "data": [
            {"id": str(v.id), "name": v.name, "display_order": v.display_order,
             "created_at": v.created_at}
            for v in versions
        ]
    }


@router.post("", status_code=201)
async def create_ib_version(data: IBVersionCreate, _: User = Depends(get_super_admin)):
    existing = await IBVersion.find_one({"name": data.name})
    if existing:
        raise HTTPException(status_code=400, detail="IB Version already exists")
    version = IBVersion(**data.model_dump())
    await version.insert()
    return {"id": str(version.id), "name": version.name}


@router.put("/{version_id}")
async def update_ib_version(
    version_id: str,
    data: IBVersionUpdate,
    _: User = Depends(get_super_admin),
):
    version = await IBVersion.get(PydanticObjectId(version_id))
    if not version:
        raise HTTPException(status_code=404, detail="IB Version not found")
    update_data = data.model_dump(exclude_none=True)
    update_data["updated_at"] = datetime.utcnow()
    await version.update({"$set": update_data})
    await version.sync()
    return {"id": str(version.id), "name": version.name}


@router.delete("/{version_id}")
async def delete_ib_version(version_id: str, _: User = Depends(get_super_admin)):
    version = await IBVersion.get(PydanticObjectId(version_id))
    if not version:
        raise HTTPException(status_code=404, detail="IB Version not found")
    await version.delete()
    return {"message": "IB Version deleted"}


@router.patch("/reorder")
async def reorder_ib_versions(data: ReorderRequest, _: User = Depends(get_super_admin)):
    for order, vid in enumerate(data.ids):
        await IBVersion.find_one(IBVersion.id == PydanticObjectId(vid)).update(
            {"$set": {"display_order": order, "updated_at": datetime.utcnow()}}
        )
    return {"message": "IB Versions reordered"}
