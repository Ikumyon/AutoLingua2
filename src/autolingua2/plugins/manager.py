"""Host-side plugin management: explicit loading, validation, routing and lifecycle."""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import importlib
import importlib.util
import logging
from pathlib import Path
import sys
from types import MappingProxyType, ModuleType

from autolingua2.adapters.executable import ExecutableAdapter
from autolingua2.adapters.validation import validate_adapter
from autolingua2.ir.validation import required, text
from autolingua2.services.ai_providers.registry import ProviderRegistry
from autolingua2.ui.creation_contract import CreationAdapter, CreationContext
from .api import (
    HighlighterFactory,
    PluginContext,
    PluginContribution,
    SettingsPageProvider,
    GameTextPresentation,
    UIContribution,
)
from .contracts import FileAdapter, AiProviderPlugin

logger = logging.getLogger(__name__)


def _resolve(root: Path, value: object) -> Path:
    path = Path(text(value, nonempty=True))
    return (root / path).resolve()


def _python_entry(config: dict[str, object], root: Path, context: PluginContext) -> None:
    has_module, has_path = "module" in config, "path" in config
    if has_module == has_path:
        raise ValueError("Specify exactly one of module or path")
    module: ModuleType
    name: str | None = None
    if has_module:
        module = importlib.import_module(text(config["module"], nonempty=True))
    else:
        path = _resolve(root, config["path"])
        name = "autolingua2_external_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        module_name = name
        if name in sys.modules:
            raise ValueError("Python entry path was already loaded")
        spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
        if spec is None or spec.loader is None:
            raise ValueError(f"Cannot load Python entry: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module

        def unload() -> None:
            for key in tuple(sys.modules):
                if key == module_name or key.startswith(module_name + "."):
                    del sys.modules[key]

        context.on_close(unload)
        spec.loader.exec_module(module)
    entry: object = getattr(module, "register", None)
    if not callable(entry):
        raise ValueError("Python entry must define register(context)")
    entry(context)


class PluginManager:
    """Host-side composition root, never passed to plugins or lower-layer services."""
    def __init__(self, language: str) -> None:
        self._language = language
        self._contexts: dict[str, PluginContext] = {}
        self._parsers: dict[str, FileAdapter] = {}
        self._providers: dict[str, AiProviderPlugin] = {}
        self._ui: dict[str, CreationAdapter] = {}
        self._ui_contributions: dict[str, UIContribution] = {}
        self._errors: list[str] = []
        self._attempted: set[str] = set()
        self._closed = False
        self._display_callbacks: list[Callable[[str], None]] = []

    def on_display_changed(self, callback: Callable[[str], None]) -> None:
        self._display_callbacks.append(callback)

    def remove_display_listener(self, callback: Callable[[str], None]) -> None:
        if callback in self._display_callbacks:
            self._display_callbacks.remove(callback)

    def _notify_display_changed(self, plugin_id: str) -> None:
        for callback in tuple(self._display_callbacks):
            callback(plugin_id)

    @property
    def parsers(self) -> Mapping[str, FileAdapter]:
        return MappingProxyType(self._parsers)

    @property
    def ui_extensions(self) -> Mapping[str, CreationAdapter]:
        return MappingProxyType(self._ui)

    @property
    def ui_contributions(self) -> Mapping[str, UIContribution]:
        return MappingProxyType(self._ui_contributions)

    @property
    def all_settings_pages(self) -> list[SettingsPageProvider]:
        pages: list[SettingsPageProvider] = []
        for contribution in self._ui_contributions.values():
            pages.extend(contribution.settings_pages)
        return pages

    def get_highlighter_factory(self, plugin_id: str) -> HighlighterFactory | None:
        contribution = self._ui_contributions.get(plugin_id)
        if contribution is not None:
            return contribution.highlighter_factory
        return None

    def get_text_presentation(self, plugin_id: str, game_id: str) -> GameTextPresentation | None:
        contribution = self._ui_contributions.get(plugin_id)
        if contribution is not None and contribution.text_presentation is not None:
            presentation = contribution.text_presentation(game_id)
            if presentation is not None:
                if not isinstance(presentation, GameTextPresentation):
                    raise TypeError("Invalid game text presentation")
                if (presentation.settings_page_id is not None
                        and presentation.settings_page_id not in {page.id for page in contribution.settings_pages}):
                    raise ValueError("Game settings page must belong to the same plugin")
            return presentation
        return None

    @property
    def providers(self) -> ProviderRegistry:
        return ProviderRegistry(self._providers, self.errors)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(self._errors)

    def report_error(self, label: str, error: Exception) -> None:
        message = f"{label}: {type(error).__name__}: {error}"
        self._errors.append(message)
        logger.error("Plugin failure: %s", message)

    def _load(self, plugin_id: str, entry: Callable[[PluginContext], None]) -> bool:
        context = PluginContext(plugin_id, self._language, self._notify_display_changed)
        try:
            if self._closed:
                raise RuntimeError("Plugin manager is closed")
            if not plugin_id.strip() or plugin_id in self._attempted:
                raise ValueError("Empty or duplicate plugin ID")
            self._attempted.add(plugin_id)
            entry(context)
            context._accepting = False
            contribution = context._contribution
            if contribution is None:
                raise ValueError("Entry returned without registering a contribution")
            parser, provider, ui = contribution.parser, contribution.provider, contribution.ui
            if parser is None and provider is None and ui is None:
                raise ValueError("Plugin has no capabilities")
            if parser is not None:
                if not isinstance(parser, FileAdapter) or parser.id != plugin_id:
                    raise ValueError("Invalid parser contract or ID")
                validate_adapter(parser)
            if provider is not None:
                if not isinstance(provider, AiProviderPlugin) or provider.id != plugin_id:
                    raise ValueError("Invalid AI provider contract or ID")
                if not isinstance(provider.display_name, str) or not provider.display_name.strip():
                    raise ValueError("Invalid AI provider display name")
                if not isinstance(provider.api_key_env, str) or not callable(provider.create):
                    raise ValueError("Invalid AI provider metadata")

            creation_adapter: CreationAdapter | None = None
            ui_contribution: UIContribution | None = None

            if ui is not None:
                if not isinstance(ui, UIContribution):
                    raise ValueError("Invalid UI extension contract")
                ui_contribution = ui
                creation_adapter = ui.creation_panel
                if ui.highlighter_factory is not None and not callable(ui.highlighter_factory):
                    raise ValueError("Invalid highlighter factory")
                if ui.text_presentation is not None and not callable(ui.text_presentation):
                    raise ValueError("Invalid game presentation provider")
                if creation_adapter is not None and parser is None:
                    raise ValueError("Project creation UI requires a parser contribution")
                page_ids = {page.id for page in self.all_settings_pages}
                for page in ui.settings_pages:
                    if not isinstance(page, SettingsPageProvider) or not page.id or page.id in page_ids:
                        raise ValueError("Invalid or duplicate settings page ID")
                    page_ids.add(page.id)
                if (parser is None and provider is None and creation_adapter is None
                        and not ui.settings_pages and ui.text_presentation is None
                        and ui.highlighter_factory is None):
                    raise ValueError("Plugin has no capabilities")

                if creation_adapter is not None and (not isinstance(creation_adapter, CreationAdapter) or any(
                    not callable(getattr(creation_adapter, name, None)) for name in (
                        "create_creation_panel", "on_paths_dropped", "on_game_selected",
                        "format_target_path_label", "dispose_creation_panel",
                    )
                )):
                    raise ValueError("Invalid CreationAdapter contract")

            context._change_language(self._language)
            # Publish only after validation and initial language callbacks succeed.
            self._contexts[plugin_id] = context
            if parser is not None:
                self._parsers[plugin_id] = parser
            if provider is not None:
                self._providers[plugin_id] = provider
            if creation_adapter is not None:
                self._ui[plugin_id] = creation_adapter
            if ui_contribution is not None:
                self._ui_contributions[plugin_id] = ui_contribution
            return True
        except Exception as exc:
            self.report_error(plugin_id, exc)
            try:
                context._close()
            except Exception as close_error:
                self.report_error(plugin_id, close_error)
            return False

    def context(self, plugin_id: str) -> PluginContext:
        return self._contexts[plugin_id]

    def bind_creation(self, plugin_id: str, actions: CreationContext | None) -> None:
        self.context(plugin_id)._creation = actions

    def change_language(self, language: str) -> None:
        self._language = language
        for plugin_id, context in tuple(self._contexts.items()):
            try:
                context._change_language(language)
            except Exception as exc:
                self.report_error(plugin_id, exc)

    def close(self) -> None:
        self._closed = True
        for plugin_id, context in reversed(tuple(self._contexts.items())):
            try:
                context._close()
            except Exception as exc:
                self.report_error(plugin_id, exc)
        self._contexts.clear()
        self._parsers.clear()
        self._providers.clear()
        self._ui.clear()
        self._ui_contributions.clear()
        self._display_callbacks.clear()


    def _load_configured(self, item: dict[str, object], root: Path) -> bool:
        plugin_id = text(required(item, "id"), nonempty=True)
        kind = text(required(item, "kind"), nonempty=True)

        def enter(context: PluginContext) -> None:
            if kind == "python":
                _python_entry(item, root, context)
            elif kind == "executable":
                adapter = ExecutableAdapter(_resolve(root, required(item, "manifest")))
                context.register(PluginContribution(adapter.id, parser=adapter))
            else:
                raise ValueError(f"Unknown plugin kind: {kind}")

        return self._load(plugin_id, enter)
