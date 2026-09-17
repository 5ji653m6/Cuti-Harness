"""Compatibility module alias for the provider integration."""

import sys

from app.integrations.providers import provider_bridge as _implementation

sys.modules[__name__] = _implementation
