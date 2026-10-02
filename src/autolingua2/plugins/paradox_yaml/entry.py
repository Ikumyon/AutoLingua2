from autolingua2.plugins.api import PluginContext, PluginContribution
from .parser import ParadoxYamlAdapter
from .ui.panel import ParadoxCreationAdapter
from .ui.translations import PluginTranslations


def register(context: PluginContext) -> None:
    translations = PluginTranslations()
    context.on_close(translations.close)
    context.on_language_changed(translations.change_language)
    ui = ParadoxCreationAdapter()
    context.on_language_changed(ui.change_language)
    context.on_close(ui.close)
    context.register(PluginContribution(
        id="paradox_yaml", parser=ParadoxYamlAdapter(context.files.read_text_lossless), ui=ui,
    ))
