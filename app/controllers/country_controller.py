"""
Country controller - Business logic for country management.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from beanie import PydanticObjectId
from fastapi import HTTPException
from loguru import logger

from app.models.country import Country
from app.models.region import Region


class CountryController:
    """Controller for country management operations."""
    
    @staticmethod
    async def list_countries(region_id: Optional[str] = None) -> Dict[str, Any]:
        """
        List countries with optional region filter.
        """
        query = {}
        if region_id:
            query["region_id"] = PydanticObjectId(region_id)
            
        countries = await Country.find(query).sort("+display_order").to_list()
        result = []
        for c in countries:
            region = await Region.get(c.region_id)
            result.append(CountryController._country_to_dict(c, region_name=region.name if region else "Unknown"))
        
        return {"data": result, "total": len(result)}

    @staticmethod
    async def get_countries_by_region(region_id: str) -> Dict[str, Any]:
        """
        Get countries by region ID.
        """
        countries = await Country.find(
            {"region_id": PydanticObjectId(region_id)}
        ).sort("+display_order").to_list()
        return {
            "data": [
                CountryController._country_to_dict(c) 
                for c in countries
            ]
        }

    @staticmethod
    async def create_country(
        region_id: str,
        name: str,
        display_order: int = 0,
    ) -> Dict[str, Any]:
        """
        Create a new country.
        """
        region = await Region.get(PydanticObjectId(region_id))
        if not region:
            raise HTTPException(status_code=404, detail="Region not found")

        existing = await Country.find_one(
            {"region_id": PydanticObjectId(region_id), "name": name}
        )
        if existing:
            raise HTTPException(status_code=400, detail="Country already exists in this region")

        country = Country(
            region_id=PydanticObjectId(region_id),
            name=name,
            display_order=display_order,
        )
        await country.insert()
        logger.info(f"Country created: {name} in region {region_id}")
        return CountryController._country_to_dict(country, region_name=region.name)

    @staticmethod
    async def update_country(
        country_id: str,
        name: Optional[str] = None,
        region_id: Optional[str] = None,
        display_order: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Update country details.
        """
        country = await Country.get(PydanticObjectId(country_id))
        if not country:
            raise HTTPException(status_code=404, detail="Country not found")
            
        update_data = {}
        if name:
            update_data["name"] = name
        if region_id:
            update_data["region_id"] = PydanticObjectId(region_id)
        if display_order is not None:
            update_data["display_order"] = display_order
        update_data["updated_at"] = datetime.utcnow()
        
        await country.update({"$set": update_data})
        await country.sync()
        logger.info(f"Country updated: {country_id}")
        return CountryController._country_to_dict(country)

    @staticmethod
    async def delete_country(country_id: str) -> Dict[str, Any]:
        """
        Delete country.
        """
        country = await Country.get(PydanticObjectId(country_id))
        if not country:
            raise HTTPException(status_code=404, detail="Country not found")
            
        await country.delete()
        logger.info(f"Country deleted: {country_id}")
        return {"message": "Country deleted successfully"}

    @staticmethod
    async def reorder_countries(country_ids: List[str]) -> Dict[str, Any]:
        """
        Reorder countries by display order.
        """
        for order, country_id in enumerate(country_ids):
            await Country.find_one(Country.id == PydanticObjectId(country_id)).update(
                {"$set": {"display_order": order, "updated_at": datetime.utcnow()}}
            )
        logger.info("Countries reordered")
        return {"message": "Countries reordered"}

    @staticmethod
    def _country_to_dict(country: Country, region_name: str = "Unknown") -> Dict[str, Any]:
        """
        Convert Country model to dictionary.
        """
        return {
            "id": str(country.id),
            "region_id": str(country.region_id),
            "region_name": region_name,
            "name": country.name,
            "display_order": country.display_order,
            "created_at": country.created_at,
            "updated_at": country.updated_at,
        }