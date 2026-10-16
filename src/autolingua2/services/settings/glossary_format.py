"""Public, widget-free contract for flat bilingual glossary interchange."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from autolingua2.ir.glossary import DirectedTerm, GlossaryTerm, TermSide

__all__ = ["GlossaryFormat", "GlossaryImportData", "GlossaryExportData", "GlossaryTerm", "TermSide", "DirectedTerm"]


@dataclass(frozen=True, slots=True)
class GlossaryImportData:
    # a is the file's original side; the host maps it to the root language slots.
    terms: tuple[GlossaryTerm, ...]
    input_count: int


@dataclass(frozen=True, slots=True)
class GlossaryExportData:
    payload: object
    omitted_target_variants: int
    omitted_case_settings: int


@runtime_checkable
class GlossaryFormat(Protocol):
    id: str
    name: str

    def decode(self, value: object) -> GlossaryImportData: ...

    def encode(self, terms: tuple[DirectedTerm, ...]) -> GlossaryExportData: ...
