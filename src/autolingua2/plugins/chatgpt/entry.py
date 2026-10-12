from PySide6.QtWidgets import QWidget

from autolingua2.plugins.api import (
    AiSetupCallbacks, AiSetupOption, AiSetupPanel, AiSetupValues,
    PluginContext, PluginContribution, UIContribution,
)
from .chatgpt import ChatGptProvider
from .widget import ChatGptSetupPanel


def _create_setup_panel(
    parent: QWidget, initial: AiSetupValues, callbacks: AiSetupCallbacks,
) -> AiSetupPanel:
    return ChatGptSetupPanel(parent, initial, callbacks)


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="chatgpt",
            provider=ChatGptProvider(),
            ui=UIContribution(
                ai_setup=AiSetupOption(
                    provider_id="chatgpt",
                    title="ChatGPT",
                    description="ブラウザで ChatGPT にサインインして利用します。",
                    mode="auth",
                    create_panel=_create_setup_panel,
                ),
            ),
        )
    )

