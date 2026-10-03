from autolingua2.plugins.api import PluginContext, PluginContribution
from .claude import ClaudeProvider


def register(context: PluginContext) -> None:
    context.register(
        PluginContribution(
            id="claude",
            provider=ClaudeProvider(),
        )
    )
