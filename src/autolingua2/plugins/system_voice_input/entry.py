from autolingua2.plugins.api import PluginContext, PluginContribution
from autolingua2.plugins.contracts import VoiceInputCallbacks, VoiceInputMode


class SystemVoiceInputProvider:
    def __init__(self, context: PluginContext) -> None:
        self._context = context

    @property
    def id(self) -> str:
        return self._context.id

    @property
    def display_name(self) -> str:
        return "OS標準の音声入力" if self._context.ui_language.startswith("ja") else "System voice input"

    @property
    def mode(self) -> VoiceInputMode:
        return "external"

    def is_available(self) -> bool:
        return self._context.system_voice_input.is_available()

    def start(self, callbacks: VoiceInputCallbacks) -> None:
        self._context.system_voice_input.start()


def register(context: PluginContext) -> None:
    context.register(PluginContribution(id=context.id, voice_input=SystemVoiceInputProvider(context)))
