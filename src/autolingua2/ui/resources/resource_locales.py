"""Stateless label lookup shared by resource managers; owns no registrations."""
import json
from pathlib import Path

def resolve_locale_text(locales_dir: Path, key: str, language: str) -> str | None:
    if not locales_dir.exists() or not locales_dir.is_dir():
        return None

    # Candidate file names in order of preference
    candidates: list[str] = [f"{language}.json"]
    if "_" in language:
        candidates.append(f"{language.split('_')[0]}.json")
    if language != "en_US":
        candidates.extend(["en_US.json", "en.json"])

    for candidate in candidates:
        locale_file = locales_dir / candidate
        if locale_file.is_file():
            try:
                with open(locale_file, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and key in data:
                    return str(data[key])
            except Exception:
                continue

    # Fallback to any json file found
    for locale_file in locales_dir.glob("*.json"):
        try:
            with open(locale_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and key in data:
                return str(data[key])
        except Exception:
            continue

    return None


