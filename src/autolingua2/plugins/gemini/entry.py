from pathlib import Path

from PySide6.QtGui import QIcon

from autolingua2.plugins.api import PluginContext, PluginContribution, UIContribution
from .gemini import GeminiProvider


def _chat_icon() -> QIcon:
    return QIcon(str(Path(__file__).parent / "icons" / "gemini.svg"))


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="gemini",
            provider=GeminiProvider(),
            ui=UIContribution(chat_icon=_chat_icon),
        )
    )
