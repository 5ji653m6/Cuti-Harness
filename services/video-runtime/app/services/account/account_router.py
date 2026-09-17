"""
Account router - handles request routing, failover, and rate limiting
"""
from typing import Callable, Any
import logging

from ...models.tool_enums import ToolProvider, ToolType
from .account_manager import AccountConfigLoader
from .rate_limiter import ModelRateLimiter, RateLimitExceededError

logger = logging.getLogger(__name__)


class AccountRouter:
    """
    Account router - integrates rate-limit checking.

    Features:
    - Routes API requests to the best account (by priority and rate-limit status)
    - Integrates ModelRateLimiter for rate-limit checking
    - Supports multi-account failover (if one account is rate-limited, try the next)
    - Automatically handles exceptions and quota release

    Workflow:
    1. Load the account list from environment variables
    2. For each account (by priority):
       a. Check the rate-limit status (check_rate_limit)
       b. If it passes, acquire rate-limit quota (acquire_rate_limit)
       c. Execute the API request
       d. Update TPM usage (if applicable)
       e. Release the CONCURRENT quota (on failure or cancellation)
    3. If all accounts are rate-limited, raise RateLimitExceededError
    """

    def __init__(self, account_config_loader: AccountConfigLoader, rate_limiter: ModelRateLimiter):
        """
        Initialize the account router.

        Args:
            account_config_loader: account config loader (reads each provider's key from environment variables)
            rate_limiter: rate limiter (required)
        """
        self.account_config_loader = account_config_loader
        self.rate_limiter = rate_limiter

    def _get_provider_name(self, provider: ToolProvider) -> str:
        """
        Convert a ToolProvider enum into the provider name used in the env-var accounts.

        Args:
            provider: ToolProvider enum value

        Returns:
            the provider name (e.g. "google", "wavespeed")
        """
        provider_name_map = {
            ToolProvider.GOOGLE: "google",
            ToolProvider.WAVESPEED: "wavespeed",
            ToolProvider.SUNO: "suno",
            ToolProvider.OPENAI: "openai",
        }
        return provider_name_map.get(provider)

    async def route_tool_request(
        self,
        provider: ToolProvider,
        tool_type: ToolType,
        request_func: Callable,
        *args,
        **kwargs
    ) -> Any:
        """
        Route a tool request to the best account, considering model-level rate limiting.

        Flow:
        1. Load the account list from environment variables
        2. For each account (by priority):
           a. Check the rate-limit status
           b. If it passes, acquire rate-limit quota
           c. Execute the request
           d. Release rate-limit quota (on failure)
        3. If all accounts are rate-limited, raise an exception

        Args:
            provider: service provider (ToolProvider enum)
            tool_type: tool type (ToolType enum), required
            request_func: the actual request function, signature: async def func(api_key, *args, **kwargs)
            *args, **kwargs: other arguments passed to request_func

        Returns:
            the return value of the request function
        """
        # load the account list
        accounts_dict = await self.account_config_loader.load_accounts()
        provider_name = self._get_provider_name(provider)

        if not provider_name or provider_name not in accounts_dict:
            raise ValueError(f"Provider {provider.value} not configured")

        accounts = accounts_dict[provider_name]

        # try each account (by priority)
        for account in accounts:
            # check the rate limit
            can_proceed = await self.rate_limiter.check_rate_limit(
                provider, tool_type, account.name
            )

            if not can_proceed:
                logger.debug(
                    f"Account {account.name} rate limited for {tool_type.value}, "
                    f"trying next account"
                )
                continue

            # acquire rate-limit quota (strategies like CONCURRENT consume quota)
            acquired = await self.rate_limiter.acquire_rate_limit(
                provider, tool_type, account.name
            )

            if not acquired:
                logger.debug(
                    f"Failed to acquire rate limit for {account.name} "
                    f"({tool_type.value}), trying next account"
                )
                continue

            # execute the request; whether it succeeds, fails, or is cancelled, release the CONCURRENT quota in finally, to avoid dev-only increments without release
            # ⚠️ rate-limit quota is consumed at request start; it must be released after the request (otherwise the CONCURRENT count keeps growing)
            try:
                result = await request_func(account.api_key, *args, **kwargs)

                # if it is the Google API, extract token usage and update the TPM count
                if provider == ToolProvider.GOOGLE and hasattr(result, 'usage_metadata'):
                    usage_metadata = result.usage_metadata
                    input_tokens = usage_metadata.prompt_token_count or 0
                    await self.rate_limiter.update_tpm_usage(
                        provider, tool_type, account.name, input_tokens
                    )

                return result
            finally:
                # CONCURRENT strategy: release on task end (success/failure/cancel), otherwise the count only grows
                await self.rate_limiter.release_rate_limit(
                    provider, tool_type, account.name
                )

        # all accounts are rate-limited
        raise RateLimitExceededError(
            f"All accounts rate limited for provider {provider.value}, tool_type {tool_type.value}"
        )


# global account-router instance
_account_router = None


async def get_account_router() -> AccountRouter:
    """
    Get the account router (singleton).

    Notes:
    - AccountConfigLoader must be initialized via lifespan at app startup
    - ModelRateLimiter initializes automatically and loads rate-limit rules
    - If AccountConfigLoader is not initialized, it tries to auto-initialize (fallback strategy)

    Returns:
        an AccountRouter instance
    """
    global _account_router
    if _account_router is None:
        from .account_manager import AccountConfigLoader
        from .rate_limiter import ModelRateLimiter

        account_config_loader = AccountConfigLoader()
        # check whether AccountConfigLoader is initialized
        if not account_config_loader._initialized:
            # try auto-initialization (fallback strategy)
            # this handles the case where startup initialization failed
            logger.warning(
                "AccountConfigLoader not initialized. "
                "Attempting to initialize automatically (fallback strategy)..."
            )
            try:
                await account_config_loader.initialize()
                logger.info("✅ AccountConfigLoader auto-initialized successfully")
            except Exception as e:
                logger.error(
                    f"❌ Failed to auto-initialize AccountConfigLoader: {e}",
                    exc_info=True
                )
                raise RuntimeError(
                    "AccountConfigLoader not initialized and auto-initialization failed. "
                    "Please ensure AccountConfigLoader.initialize() is called in application lifespan. "
                    f"Error: {str(e)}"
                )

        rate_limiter = ModelRateLimiter()
        await rate_limiter.initialize()
        await rate_limiter.load_rules_from_config({"providers": {}})
        logger.info("ModelRateLimiter initialized with empty rules (environment keys)")

        _account_router = AccountRouter(account_config_loader, rate_limiter)
    return _account_router
