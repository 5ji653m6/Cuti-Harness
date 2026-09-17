"""
Redis connection management
"""
import redis.asyncio as aioredis
from typing import Optional
from functools import lru_cache
import logging
from urllib.parse import urlparse

from ...config import get_settings
from .stream_service import RedisStreamService

logger = logging.getLogger(__name__)

# global Redis client instances (supports two modes)
_redis_client_bytes: Optional[aioredis.Redis] = None  # bytes mode (default, compatible with existing code)
_redis_client_str: Optional[aioredis.Redis] = None    # str mode (for AccountManager and other new code)
_redis_stream_service: Optional[RedisStreamService] = None


def parse_redis_url(url: str) -> dict:
    """Parse the Redis URL."""
    parsed = urlparse(url)

    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 6379,
        "db": int(parsed.path.lstrip("/")) if parsed.path else 0,
        "password": parsed.password,
    }


async def get_redis_client(decode_responses: bool = False) -> aioredis.Redis:
    """
    Get a Redis client (singleton, supports two modes).

    Args:
        decode_responses: whether to auto-decode responses to strings
            - False: returns bytes (default, compatible with existing code like RedisStreamService)
            - True: returns str (for AccountManager and other new code, avoiding bytes conversion)

    Returns:
        a Redis client instance
    """
    global _redis_client_bytes, _redis_client_str

    settings = get_settings()
    redis_url = settings.REDIS_URL

    # return the corresponding client by mode
    if decode_responses:
        # str mode
        if _redis_client_str is None:
            try:
                redis_config = parse_redis_url(redis_url)
                _redis_client_str = aioredis.Redis(
                    host=redis_config["host"],
                    port=redis_config["port"],
                    db=redis_config["db"],
                    password=redis_config["password"],
                    decode_responses=True,  # str mode
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                )
                await _redis_client_str.ping()
                logger.info(f"✅ Redis连接成功(str模式): {redis_config['host']}:{redis_config['port']}/{redis_config['db']}")
            except Exception as e:
                logger.error(f"❌ Redis连接失败(str模式): {e}")
                raise
        return _redis_client_str
    else:
        # bytes mode (default, compatible with existing code)
        if _redis_client_bytes is None:
            try:
                redis_config = parse_redis_url(redis_url)
                _redis_client_bytes = aioredis.Redis(
                    host=redis_config["host"],
                    port=redis_config["port"],
                    db=redis_config["db"],
                    password=redis_config["password"],
                    decode_responses=False,  # bytes mode
                    socket_connect_timeout=5,
                    socket_keepalive=True,
                )
                await _redis_client_bytes.ping()
                logger.info(f"✅ Redis连接成功(bytes模式): {redis_config['host']}:{redis_config['port']}/{redis_config['db']}")
            except Exception as e:
                logger.error(f"❌ Redis连接失败(bytes模式): {e}")
                raise
        return _redis_client_bytes


async def get_redis_stream_service() -> RedisStreamService:
    """Get the Redis Stream service (singleton)."""
    return await init_redis_stream_service()


async def init_redis_stream_service():
    """Initialize the Redis Stream service (using str mode)."""
    global _redis_stream_service

    if _redis_stream_service is None:
        # use the str-mode Redis client (avoids bytes conversion)
        redis_client = await get_redis_client(decode_responses=True)
        # get the environment from config
        from ...config import get_settings
        settings = get_settings()
        environment = settings.ENVIRONMENT.value
        _redis_stream_service = RedisStreamService(redis_client, environment=environment)
        logger.info(f"✅ Redis Stream服务初始化成功: 环境={environment}")

    return _redis_stream_service


async def close_redis_client():
    """Close the Redis clients (both modes)."""
    global _redis_client_bytes, _redis_client_str, _redis_stream_service

    if _redis_client_bytes:
        await _redis_client_bytes.close()
        _redis_client_bytes = None
        logger.info("✅ Redis客户端已关闭(bytes模式)")

    if _redis_client_str:
        await _redis_client_str.close()
        _redis_client_str = None
        logger.info("✅ Redis客户端已关闭(str模式)")

    _redis_stream_service = None
