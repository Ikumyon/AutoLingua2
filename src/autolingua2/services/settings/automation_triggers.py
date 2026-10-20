from __future__ import annotations

from dataclasses import asdict

from autolingua2.ir.automation_trigger import TriggerDefinition
from autolingua2.services.settings.settings_store import _read_settings_file, _write_settings_file


def load_triggers() -> list[TriggerDefinition]:
    values = _read_settings_file().get("automation_triggers", [])
    if not isinstance(values, list):
        raise ValueError("トリガー設定が不正です。")
    result: list[TriggerDefinition] = []
    ids: set[str] = set()
    for value in values:
        if (not isinstance(value, dict)
                or not all(isinstance(value.get(key), str) for key in ("id", "name", "source"))
                or type(value.get("enabled")) is not bool or not value["id"] or value["id"] in ids):
            raise ValueError("トリガー設定が不正です。")
        ids.add(value["id"])
        result.append(TriggerDefinition(value["id"], value["name"], value["source"], value["enabled"]))
    return result


def save_triggers(values: list[TriggerDefinition]) -> None:
    settings = _read_settings_file()
    settings["automation_triggers"] = [asdict(value) for value in values]
    _write_settings_file(settings)
