"""
API rate limiter - throttles per model

Features:
- Controls API call rate (by Provider + Model + Account)
- Supports multiple strategies: RPM, TPM, RPD, FIXED_WINDOW, CONCURRENT
- Supports shared limits (e.g. WaveSpeed's Images/min, Videos/min)
- Rate-limit rules are injected by the caller; the env-var account path uses empty rules (a single key needs no cross-account limiting)

Difference from worker/rate_limiter.py:
- worker/rate_limiter: controls worker task concurrency (shared by all workers)
- account/rate_limiter: controls API-call rate limiting (per model)
"""
import time
import uuid
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from ...models.tool_enums import ToolProvider, ToolType
from ...config import get_settings

logger = logging.getLogger(__name__)


def _get_env_prefix_for_clear() -> str:
    """Return the environment prefix (matches ModelRateLimiter._get_env_prefix)."""
    settings = get_settings()
    env = settings.ENVIRONMENT.value
    env_prefix_map = {
        "local": "local",
        "development": "dev",
        "production": "prod"
    }
    return env_prefix_map.get(env, "dev")


async def clear_wavespeed_concurrent_limits(
    redis=None,
    env_prefix: Optional[str] = None
) -> int:
    """
    Clear WaveSpeed's CONCURRENT rate-limit counters (call on shutdown to avoid leftovers on next start).
    Uses Redis SCAN to match cuti-videoagent:{env_prefix}:ratelimit:wavespeed:*:concurrent and delete them.

    Args:
        redis: Redis client (fetched temporarily if None; pass a held client when calling before shutdown)
        env_prefix: environment prefix, e.g. local/dev/prod (derived from get_settings() if None)

    Returns:
        number of keys deleted
    """
    if redis is None:
        from ..redis.connection import get_redis_client

        redis = await get_redis_client(decode_responses=True)
    if env_prefix is None:
        env_prefix = _get_env_prefix_for_clear()
    pattern = f"cuti-videoagent:{env_prefix}:ratelimit:wavespeed:*:concurrent"
    deleted = 0
    async for key in redis.scan_iter(match=pattern):
        await redis.delete(key)
        deleted += 1
    if deleted:
        logger.info("Cleared WaveSpeed CONCURRENT rate limit keys: %d keys (pattern=%s)", deleted, pattern)
    return deleted


class RateLimitStrategy(str, Enum):
    """
    Rate-limit strategy enum.

    Supported strategies:
    - RPM: Requests Per Minute (sliding window, 60s)
    - TPM: Tokens Per Minute (sliding window, 60s, input tokens only)
    - RPD: Requests Per Day (sliding window, 24h)
    - FIXED_WINDOW: fixed window (configurable window size, e.g. Suno's 3s)
    - CONCURRENT: number of concurrent tasks (tasks running simultaneously)
    """
    RPM = "RPM"
    TPM = "TPM"
    RPD = "RPD"
    FIXED_WINDOW = "FIXED_WINDOW"
    CONCURRENT = "CONCURRENT"


@dataclass
class RateLimitRule:
    """
    Rate-limit rule.

    Attributes:
    - tool_type: tool type (model)
    - strategy: rate-limit strategy
    - limit: limit value
    - window_seconds: time window (used by RPM/TPM/RPD/FIXED_WINDOW; 0 for CONCURRENT)
    - shared_key: shared rate-limit key (e.g. WaveSpeed's "images", "videos", "all")

    Notes:
    - A model may have multiple rate-limit rules (e.g. RPM + TPM + CONCURRENT)
    - shared_key is used for shared limiting (multiple models share the same limit key)
    """
    tool_type: ToolType
    strategy: RateLimitStrategy
    limit: int
    window_seconds: int
    shared_key: Optional[str] = None


class RateLimitExceededError(Exception):
    """
    Rate-limit-exceeded exception.

    Raised when all accounts have hit their rate limits.
    """
    pass


class ModelRateLimiter:
    """
    API rate limiter - throttles per model.

    Features:
    - Controls API call rate (by Provider + Model + Account)
    - Supports multiple strategies: RPM, TPM, RPD, FIXED_WINDOW, CONCURRENT
    - Supports shared limits (e.g. WaveSpeed's Images/min, Videos/min)
    - Rate-limit rules are injected by load_rules_from_config; the env-var account path uses empty rules

    Usage example:
        rate_limiter = ModelRateLimiter()
        await rate_limiter.initialize()
        await rate_limiter.load_rules_from_config(config)

        # Check rate limit
        can_proceed = await rate_limiter.check_rate_limit(
            ToolProvider.GOOGLE, ToolType.GEMINI_2_5_FLASH_IMAGE, "google-main"
        )

        # Acquire quota
        acquired = await rate_limiter.acquire_rate_limit(...)

        # Release after the request (only CONCURRENT needs this)
        await rate_limiter.release_rate_limit(...)
    """

    def __init__(self, redis_client=None, env_prefix: Optional[str] = None):
        self.redis = redis_client
        self.env_prefix = env_prefix or self._get_env_prefix()
        self._rules_cache: Dict[str, List[RateLimitRule]] = {}  # each model may have multiple rules

    def _get_env_prefix(self) -> str:
        """
        Return the environment prefix (used as a Redis key prefix for environment isolation).

        Returns:
            environment prefix ("local", "dev", "prod")
        """
        settings = get_settings()
        env = settings.ENVIRONMENT.value
        env_prefix_map = {
            "local": "local",
            "development": "dev",
            "production": "prod"
        }
        return env_prefix_map.get(env, "dev")

    async def initialize(self):
        """No-op: environment-key path does not connect Redis for rate-limit rules."""
        logger.info("ModelRateLimiter initialized without Redis (environment keys)")
        return

    async def load_rules_from_config(self, config: dict):
        """
        Load rate-limit rules (the env-var account path passes empty providers).

        Config format:
        {
            "providers": {
                "google": {
                    "rate_limits": {
                        "gemini-2.5-flash-image": [
                            {
                                "strategy": "RPM",
                                "limit": 500,
                                "window_seconds": 60
                            },
                            {
                                "strategy": "TPM",
                                "limit": 500000,
                                "window_seconds": 60
                            }
                        ]
                    }
                },
                "wavespeed": {
                    "rate_limits": {
                        "seedream-v4.5": [
                            {
                                "strategy": "RPM",
                                "limit": 500,
                                "window_seconds": 60,
                                "shared_key": "images"
                            },
                            {
                                "strategy": "CONCURRENT",
                                "limit": 100,
                                "window_seconds": 0,
                                "shared_key": "all"
                            }
                        ]
                    }
                }
            }
        }

        Args:
            config: provider config dict (environment path passes empty providers)
        """
        self._rules_cache.clear()

        for provider_name, provider_config in config.get("providers", {}).items():
            rate_limits = provider_config.get("rate_limits", {})

            for tool_type_str, rules_config in rate_limits.items():
                # Convert the string to a ToolType
                try:
                    tool_type = ToolType(tool_type_str)
                except ValueError:
                    logger.warning(f"Unknown tool_type: {tool_type_str}, skipping")
                    continue

                # Convert provider_name to a ToolProvider
                try:
                    provider = ToolProvider(provider_name)
                except ValueError:
                    logger.warning(f"Unknown provider: {provider_name}, skipping")
                    continue

                # Parse the rule (may be a single dict or a list)
                if isinstance(rules_config, dict):
                    rules_config = [rules_config]

                rules = []
                for rule_config in rules_config:
                    try:
                        strategy = RateLimitStrategy(rule_config["strategy"])
                        rule = RateLimitRule(
                            tool_type=tool_type,
                            strategy=strategy,
                            limit=rule_config["limit"],
                            window_seconds=rule_config.get("window_seconds", 0),
                            shared_key=rule_config.get("shared_key")
                        )
                        rules.append(rule)
                    except (KeyError, ValueError) as e:
                        logger.warning(f"Invalid rate limit rule for {tool_type_str}: {e}")
                        continue

                if rules:
                    key = f"{provider.value}:{tool_type.value}"
                    self._rules_cache[key] = rules
                    logger.debug(f"Loaded {len(rules)} rate limit rules for {key}")

    def _get_rules(self, provider: ToolProvider, tool_type: ToolType) -> List[RateLimitRule]:
        """
        Get rate-limit rules (may return multiple).

        A model may have multiple rate-limit rules, e.g.:
        - RPM = 500 (500 requests per minute)
        - TPM = 500K (500K tokens per minute)
        - CONCURRENT = 100 (100 concurrent tasks)

        Args:
            provider: service provider
            tool_type: tool type

        Returns:
            list of rate-limit rules (may be empty)
        """
        key = f"{provider.value}:{tool_type.value}"
        rules = self._rules_cache.get(key, [])
        return rules if isinstance(rules, list) else [rules] if rules else []

    def _get_rpm_key(self, provider: ToolProvider, tool_type: ToolType, account_name: str) -> str:
        """Return the RPM key (model level)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:{tool_type.value}:{account_name}:rpm"

    def _get_shared_rpm_key(self, provider: ToolProvider, shared_key: str, account_name: str) -> str:
        """Return the shared RPM key (for WaveSpeed shared limits, e.g. images/videos)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:shared:{shared_key}:{account_name}:rpm"

    def _get_tpm_key(self, provider: ToolProvider, tool_type: ToolType, account_name: str) -> str:
        """Return the TPM key (model level)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:{tool_type.value}:{account_name}:tpm"

    def _get_rpd_key(self, provider: ToolProvider, tool_type: ToolType, account_name: str) -> str:
        """Return the RPD key (model level)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:{tool_type.value}:{account_name}:rpd"

    def _get_fixed_window_key(self, provider: ToolProvider, tool_type: ToolType, account_name: str) -> str:
        """Return the FIXED_WINDOW key (model level)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:{tool_type.value}:{account_name}:fixed"

    def _get_concurrent_key(self, provider: ToolProvider, tool_type: ToolType, account_name: str) -> str:
        """Return the CONCURRENT key (model level)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:{tool_type.value}:{account_name}:concurrent"

    def _get_shared_concurrent_key(self, provider: ToolProvider, shared_key: str, account_name: str) -> str:
        """Return the shared CONCURRENT key (for WaveSpeed shared limits, e.g. all)."""
        return f"cuti-videoagent:{self.env_prefix}:ratelimit:{provider.value}:shared:{shared_key}:{account_name}:concurrent"

    async def check_rate_limit(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str
    ) -> bool:
        """
        Check whether the rate limit is exceeded (check only, does not consume quota).

        Args:
            provider: service provider
            tool_type: tool type (model)
            account_name: account name

        Returns:
            True: may proceed with the request
            False: rate limit exceeded
        """
        rules = self._get_rules(provider, tool_type)
        if not rules:
            return True  # no rules, allow through

        # Strategy-check function mapping
        check_funcs = {
            RateLimitStrategy.RPM: self._check_rpm,
            RateLimitStrategy.TPM: self._check_tpm,
            RateLimitStrategy.RPD: self._check_rpd,
            RateLimitStrategy.FIXED_WINDOW: self._check_fixed_window,
            RateLimitStrategy.CONCURRENT: self._check_concurrent,
        }

        # Check all rules; all must pass
        for rule in rules:
            check_func = check_funcs.get(rule.strategy)
            if check_func and not await check_func(provider, tool_type, account_name, rule):
                return False

        return True

    async def acquire_rate_limit(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str
    ) -> bool:
        """
        Acquire rate-limit quota (atomic operation).

        Flow:
        1. Check all rules first (fail fast)
        2. If all pass, acquire quota (atomic operation)

        Args:
            provider: service provider
            tool_type: tool type (model)
            account_name: account name

        Returns:
            True: quota acquired successfully
            False: rate limit exceeded or acquisition failed
        """
        rules = self._get_rules(provider, tool_type)
        if not rules:
            return True  # no rules, allow through

        # Strategy-check function mapping
        check_funcs = {
            RateLimitStrategy.RPM: self._check_rpm,
            RateLimitStrategy.TPM: self._check_tpm,
            RateLimitStrategy.RPD: self._check_rpd,
            RateLimitStrategy.FIXED_WINDOW: self._check_fixed_window,
            RateLimitStrategy.CONCURRENT: self._check_concurrent,
        }

        # Check all rules first (fail fast)
        for rule in rules:
            check_func = check_funcs.get(rule.strategy)
            if check_func and not await check_func(provider, tool_type, account_name, rule):
                return False

        # Strategy-acquire function mapping (TPM does not consume quota at acquire time)
        acquire_funcs = {
            RateLimitStrategy.RPM: self._acquire_rpm,
            RateLimitStrategy.RPD: self._acquire_rpd,
            RateLimitStrategy.FIXED_WINDOW: self._acquire_fixed_window,
            RateLimitStrategy.CONCURRENT: self._acquire_concurrent,
        }

        # All checks passed; acquire quota (atomic operation)
        for rule in rules:
            acquire_func = acquire_funcs.get(rule.strategy)
            if acquire_func and not await acquire_func(provider, tool_type, account_name, rule):
                return False
            # TPM does not consume quota at acquire time; updated after the request completes

        return True

    async def release_rate_limit(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str
    ):
        """
        Release rate-limit quota (unified interface; internally decides whether release is needed based on strategy).

        Strategy categories:
        - CONCURRENT: needs release (based on running state, not a time window)
        - RPM/TPM/RPD/FIXED_WINDOW: no release needed (time-window based, expires automatically)

        Call scenarios:
        - Task completes normally
        - Task fails (API error, network error, etc.)
        - Task is cancelled (user cancel, timeout cancel, etc.)

        Notes:
        - The implementation is idempotent (safe to call multiple times)
        - Must be called in try-finally so it releases even on exceptions

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
        """
        rules = self._get_rules(provider, tool_type)
        for rule in rules:
            # Only the CONCURRENT strategy needs release
            if rule.strategy == RateLimitStrategy.CONCURRENT:
                # Pick a different key depending on whether shared_key is set
                key = (self._get_shared_concurrent_key(provider, rule.shared_key, account_name)
                       if rule.shared_key
                       else self._get_concurrent_key(provider, tool_type, account_name))

                # Set TTL to the max task execution time (consistent with acquire)
                max_task_duration = 3600

                # Use a Lua script for atomicity and to prevent the counter from going negative
                # Also refresh TTL (when counter > 0) so TTL stays valid as long as tasks are running
                lua_script = """
                local key = KEYS[1]
                local ttl = tonumber(ARGV[1])
                local count = redis.call('GET', key) or 0
                count = tonumber(count)

                if count > 0 then
                    redis.call('DECR', key)
                    -- If the counter > 0 after release, refresh TTL (other tasks are still running)
                    local new_count = redis.call('GET', key) or 0
                    if tonumber(new_count) > 0 then
                        redis.call('EXPIRE', key, ttl)
                    end
                    return 1
                else
                    -- Already 0 or negative; do nothing (idempotency)
                    return 0
                end
                """

                await self.redis.eval(lua_script, 1, key, max_task_duration)

    async def update_tpm_usage(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        input_tokens: int
    ) -> bool:
        """
        Update TPM usage (call after the request completes).

        When to call:
        - After the API request completes
        - Update the count based on the input tokens actually used

        Notes:
        - Input tokens only, no output tokens
        - Must be called after the request completes, since token counts are only known after the API returns

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            input_tokens: number of input tokens actually used

        Returns:
            True: update succeeded
        """
        rules = self._get_rules(provider, tool_type)
        for rule in rules:
            if rule.strategy == RateLimitStrategy.TPM:
                await self._update_tpm_count(provider, tool_type, account_name, rule, input_tokens)
        return True

    # ==================== Per-strategy implementations ====================

    async def _check_rpm(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Check RPM rate limit (sliding window, 60s).

        How it works:
        - Store request records in a Redis Sorted Set
        - Score = request timestamp (seconds), Value = request ID
        - Clean up expired records (score < now - 60s)
        - Count requests in the current window

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: not over the limit
            False: over the limit
        """
        # Pick a different key depending on whether shared_key is set
        key = (self._get_shared_rpm_key(provider, rule.shared_key, account_name)
               if rule.shared_key
               else self._get_rpm_key(provider, tool_type, account_name))

        now = int(time.time())
        window_start = now - rule.window_seconds

        # Clean up expired requests (score < window_start)
        await self.redis.zremrangebyscore(key, 0, window_start)

        # Get the request count in the current window
        count = await self.redis.zcard(key)
        return count < rule.limit

    async def _acquire_rpm(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Acquire RPM rate-limit quota (atomic operation).

        Use a Lua script for atomicity:
        1. Clean up expired requests
        2. Check the current request count
        3. If under the limit, add the new request

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: quota acquired successfully
            False: over the limit or acquisition failed
        """
        key = (self._get_shared_rpm_key(provider, rule.shared_key, account_name)
               if rule.shared_key
               else self._get_rpm_key(provider, tool_type, account_name))

        now = int(time.time())
        request_id = str(uuid.uuid4())

        lua_script = """
        local key = KEYS[1]
        local window = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local request_id = ARGV[4]

        -- Clean up expired requests (score < now - window)
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- Get the request count in the current window
        local count = redis.call('ZCARD', key)

        -- If under the limit, add the new request
        if count < limit then
            redis.call('ZADD', key, now, request_id)  -- score=timestamp, value=request ID
            redis.call('EXPIRE', key, window)  -- set expiration
            return 1
        else
            return 0
        end
        """

        result = await self.redis.eval(
            lua_script, 1, key, rule.window_seconds, rule.limit, now, request_id
        )
        return result == 1

    async def _check_tpm(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Check TPM rate limit (sliding window, 60s, input tokens only).

        How it works:
        - Store token-usage records in a Redis Sorted Set
        - Score = request timestamp (seconds), Value = token count (string)
        - Clean up expired records and sum all token counts in the current window

        Notes:
        - Can only check already-used tokens; cannot predict how many a new request will use
        - Actual token counts are updated via update_tpm_usage after the request completes

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: not over the limit (conservative check)
            False: over the limit
        """
        key = self._get_tpm_key(provider, tool_type, account_name)
        now = int(time.time())
        window_start = now - rule.window_seconds

        # Clean up expired records
        await self.redis.zremrangebyscore(key, 0, window_start)

        # Sum all token counts in the current window
        total_tokens = 0
        records = await self.redis.zrangebyscore(key, window_start, now, withscores=True)
        for token_count_str, _ in records:
            total_tokens += int(token_count_str)

        return total_tokens < rule.limit

    async def _update_tpm_count(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule,
        token_count: int
    ):
        """
        Update the TPM count (call after the request completes; input tokens only).

        When to call:
        - After the API request completes
        - Update the count based on the input tokens actually used

        How it works:
        - Clean up expired records
        - Add a new token-usage record (score=current time, value=token count)

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule
            token_count: number of input tokens actually used
        """
        key = self._get_tpm_key(provider, tool_type, account_name)
        now = int(time.time())

        lua_script = """
        local key = KEYS[1]
        local token_count = tonumber(ARGV[1])
        local now = tonumber(ARGV[2])
        local window = tonumber(ARGV[3])

        -- Clean up expired records
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- Add a new token-usage record (score=timestamp, value=token count)
        redis.call('ZADD', key, now, token_count)
        redis.call('EXPIRE', key, window)

        return 1
        """

        await self.redis.eval(lua_script, 1, key, token_count, now, rule.window_seconds)

    async def _check_rpd(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Check RPD rate limit (sliding window, 24h).

        How it works: same as RPM, but the window is 24 hours (86400s).

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: not over the limit
            False: over the limit
        """
        key = self._get_rpd_key(provider, tool_type, account_name)
        now = int(time.time())
        window_start = now - rule.window_seconds

        # Clean up expired requests (score < window_start)
        await self.redis.zremrangebyscore(key, 0, window_start)

        # Get the request count in the current window
        count = await self.redis.zcard(key)
        return count < rule.limit

    async def _acquire_rpd(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Acquire RPD rate-limit quota (sliding window, 24h).

        How it works: same as RPM, but the window is 24 hours (86400s).

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: quota acquired successfully
            False: over the limit or acquisition failed
        """
        key = self._get_rpd_key(provider, tool_type, account_name)
        now = int(time.time())
        request_id = str(uuid.uuid4())

        lua_script = """
        local key = KEYS[1]
        local window = tonumber(ARGV[1])
        local limit = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local request_id = ARGV[4]

        -- Clean up expired requests (score < now - window)
        redis.call('ZREMRANGEBYSCORE', key, 0, now - window)

        -- Get the request count in the current window
        local count = redis.call('ZCARD', key)

        -- If under the limit, add the new request
        if count < limit then
            redis.call('ZADD', key, now, request_id)  -- score=timestamp, value=request ID
            redis.call('EXPIRE', key, window)  -- set expiration
            return 1
        else
            return 0
        end
        """

        result = await self.redis.eval(
            lua_script, 1, key, rule.window_seconds, rule.limit, now, request_id
        )
        return result == 1

    async def _check_fixed_window(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Check fixed-window rate limit.

        How it works:
        - Implement a fixed window with a Redis counter + TTL
        - Window size is set by window_seconds (e.g. Suno's 3s)
        - The counter resets automatically when the TTL expires

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: not over the limit
            False: over the limit
        """
        key = self._get_fixed_window_key(provider, tool_type, account_name)
        count = await self.redis.get(key)
        count = int(count) if count else 0
        return count < rule.limit

    async def _acquire_fixed_window(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Acquire fixed-window rate-limit quota (atomic operation).

        How it works:
        - Use a Lua script for atomicity
        - INCR the counter
        - If count == 1, set TTL (window resets automatically on expiry)
        - If count <= limit, return success
        - If count > limit, roll back (DECR) and return failure

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: quota acquired successfully
            False: over the limit or acquisition failed
        """
        key = self._get_fixed_window_key(provider, tool_type, account_name)

        lua_script = """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local ttl = tonumber(ARGV[2])

        -- Counter +1
        local count = redis.call('INCR', key)

        -- If first time (count == 1), set expiration
        if count == 1 then
            redis.call('EXPIRE', key, ttl)
        end

        -- Check whether over the limit
        if count <= limit then
            return 1  -- success
        else
            redis.call('DECR', key)  -- roll back
            return 0  -- failure
        end
        """

        result = await self.redis.eval(
            lua_script, 1, key, rule.limit, rule.window_seconds
        )
        return result == 1

    async def _check_concurrent(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Check concurrency rate limit.

        How it works:
        - Use a Redis counter to store the number of currently running tasks
        - Check whether the current count is below the limit

        Notes:
        - Based on running state, not a time window
        - release_rate_limit must be called to release quota when a task finishes

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: not over the limit
            False: over the limit
        """
        key = (self._get_shared_concurrent_key(provider, rule.shared_key, account_name)
               if rule.shared_key
               else self._get_concurrent_key(provider, tool_type, account_name))

        count = await self.redis.get(key)
        count = int(count) if count else 0
        return count < rule.limit

    async def _acquire_concurrent(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        account_name: str,
        rule: RateLimitRule
    ) -> bool:
        """
        Acquire concurrency rate-limit quota (atomic operation).

        How it works:
        - Use a Lua script for atomicity
        - Check the current count; INCR if under the limit
        - Refresh TTL on every acquire (so TTL stays valid as long as tasks are running)

        TTL mechanism:
        - TTL = 3600s (1 hour) as a safety net to prevent counter leaks
        - Multi-user, multi-task scenarios: refresh uniformly on acquire/release, no per-task refresh needed

        Args:
            provider: service provider
            tool_type: tool type
            account_name: account name
            rule: rate-limit rule

        Returns:
            True: quota acquired successfully
            False: over the limit or acquisition failed
        """
        key = (self._get_shared_concurrent_key(provider, rule.shared_key, account_name)
               if rule.shared_key
               else self._get_concurrent_key(provider, tool_type, account_name))

        # Set TTL to the max task execution time (1 hour) as a safety net
        max_task_duration = 3600

        lua_script = """
        local key = KEYS[1]
        local limit = tonumber(ARGV[1])
        local ttl = tonumber(ARGV[2])

        local count = redis.call('GET', key) or 0
        count = tonumber(count)

        if count < limit then
            redis.call('INCR', key)
            -- Refresh TTL on every acquire so TTL stays valid as long as tasks are running
            -- Multi-user, multi-task scenarios: refresh uniformly on acquire/release, no per-task refresh needed
            redis.call('EXPIRE', key, ttl)
            return 1
        else
            return 0
        end
        """

        result = await self.redis.eval(lua_script, 1, key, rule.limit, max_task_duration)
        return result == 1
