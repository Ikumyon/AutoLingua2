"""Stable public plugin contracts. Importing this module requires neither Qt nor native code.

Internal model locations may change; plugin authors should import these names here.
These are the host's actual types, not copies or compatibility implementations.
"""
from autolingua2.adapters.base import FileAdapter
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit, UnitState
from autolingua2.ir.filter_rules import FilterRule
from autolingua2.ir.imported import GameProfile, GameSlot, ImportedTranslation, SourceRef
from autolingua2.services.ai_providers.base import AiProviderPlugin, TextTranslator, TranslationProviderError

__all__ = [
    "FileAdapter", "AiProviderPlugin", "TextTranslator", "TranslationProviderError",
    "Issue", "TranslationProject", "TranslationSource", "TranslationUnit", "UnitState",
    "FilterRule", "GameProfile", "GameSlot", "ImportedTranslation", "SourceRef",
]
