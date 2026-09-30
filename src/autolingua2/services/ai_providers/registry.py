from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import re
import sys

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from .base import AiProviderPlugin
from .gemini import GeminiPlugin
from .openai import OpenAIPlugin


PLUGINS_DIR = PROJECT_ROOT / "plugins" / "ai_providers"


@dataclass(slots=True)
class ProviderRegistry:
    providers: dict[str, AiProviderPlugin]
    errors: list[str]

    def get(self, provider_id: str) -> AiProviderPlugin | None:
        return self.providers.get(provider_id)


def discover_providers(plugins_dir: Path = PLUGINS_DIR) -> ProviderRegistry:
    providers: dict[str, AiProviderPlugin] = {}
    errors: list[str] = []
    for built_in in (OpenAIPlugin(), GeminiPlugin()):
        providers[built_in.id] = built_in

    if not plugins_dir.exists():
        return ProviderRegistry(providers, errors)
    for directory in sorted(plugins_dir.iterdir()):
        entry_file = directory / "plugin.py"
        if not directory.is_dir() or not entry_file.is_file():
            continue
        try:
            module_name = f"autolingua2_ai_provider_{re.sub(r'\W', '_', directory.name)}"
            spec = importlib.util.spec_from_file_location(
                module_name, entry_file, submodule_search_locations=[str(directory)]
            )
            if spec is None or spec.loader is None:
                raise ValueError("plugin.py を読み込めません")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            factory = getattr(module, "get_provider", None)
            if not callable(factory):
                raise ValueError("get_provider() がありません")
            provider = factory()
            if not isinstance(provider, AiProviderPlugin):
                raise ValueError("Provider のインターフェースが不正です")
            provider_id = getattr(provider, "id", None)
            if not isinstance(provider_id, str) or not provider_id.strip():
                raise ValueError("Provider の id が不正です")
            if provider_id in providers:
                raise ValueError(f"Provider ID が重複しています: {provider_id}")
            if not isinstance(getattr(provider, "display_name", None), str) or not provider.display_name.strip():
                raise ValueError("表示名が不正です")
            if not isinstance(getattr(provider, "api_key_env", None), str) or not provider.api_key_env.strip():
                raise ValueError("APIキー環境変数名が不正です")
            if not callable(getattr(provider, "create", None)):
                raise ValueError("create() がありません")
            providers[provider_id] = provider
        except Exception as exc:
            errors.append(f"{directory.name}: {exc}")
    return ProviderRegistry(providers, errors)
