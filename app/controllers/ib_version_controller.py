"""
IB Version controller - Business logic for IB version management.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.ib_version import IBVersion


class IBVersionController:
    """Controller for IB version management operations."""
    
    @staticmethod
    async def list_ib_versions() -> Dict[str, Any]:
        """
        List all IB versions.
        """
        versions = await IBVersion.find_all().sort("+display_order").to_list()
        return {
            "data": [
                {
                    "id": str(v.id),
                    "name": v.name,
                    "display_order": v.display_order,
                    "created_at": v.created_at,
                    "updated_at": v.updated_at,
                }
                for v in versions
            ]
        }

    @staticmethod
    async def create_ib_version(name: str, display_order: int = 0) -> Dict[str, Any]:
        """
        Create a new IB version.
        """
        existing = await IBVersion.find_one({"name": name})
        if existing:
            raise HTTPException(status_code=400, detail="IB Version already exists")
            
        version = IBVersion(name=name, display_order=display_order)
        await version.insert()
        logger.info(f"IB Version created: {name}")
        return {"id": str(version.id), "name": version.name}

    @staticmethod
    async def update_ib_version(
        version_id: str,
        name: Optional[str] = None,
        display_order: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update IB version details.
        """
        version = await IBVersion.get(PydanticObjectId(version_id))
        if not version:
            raise HTTPException(status_code=404, detail="IB Version not found")
            
        update_data = {}
        if name:
            update_data["name"] = name
        if display_order is not None:
            update_data["display_order"] = display_order
        update_data["updated_at"] = datetime.utcnow()
        
        await version.update({"$set": update_data})
        await version.sync()
        logger.info(f"IB Version updated: {version_id}")
        return {"id": str(version.id), "name": version.name}

    @staticmethod
    async def delete_ib_version(version_id: str) -> Dict[str, Any]:
        """
        Delete IB version.
        """
        version = await IBVersion.get(PydanticObjectId(version_id))
        if not version:
            raise HTTPException(status_code=404, detail="IB Version not found")
            
        await version.delete()
        logger.info(f"IB Version deleted: {version_id}")
        return {"message": "IB Version deleted"}

    @staticmethod
    async def reorder_ib_versions(version_ids: List[str]) -> Dict[str, Any]:
        """
        Reorder IB versions by display order.
        """
        for order, vid in enumerate(version_ids):
            await IBVersion.find_one(IBVersion.id == PydanticObjectId(vid)).update(
                {"$set": {"display_order": order, "updated_at": datetime.utcnow()}}
            )
        logger.info("IB Versions reordered")
        return {"message": "IB Versions reordered"}