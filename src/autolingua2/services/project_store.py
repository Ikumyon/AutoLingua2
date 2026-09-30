from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from autolingua2.adapters.base import ImportedTranslation, SourceRef
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit, UnitState


def save_project(path: Path, imported: ImportedTranslation) -> None:
    """Persist canonical languages separately from the adapter's output slot."""
    path.write_text(json.dumps(asdict(imported), ensure_ascii=False, indent=2), encoding="utf-8")


def load_project(path: Path) -> ImportedTranslation:
    data = json.loads(path.read_text(encoding="utf-8"))
    return imported_from_dict(data)


def imported_from_dict(data: dict) -> ImportedTranslation:
    project_data = dict(data["project"])
    sources = [TranslationSource(**{**source, "issues": [Issue(**i) for i in source["issues"]]})
               for source in project_data.pop("sources")]
    units = [TranslationUnit(**{**unit, "state": UnitState(unit["state"]),
                               "issues": [Issue(**i) for i in unit["issues"]]})
             for unit in project_data.pop("units")]
    project = TranslationProject(**project_data, sources=sources, units=units)
    return ImportedTranslation(project, {key: SourceRef(**ref) for key, ref in data["source_refs"].items()})
