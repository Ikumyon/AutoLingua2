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
from autolingua2.ui.creation_contract import CreationActions, CreationAdapter
from .api import PluginContext, PluginContribution
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
        self._errors: list[str] = []
        self._attempted: set[str] = set()
        self._closed = False

    @property
    def parsers(self) -> Mapping[str, FileAdapter]:
        return MappingProxyType(self._parsers)

    @property
    def ui_extensions(self) -> Mapping[str, CreationAdapter]:
        return MappingProxyType(self._ui)

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
        context = PluginContext(plugin_id, self._language)
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
            if ui is not None and parser is None:
                raise ValueError("Project creation UI requires a parser contribution")
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
            if ui is not None and (not isinstance(ui, CreationAdapter) or any(
                not callable(getattr(ui, name, None)) for name in (
                    "create_creation_panel", "on_paths_dropped", "on_game_selected",
                    "format_target_path_label", "dispose_creation_panel",
                )
            )):
                raise ValueError("Invalid UI extension contract")
            context._change_language(self._language)
            # Publish only after validation and initial language callbacks succeed.
            self._contexts[plugin_id] = context
            if parser is not None:
                self._parsers[plugin_id] = parser
            if provider is not None:
                self._providers[plugin_id] = provider
            if ui is not None:
                self._ui[plugin_id] = ui
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

    def bind_creation(self, plugin_id: str, actions: CreationActions | None) -> None:
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
