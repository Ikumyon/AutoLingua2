from autolingua2.plugins.api import PluginContext, PluginContribution
from .provider import ExampleProvider


def register(context: PluginContext) -> None:
    context.register(PluginContribution(context.id, provider=ExampleProvider(context.id)))
