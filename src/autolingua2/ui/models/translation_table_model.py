from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from autolingua2.ir import TranslationUnit
from autolingua2.ui.i18n import tr


SourceNameGetter = Callable[[TranslationUnit], str]
ValueGetter = Callable[[TranslationUnit, SourceNameGetter], str]


@dataclass(frozen=True, slots=True)
class TranslationTableColumn:
    id: str
    label: str
    value_getter: ValueGetter
    default_visible: bool = True

    def value_for(self, unit: TranslationUnit, source_name_getter: SourceNameGetter) -> str:
        return self.value_getter(unit, source_name_getter)


def default_translation_table_columns(
    status_getter: Callable[[TranslationUnit], str],
) -> list[TranslationTableColumn]:
    return [
        TranslationTableColumn("label", tr("TranslationTable", "キー"), lambda unit, _: unit.label),
        TranslationTableColumn("source_text", tr("TranslationTable", "原文"), lambda unit, _: unit.source_text),
        TranslationTableColumn("target_text", tr("TranslationTable", "訳文"), lambda unit, _: unit.target_text),
        TranslationTableColumn("status", tr("TranslationTable", "状態"), lambda unit, _: status_getter(unit)),
        TranslationTableColumn("file", tr("TranslationTable", "ファイル"), lambda unit, source_name_getter: source_name_getter(unit)),
    ]
