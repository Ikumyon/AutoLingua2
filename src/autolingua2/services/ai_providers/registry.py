from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from .base import AiProviderPlugin


class ProviderRegistry:
    """Read-only service view of providers accepted by the entrance."""
    def __init__(self, providers: Mapping[str, AiProviderPlugin], errors: tuple[str, ...] = ()) -> None:
        self.providers: Mapping[str, AiProviderPlugin] = MappingProxyType(dict(providers))
        self.errors = errors

    def get(self, provider_id: str) -> AiProviderPlugin | None:
        return self.providers.get(provider_id)

