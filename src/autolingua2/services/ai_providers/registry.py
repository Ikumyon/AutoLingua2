from __future__ import annotations

from collections.abc import Mapping
import os
from types import MappingProxyType
from typing import TYPE_CHECKING

from .base import AiProviderPlugin

if TYPE_CHECKING:
    from autolingua2.services.settings_store import AiModel


class ProviderRegistry:
    """Read-only service view of providers accepted by the entrance."""
    def __init__(self, providers: Mapping[str, AiProviderPlugin], errors: tuple[str, ...] = ()) -> None:
        self.providers: Mapping[str, AiProviderPlugin] = MappingProxyType(dict(providers))
        self.errors = errors

    def get(self, provider_id: str) -> AiProviderPlugin | None:
        return self.providers.get(provider_id)

    def get_default_models(self, provider_id: str) -> list[AiModel]:
        """指定プロバイダの推奨モデルリストを AiModel オブジェクトとして返します。"""
        from autolingua2.services.settings_store import AiModel

        provider = self.get(provider_id)
        if provider is None:
            return []
        defaults = getattr(provider, "default_models", ())
        return [
            AiModel(name=name, model=model_id, enabled=True)
            for name, model_id in defaults
        ]

    def get_env_api_key(self, provider_id: str) -> str:
        """指定プロバイダに対応する環境変数からAPIキーを取得して返します。"""
        provider = self.get(provider_id)
        if provider is None:
            return ""
        env_var = getattr(provider, "api_key_env", "")
        if not env_var:
            return ""
        return os.environ.get(env_var, "").strip()


