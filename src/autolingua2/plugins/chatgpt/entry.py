from PySide6.QtWidgets import QWidget

from autolingua2.plugins.api import (
    AiSetupCallbacks, AiSetupOption, AiSetupPanel, AiSetupValues,
    PluginContext, PluginContribution, UIContribution,
)
from .chatgpt import ChatGptProvider
from .auth import ChatGptAuthManager
from .widget import ChatGptSetupPanel


def register(context: PluginContext) -> None:
    auth = ChatGptAuthManager(context.settings)
    context.on_close(auth.close)

    def create_setup_panel(
        parent: QWidget, initial: AiSetupValues, callbacks: AiSetupCallbacks,
    ) -> AiSetupPanel:
        return ChatGptSetupPanel(parent, initial, callbacks, auth)

    context.register(
        PluginContribution(
            id="chatgpt",
            provider=ChatGptProvider(auth),
            ui=UIContribution(
                ai_setup=AiSetupOption(
                    provider_id="chatgpt",
                    title="ChatGPT (おすすめ)",
                    description="ブラウザで ChatGPT にサインインして利用します（APIキー不要）。",
                    mode="auth",
                    create_panel=create_setup_panel,
                ),
            ),
        )
    )

