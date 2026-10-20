"""Guide navigation must preserve language and use stable form/category IDs."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QStackedWidget, QTabWidget, QWidget

from autolingua2.ui import guide
from autolingua2.ui.ui_loader import load_ui


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_guide_url_leaves_language_selection_to_browser():
    assert guide.guide_url("tone", "condition-example") == (
        "https://ikumyon.github.io/AutoLingua2/guide/tone#condition-example")


def test_settings_button_tracks_selected_category(app):
    dialog = load_ui("dialogs/settings/SettingsDialog.ui")
    stack = dialog.findChild(QStackedWidget, "stackSettings")
    button = dialog.findChild(QPushButton, "buttonGuideSettings")
    for name, expected in (("pageAI", "ai-settings"), ("pageTone", "tone"),
                           ("pageGlossary", "glossary-editor"), ("pageSourceWatch", "source-updates")):
        stack.setCurrentWidget(dialog.findChild(QWidget, name))
        assert guide.guide_target(button)[0] == expected
    resource_button = dialog.findChild(QPushButton, "buttonGuideResources")
    assert guide.guide_target(resource_button) == ("mcp-resources", "")
    dialog.deleteLater()


def test_automation_button_tracks_tab_and_reference_is_fixed(app):
    dialog = load_ui("dialogs/AutomationDialog.ui")
    tabs = dialog.findChild(QTabWidget, "automationTabs")
    button = dialog.findChild(QPushButton, "buttonGuideAutomation")
    assert guide.guide_target(button) == ("scripts", "")
    tabs.setCurrentIndex(1)
    assert guide.guide_target(button) == ("automation-triggers", "")
    assert guide.guide_target(dialog.findChild(QPushButton, "buttonGuideReference")) == ("script-reference", "")
    dialog.deleteLater()


def test_open_keeps_dialog_and_edits_intact(app, monkeypatch):
    dialog = load_ui("dialogs/GlossaryImportDialog.ui")
    calls = []
    monkeypatch.setattr(guide.QDesktopServices, "openUrl", lambda url: calls.append(url.toString()) or True)
    dialog.show()
    app.processEvents()
    dialog.findChild(QPushButton, "buttonGuideImport").click()
    assert calls == ["https://ikumyon.github.io/AutoLingua2/guide/glossary-exchange#import-glossary"]
    assert dialog.isVisible()
    dialog.close()
    dialog.deleteLater()


def test_f1_uses_active_modal_context(app, monkeypatch):
    calls = []
    monkeypatch.setattr(guide.QDesktopServices, "openUrl", lambda url: calls.append(url.toString()) or True)
    dialog = load_ui("dialogs/settings/SettingsDialog.ui")
    stack = dialog.findChild(QStackedWidget, "stackSettings")
    stack.setCurrentWidget(dialog.findChild(QWidget, "pageTone"))
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    app.processEvents()
    QTest.keyClick(dialog, Qt.Key.Key_F1)
    assert len(calls) == 1 and "/guide/tone" in calls[0]
    dialog.close()
    dialog.deleteLater()


def test_export_context_override_and_wrapped_designer_form(app):
    wrapper = QDialog()
    form = load_ui("dialogs/ThumbnailDialog.ui", wrapper)
    assert guide.guide_target(wrapper) == ("thumbnail", "transform")
    assert guide.guide_target(form.findChild(QPushButton, "buttonGuideThumbnail")) == ("thumbnail", "transform")
    export = load_ui("dialogs/ExportDialog.ui")
    export.setProperty("guidePage", "export-bmfont")
    assert guide.guide_target(export.findChild(QPushButton, "buttonGuideExport")) == ("export-bmfont", "")
    wrapper.deleteLater()
    export.deleteLater()


def test_export_guide_tracks_real_exporter_keys(app, monkeypatch):
    from autolingua2.ui.export.export_dialog import ExportDialog
    from autolingua2.ui import shortcuts

    monkeypatch.setattr(shortcuts, "load_shortcut_preferences", lambda: ("default", False))
    manager = app.findChild(shortcuts.ShortcutManager) or shortcuts.ShortcutManager(app)
    parent = QDialog()
    dialog = ExportDialog([], {
        "paradox_yaml:yaml": SimpleNamespace(id="yaml", name="YAML"),
        "paratranz:json": SimpleNamespace(id="json", name="ParaTranz JSON"),
    }, {}, Path(__file__).resolve().parents[1], "paradox_yaml", parent)
    button = dialog.dialog.findChild(QPushButton, "buttonGuideExport")
    for index, expected in enumerate(("export-yaml", "export-paratranz", "export-bmfont")):
        dialog._formats.setCurrentIndex(index)
        assert guide.guide_target(button) == (expected, "")
    dialog.dialog.deleteLater()
    parent.deleteLater()


def test_browser_failure_shows_copyable_url(app, monkeypatch):
    messages = []
    monkeypatch.setattr(guide.QDesktopServices, "openUrl", lambda url: False)
    monkeypatch.setattr(guide.QMessageBox, "warning", lambda parent, title, text: messages.append(text))
    assert not guide.open_guide(page="support", anchor="connection")
    assert len(messages) == 1 and "/guide/support#connection" in messages[0]


def test_guide_controls_are_designer_defined_and_not_default_buttons():
    root = Path(__file__).resolve().parents[1]
    files = ["MainWindow.ui", "dialogs/settings/SettingsDialog.ui", "dialogs/AutomationDialog.ui",
             "dialogs/ExportDialog.ui", "dialogs/ThumbnailDialog.ui", "dialogs/ProblemsDialog.ui",
             "dialogs/UpdateDialog.ui", "dialogs/GlossaryImportDialog.ui", "dialogs/GlossaryExportDialog.ui",
             "dialogs/setup/InitialSetupDialog.ui"]
    for name in files:
        document = ET.parse(root / "ui" / name)
        buttons = [w for w in document.iter("widget") if w.get("name", "").startswith("buttonGuide")]
        assert buttons, name
        for button in buttons:
            assert button.findtext("property[@name='autoDefault']/bool") == "false", name
