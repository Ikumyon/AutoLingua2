from autolingua2.plugins.api import PluginContext, PluginContribution
from .openai import OpenAiProvider


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="openai",
            provider=OpenAiProvider(),
        )
    )
