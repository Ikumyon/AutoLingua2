from autolingua2.plugins.api import PluginContext, PluginContribution, UIContribution
from .parser import ParadoxYamlAdapter
from .parser.exporter import ParadoxYamlExporter
from .ui.export_settings import ParadoxExportSettings
from .ui.eu4 import Eu4Palette, presentation
from .ui.panel import ParadoxCreationAdapter
from .ui.settings_page import ParadoxSettingsPageProvider
from .ui.translations import PluginTranslations


def register(context: PluginContext) -> None:
    translations = PluginTranslations()
    context.on_close(translations.close)
    context.on_language_changed(translations.change_language)
    creation_ui = ParadoxCreationAdapter()
    context.on_language_changed(creation_ui.change_language)
    context.on_close(creation_ui.close)

    palette = Eu4Palette(context)
    ui = UIContribution(
        creation_panel=creation_ui,
        settings_pages=[ParadoxSettingsPageProvider(palette)],
        text_presentation=presentation,
        highlighter_factory=palette.create_highlighter,
        export_settings={"yaml": ParadoxExportSettings()},
    )

    context.register(PluginContribution(
        id="paradox_yaml",
        parser=ParadoxYamlAdapter(lambda p: context.files.read_text_auto(p)[0]),
        ui=ui,
        exporters=[ParadoxYamlExporter()],
    ))
