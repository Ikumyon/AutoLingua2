from __future__ import annotations

from dataclasses import replace
from collections.abc import Iterable

from autolingua2.adapters.base import FileAdapter
from autolingua2.ir.filter_rules import AdapterFilterConfig


def get_default_filter_config(adapter_id: str, adapters: Iterable[FileAdapter]) -> AdapterFilterConfig:
    for adapter in adapters:
        if adapter.id == adapter_id:
            return AdapterFilterConfig(rules=[replace(rule) for rule in adapter.default_filter_rules])
    return AdapterFilterConfig()
