from __future__ import annotations

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.filter_rules import AdapterFilterConfig
from autolingua2.services.settings_store import load_game_filter_rules


def get_default_filter_config(adapter: FileAdapter) -> AdapterFilterConfig:
    return AdapterFilterConfig(list(adapter.default_filter_rules))


def get_filter_config(adapter: FileAdapter, game_id: str) -> AdapterFilterConfig:
    saved = load_game_filter_rules(adapter.id, game_id)
    return get_default_filter_config(adapter) if saved is None else AdapterFilterConfig.from_dict(saved)
