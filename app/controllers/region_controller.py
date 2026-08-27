"""
Region controller - Business logic for region management.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.region import Region
from app.models.country import Country


class RegionController:
    """Controller for region management operations."""
    
    @staticmethod
    async def list_regions() -> Dict[str, Any]:
        """
        List all regions with country counts.
        """
        regions = await Region.find_all().sort("+display_order").to_list()
        result = []
        for r in regions:
            count = await Country.find({"region_id": r.id}).count()
            result.append(RegionController._region_to_dict(r, country_count=count))
        return {"data": result, "total": len(result)}

    @staticmethod
    async def create_region(name: str, display_order: int = 0) -> Dict[str, Any]:
        """
        Create a new region.
        """
        existing = await Region.find_one({"name": name})
        if existing:
            raise HTTPException(status_code=400, detail="Region already exists")
            
        region = Region(name=name, display_order=display_order)
        await region.insert()
        logger.info(f"Region created: {name}")
        return RegionController._region_to_dict(region)

    @staticmethod
    async def update_region(
        region_id: str,
        name: Optional[str] = None,
        display_order: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update region details.
        """
        region = await Region.get(PydanticObjectId(region_id))
        if not region:
            raise HTTPException(status_code=404, detail="Region not found")
            
        update_data = {}
        if name:
            update_data["name"] = name
        if display_order is not None:
            update_data["display_order"] = display_order
        update_data["updated_at"] = datetime.utcnow()
        
        await region.update({"$set": update_data})
        await region.sync()
        logger.info(f"Region updated: {region_id}")
        return RegionController._region_to_dict(region)

    @staticmethod
    async def delete_region(region_id: str) -> Dict[str, Any]:
        """
        Delete region (only if no countries linked).
        """
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
        logger.info(f"Region deleted: {region_id}")
        return {"message": "Region deleted successfully"}

    @staticmethod
    async def reorder_regions(region_ids: List[str]) -> Dict[str, Any]:
        """
        Reorder regions by display order.
        """
        for order, region_id in enumerate(region_ids):
            await Region.find_one(Region.id == PydanticObjectId(region_id)).update(
                {"$set": {"display_order": order, "updated_at": datetime.utcnow()}}
            )
        logger.info("Regions reordered")
        return {"message": "Regions reordered successfully"}

    @staticmethod
    def _region_to_dict(region: Region, country_count: int = 0) -> Dict[str, Any]:
        """
        Convert Region model to dictionary.
        """
        return {
            "id": str(region.id),
            "name": region.name,
            "display_order": region.display_order,
            "country_count": country_count,
            "created_at": region.created_at,
            "updated_at": region.updated_at,
        }