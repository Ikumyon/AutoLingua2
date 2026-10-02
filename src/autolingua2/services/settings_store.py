from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from autolingua2.infrastructure.filesystem import PROJECT_ROOT


GROUP_TRANSLATION_TABLE = "translation_table"
GROUP_UI = "ui"
GROUP_AI = "ai"
GROUP_FILTER_RULES = "filter_rules"
KEY_COLUMN_ORDER = "column_order"
KEY_HIDDEN_COLUMNS = "hidden_columns"
KEY_UI_LANGUAGE = "language"
KEY_THEME = "theme"
KEY_ICON_THEME = "icon_theme"
DEFAULT_THEME = "system"
DEFAULT_ICON_THEME = "default"
KEY_AI_MODEL = "model"
KEY_AI_PROVIDER = "provider"
KEY_AI_PROVIDERS = "providers"
KEY_AI_API_KEY = "api_key"
KEY_AI_SELECTED_MODEL = "selected_model"
KEY_AI_MODELS = "models"
KEY_AI_SELECTED_MODELS = "selected_models"
KEY_AI_CONCURRENCY = "concurrency"
KEY_WINDOW_GEOMETRY = "window_geometry"
KEY_WINDOW_STATE = "window_state"
KEY_SPLITTER_MAIN = "splitter_main"
KEY_SPLITTER_FOCUS = "splitter_focus"
KEY_SIDEBAR_VISIBLE = "sidebar_visible"
KEY_AI_PANEL_VISIBLE = "ai_panel_visible"
SETTINGS_ENV_VAR = "AUTOLINGUA_SETTINGS_PATH"
SETTINGS_FILE_NAME = "settings.json"


@dataclass(slots=True)
class ColumnLayout:
    order: list[str]
    hidden: set[str]


def load_translation_table_columns(default_order: list[str], default_hidden: set[str] | None = None) -> ColumnLayout:
    settings = _read_settings_file()
    table_settings = settings.get(GROUP_TRANSLATION_TABLE, {})
    if not isinstance(table_settings, dict):
        table_settings = {}
    has_hidden_setting = KEY_HIDDEN_COLUMNS in table_settings
    saved_order = _string_list(table_settings.get(KEY_COLUMN_ORDER, []))
    saved_hidden = set(_string_list(table_settings.get(KEY_HIDDEN_COLUMNS, [])))

    known = set(default_order)
    order = [column_id for column_id in saved_order if column_id in known]
    order.extend(column_id for column_id in default_order if column_id not in order)
    hidden_source = saved_hidden if has_hidden_setting else (default_hidden or set())
    hidden = {column_id for column_id in hidden_source if column_id in known}

    if len(hidden) >= len(default_order):
        hidden.clear()

    return ColumnLayout(order=order, hidden=hidden)


def save_translation_table_columns(layout: ColumnLayout) -> None:
    settings = _read_settings_file()
    settings[GROUP_TRANSLATION_TABLE] = {
        KEY_COLUMN_ORDER: layout.order,
        KEY_HIDDEN_COLUMNS: sorted(layout.hidden),
    }
    _write_settings_file(settings)


DEFAULT_UI_LANGUAGE = "system"
DEFAULT_AI_PROVIDER = "openai"


@dataclass(slots=True)
class AiModel:
    name: str
    model: str
    enabled: bool = True


@dataclass(slots=True)
class AiSettings:
    provider_id: str
    models: dict[str, list[AiModel]]
    selected_models: dict[str, str] = field(default_factory=dict)
    api_keys: dict[str, str] = field(default_factory=dict)
    concurrency: int = 4


def load_ai_settings() -> AiSettings:
    group = _read_settings_file().get(GROUP_AI, {})
    if not isinstance(group, dict):
        return AiSettings(DEFAULT_AI_PROVIDER, {})

    providers_data = group.get(KEY_AI_PROVIDERS, {})
    models: dict[str, list[AiModel]] = {}
    selected_models: dict[str, str] = {}
    api_keys: dict[str, str] = {}

    if isinstance(providers_data, dict):
        for p_id, p_info in providers_data.items():
            if not isinstance(p_id, str) or not isinstance(p_info, dict):
                continue
            api_keys[p_id] = str(p_info.get(KEY_AI_API_KEY) or "").strip()
            sel = str(p_info.get(KEY_AI_SELECTED_MODEL) or "").strip()
            if sel:
                selected_models[p_id] = sel
            raw_models = p_info.get(KEY_AI_MODELS, [])
            models[p_id] = []
            seen: set[str] = set()
            if isinstance(raw_models, list):
                for entry in raw_models:
                    if isinstance(entry, dict):
                        m_id = str(entry.get("model", "")).strip()
                        name = str(entry.get("name", "")).strip() or m_id
                        enabled = entry.get("enabled", True) is True
                        if m_id and m_id not in seen:
                            models[p_id].append(AiModel(name, m_id, enabled))
                            seen.add(m_id)

    provider = group.get(KEY_AI_PROVIDER)
    concurrency = group.get(KEY_AI_CONCURRENCY, 4)
    return AiSettings(
        provider_id=provider if isinstance(provider, str) and provider else DEFAULT_AI_PROVIDER,
        models=models,
        selected_models=selected_models,
        api_keys=api_keys,
        concurrency=concurrency if type(concurrency) is int and 1 <= concurrency <= 32 else 4,
    )


def save_ai_settings(settings: AiSettings) -> None:
    data = _read_settings_file()
    group = data.get(GROUP_AI, {})
    if not isinstance(group, dict):
        group = {}
    group[KEY_AI_PROVIDER] = settings.provider_id
    group[KEY_AI_CONCURRENCY] = max(1, min(32, settings.concurrency))

    all_provider_ids = set(settings.models.keys()) | set(settings.api_keys.keys()) | set(settings.selected_models.keys())
    providers_data: dict[str, dict[str, object]] = {}
    for p_id in sorted(all_provider_ids):
        p_models = settings.models.get(p_id, [])
        p_models_list = [
            {"name": item.name.strip() or item.model.strip(), "model": item.model.strip(), "enabled": item.enabled}
            for item in p_models if item.model.strip()
        ]
        selected = settings.selected_models.get(p_id, "")
        providers_data[p_id] = {
            KEY_AI_API_KEY: settings.api_keys.get(p_id, ""),
            KEY_AI_SELECTED_MODEL: selected,
            KEY_AI_MODELS: p_models_list,
        }
    group[KEY_AI_PROVIDERS] = providers_data
    group.pop(KEY_AI_MODEL, None)
    group.pop("models", None)
    group.pop("selected_models", None)
    group.pop("api_keys", None)

    data[GROUP_AI] = group
    _write_settings_file(data)


def load_ui_language(default: str = DEFAULT_UI_LANGUAGE) -> str:
    settings = _read_settings_file()
    ui_settings = settings.get(GROUP_UI, {})
    if not isinstance(ui_settings, dict):
        return default
    language = ui_settings.get(KEY_UI_LANGUAGE)
    return str(language) if language else default


def save_ui_language(language: str) -> None:
    settings = _read_settings_file()
    ui_settings = settings.get(GROUP_UI, {})
    if not isinstance(ui_settings, dict):
        ui_settings = {}
    ui_settings[KEY_UI_LANGUAGE] = language
    settings[GROUP_UI] = ui_settings
    _write_settings_file(settings)


def load_theme_settings(default_theme: str = DEFAULT_THEME, default_icon_theme: str = DEFAULT_ICON_THEME) -> tuple[str, str]:
    settings = _read_settings_file()
    ui_settings = settings.get(GROUP_UI, {})
    if not isinstance(ui_settings, dict):
        return default_theme, default_icon_theme
    theme = ui_settings.get(KEY_THEME)
    icon_theme = ui_settings.get(KEY_ICON_THEME)
    return (str(theme) if theme else default_theme,
            str(icon_theme) if icon_theme else default_icon_theme)


def save_theme_settings(theme: str, icon_theme: str) -> None:
    settings = _read_settings_file()
    ui_settings = settings.get(GROUP_UI, {})
    if not isinstance(ui_settings, dict):
        ui_settings = {}
    ui_settings[KEY_THEME] = theme
    ui_settings[KEY_ICON_THEME] = icon_theme
    settings[GROUP_UI] = ui_settings
    _write_settings_file(settings)


@dataclass(slots=True)
class WindowLayout:
    geometry: str = ""
    state: str = ""
    splitter_main: str = ""
    splitter_focus: str = ""
    sidebar_visible: bool = True
    ai_panel_visible: bool = True


def load_window_layout() -> WindowLayout:
    settings = _read_settings_file()
    ui_settings = settings.get(GROUP_UI, {})
    if not isinstance(ui_settings, dict):
        return WindowLayout()
    return WindowLayout(
        geometry=str(ui_settings.get(KEY_WINDOW_GEOMETRY) or ""),
        state=str(ui_settings.get(KEY_WINDOW_STATE) or ""),
        splitter_main=str(ui_settings.get(KEY_SPLITTER_MAIN) or ""),
        splitter_focus=str(ui_settings.get(KEY_SPLITTER_FOCUS) or ""),
        sidebar_visible=bool(ui_settings.get(KEY_SIDEBAR_VISIBLE, True)),
        ai_panel_visible=bool(ui_settings.get(KEY_AI_PANEL_VISIBLE, True)),
    )


def save_window_layout(layout: WindowLayout) -> None:
    settings = _read_settings_file()
    ui_settings = settings.get(GROUP_UI, {})
    if not isinstance(ui_settings, dict):
        ui_settings = {}
    ui_settings[KEY_WINDOW_GEOMETRY] = layout.geometry
    ui_settings[KEY_WINDOW_STATE] = layout.state
    ui_settings[KEY_SPLITTER_MAIN] = layout.splitter_main
    ui_settings[KEY_SPLITTER_FOCUS] = layout.splitter_focus
    ui_settings[KEY_SIDEBAR_VISIBLE] = layout.sidebar_visible
    ui_settings[KEY_AI_PANEL_VISIBLE] = layout.ai_panel_visible
    settings[GROUP_UI] = ui_settings
    _write_settings_file(settings)


def load_adapter_filter_rules(adapter_id: str) -> dict[str, object]:
    settings = _read_settings_file()
    rules_group = settings.get(GROUP_FILTER_RULES, {})
    if not isinstance(rules_group, dict):
        return {}
    adapter_rules = rules_group.get(adapter_id, {})
    return adapter_rules if isinstance(adapter_rules, dict) else {}


def save_adapter_filter_rules(adapter_id: str, rules_data: dict[str, object]) -> None:
    settings = _read_settings_file()
    rules_group = settings.get(GROUP_FILTER_RULES, {})
    if not isinstance(rules_group, dict):
        rules_group = {}
    rules_group[adapter_id] = rules_data
    settings[GROUP_FILTER_RULES] = rules_group
    _write_settings_file(settings)


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return []


def _read_settings_file() -> dict[str, object]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_settings_file(settings: dict[str, object]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def settings_path() -> Path:
    override = os.environ.get(SETTINGS_ENV_VAR)
    if override:
        return Path(override)

    return PROJECT_ROOT / SETTINGS_FILE_NAME
