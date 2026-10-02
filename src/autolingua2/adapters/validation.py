from __future__ import annotations

from .base import FileAdapter


def validate_adapter(adapter: FileAdapter) -> None:
    for name in ("id", "name", "suffixes", "supported_games", "supported_languages", "default_filter_rules"):
        if not hasattr(adapter, name):
            raise ValueError(f"Missing adapter attribute: {name}")
    if not isinstance(adapter.id, str) or not adapter.id.strip():
        raise ValueError("Adapter ID must be a nonempty string")
    for name in ("can_load", "load", "save", "output_name", "detect_source_language",
                 "filter_source_files"):
        if not callable(getattr(adapter, name, None)):
            raise ValueError(f"Missing adapter method: {name}")
    language_codes: set[str] = set()
    for code, name in adapter.supported_languages:
        if not code.strip() or not name.strip() or code in language_codes:
            raise ValueError("Invalid or duplicate supported language")
        language_codes.add(code)
    if not language_codes:
        raise ValueError("At least one supported language is required")
    if not adapter.supported_games:
        raise ValueError("At least one game/format profile is required")
    ids: set[str] = set()
    for game in adapter.supported_games:
        if not game.id or game.id in ids:
            raise ValueError(f"Duplicate/empty game ID: {game.id}")
        ids.add(game.id)
        if any(slot.language_code not in language_codes for slot in game.slots):
            raise ValueError(f"Unsupported slot language: {game.id}")
        slot_ids = [slot.slot_id for slot in game.slots]
        if len(slot_ids) != len(set(slot_ids)) or any(not s for s in slot_ids):
            raise ValueError(f"Invalid slots: {game.id}")
        if (slot_ids and game.default_slot_id not in slot_ids) or (not slot_ids and game.default_slot_id):
            raise ValueError(f"Invalid default slot: {game.id}")
