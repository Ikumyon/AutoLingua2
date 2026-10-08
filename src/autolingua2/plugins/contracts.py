"""Stable public plugin contracts. Importing this module requires neither Qt nor native code.

Internal model locations may change; plugin authors should import these names here.
These are the host's actual types, not copies or compatibility implementations.
"""
from autolingua2.adapters.base import FileAdapter
from autolingua2.ir import Issue, TranslationProject, TranslationSource, TranslationUnit, UnitState
from autolingua2.ir.filter_rules import FilterRule
from autolingua2.ir.imported import GameProfile, GameSlot, ImportedTranslation, SourceRef
from autolingua2.services.export_contract import ExportFile, TranslationExporter
from autolingua2.services.voice_input_contract import (
    VoiceInputCallbacks, VoiceInputMode, VoiceInputOperation, VoiceInputProvider,
)
from autolingua2.services.ai_providers.chat import (
    ChatMessage, ChatReply, ChatToolCall, object_value, string_value,
)
from autolingua2.services.ai_providers.base import (
    AiProviderPlugin,
    BaseAiProvider,
    BaseHttpTranslator,
    TextTranslator,
    TranslationProviderError,
)

__all__ = [
    "VoiceInputCallbacks", "VoiceInputMode", "VoiceInputOperation", "VoiceInputProvider",
    "ChatMessage", "ChatReply", "ChatToolCall", "object_value", "string_value",
    "ExportFile", "TranslationExporter",
    "FileAdapter", "AiProviderPlugin", "TextTranslator", "TranslationProviderError",
    "BaseHttpTranslator", "BaseAiProvider",
    "Issue", "TranslationProject", "TranslationSource", "TranslationUnit", "UnitState",
    "FilterRule", "GameProfile", "GameSlot", "ImportedTranslation", "SourceRef",
]

