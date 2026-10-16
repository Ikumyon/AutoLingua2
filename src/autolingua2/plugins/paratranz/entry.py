from autolingua2.plugins.api import PluginContext, PluginContribution
from .format import ParaTranzAdapter, ParaTranzExporter
from .glossary import ParaTranzGlossaryFormat


def register(context: PluginContext) -> None:
    context.register(PluginContribution(
        id="paratranz", parser=ParaTranzAdapter(), exporters=[ParaTranzExporter()],
        glossary_formats=(ParaTranzGlossaryFormat(),),
    ))
