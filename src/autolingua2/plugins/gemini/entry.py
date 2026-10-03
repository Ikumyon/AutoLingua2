from autolingua2.plugins.api import PluginContext, PluginContribution
from .gemini import GeminiProvider


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="gemini",
            provider=GeminiProvider(),
        )
    )
