"""
Cache service - Redis caching operations.
"""
import json
from typing import Any, Optional
from loguru import logger
from app.config.redis import get_redis


class CacheService:
    """Service for caching operations."""
    
    @staticmethod
    async def get(key: str) -> Optional[Any]:
        """
        Get value from cache.
        """
        redis = get_redis()
        if not redis:
            return None
            
        try:
            value = await redis.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            
        return None
    
    @staticmethod
    async def set(key: str, value: Any, ttl: int = 3600) -> bool:
        """
        Set value in cache.
        """
        redis = get_redis()
        if not redis:
            return False
            
        try:
            await redis.setex(key, ttl, json.dumps(value, default=str))
            return True
        except Exception as e:
            logger.error(f"Cache set error: {e}")
            return False
    
    @staticmethod
    async def delete(key: str) -> bool:
        """
        Delete value from cache.
        """
        redis = get_redis()
        if not redis:
            return False
            
        try:
            await redis.delete(key)
            return True
        except Exception as e:
            logger.error(f"Cache delete error: {e}")
            return False
    
    @staticmethod
    async def clear_pattern(pattern: str) -> int:
        """
        Clear all keys matching pattern.
        """
        redis = get_redis()
        if not redis:
            return 0
            
        try:
            keys = await redis.keys(pattern)
            if keys:
                await redis.delete(*keys)
                return len(keys)
        except Exception as e:
            logger.error(f"Cache clear error: {e}")
            
        return 0
    
    @staticmethod
    async def remember(key: str, callback, ttl: int = 3600) -> Any:
        """
        Get from cache or execute callback and cache result.
        """
        # Try to get from cache
        cached = await CacheService.get(key)
        if cached is not None:
            return cached
            
        # Execute callback
        result = await callback()
        
        # Cache result
        await CacheService.set(key, result, ttl)
        
        return result
    
    @staticmethod
    async def invalidate_pattern(pattern: str) -> int:
        """
        Invalidate all cache keys matching pattern.
        """
        return await CacheService.clear_pattern(pattern)