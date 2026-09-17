"""Load provider API keys from process environment."""
from typing import Dict, List
from dataclasses import dataclass
import logging
import os

from ...config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class Account:
    """One provider key. Rate limits live on ModelRateLimiter."""

    provider: str
    name: str
    api_key: str
    priority: int = 0


class AccountConfigLoader:
    """Singleton that reads OPENAI / WaveSpeed / Suno keys from env."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, "_initialized"):
            self.redis = None
            self._initialized = False
            self._env_prefix = None

    async def initialize(self):
        if self._initialized:
            return
        self.redis = None
        self._env_prefix = self._get_env_prefix()
        self._initialized = True
        logger.info("AccountConfigLoader initialized from environment keys")

    async def shutdown(self):
        if not self._initialized:
            return
        self.redis = None
        self._initialized = False
        logger.info("AccountConfigLoader: Shutdown complete")

    def _get_env_prefix(self) -> str:
        settings = get_settings()
        env = settings.ENVIRONMENT.value
        return {
            "local": "local",
            "development": "dev",
            "production": "prod",
        }.get(env, "dev")

    _ENV_KEY_MAP = {
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "wavespeed": "WAVESPEED_API_KEY",
        "suno": "SUNO_API_KEY",
        "pollo": "POLLO_API_KEY",
    }

    def _build_config_from_env(self) -> dict:
        providers = {}
        for provider, env_name in self._ENV_KEY_MAP.items():
            api_key = os.getenv(env_name)
            if api_key:
                providers[provider] = {
                    "accounts": [
                        {
                            "name": f"{provider}-env",
                            "api_key": api_key,
                            "priority": 100,
                            "status": "active",
                        }
                    ]
                }
        return {"providers": providers}

    async def load_accounts(self) -> Dict[str, List[Account]]:
        return self._parse_accounts_from_config(self._build_config_from_env())

    async def _load_accounts_from_appconfig(self) -> Dict[str, List[Account]]:
        """Compatibility alias used by older callers and tests."""
        return await self.load_accounts()

    def _parse_accounts_from_config(self, config: dict) -> Dict[str, List[Account]]:
        accounts: Dict[str, List[Account]] = {}
        for provider_name, provider_config in config.get("providers", {}).items():
            accounts[provider_name] = []
            for acc_config in provider_config.get("accounts", []):
                status = acc_config.get("status", "active")
                if status != "active":
                    logger.debug(
                        "Skipping account %s with status: %s",
                        acc_config.get("name"),
                        status,
                    )
                    continue
                api_key = acc_config.get("api_key")
                if not api_key:
                    logger.warning("API key not found for %s", acc_config.get("name"))
                    continue
                accounts[provider_name].append(
                    Account(
                        provider=provider_name,
                        name=acc_config["name"],
                        api_key=api_key,
                        priority=acc_config.get("priority", 0),
                    )
                )
        for provider in accounts:
            accounts[provider].sort(key=lambda item: item.priority, reverse=True)
        return accounts
