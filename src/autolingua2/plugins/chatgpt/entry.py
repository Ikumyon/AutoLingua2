from autolingua2.plugins.api import PluginContext, PluginContribution
from .chatgpt import ChatGptProvider


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="chatgpt",
            provider=ChatGptProvider(),
        )
    )
