"""Context-sensitive online guide links shared by Designer forms and F1."""
from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeyEvent
from PySide6.QtWidgets import QAbstractButton, QApplication, QMessageBox, QStackedWidget, QTabWidget, QWidget

from autolingua2.ui.resources.i18n import tr


GUIDE_BASE_URL = "https://ikumyon.github.io/AutoLingua2/"
FORM_TARGETS = {
    "dialogs/setup/InitialSetupDialog.ui": ("setup", ""),
    "dialogs/GlossaryImportDialog.ui": ("glossary-exchange", "import-glossary"),
    "dialogs/GlossaryExportDialog.ui": ("glossary-exchange", "export-glossary"),
    "dialogs/GlossaryTermDialog.ui": ("glossary-editor", "edit-terms"),
    "dialogs/SourceUpdateDialog.ui": ("source-updates", "after-update"),
    "dialogs/SourceWatchTargetDialog.ui": ("source-updates", "register-target"),
    "dialogs/ThumbnailDialog.ui": ("thumbnail", "transform"),
    "dialogs/ThumbnailExportSettings.ui": ("thumbnail", "export-image"),
    "dialogs/ProblemsDialog.ui": ("support", "problems"),
    "dialogs/UpdateDialog.ui": ("support", "update"),
    "dialogs/MultiModelTranslationDialog.ui": ("translation", "compare-models"),
    "dialogs/WorkspaceLanguageDialog.ui": ("projects", "languages"),
    "dialogs/ExportDialog.ui": ("export", ""),
}
SETTINGS_TARGETS = {
    "pageGeneral": ("settings", "application"), "pageDisplay": ("settings", "application"),
    "pageInput": ("settings", "application"), "pageTranslation": ("settings", "translation"),
    "pageAI": ("ai-settings", ""), "pageTone": ("tone", ""),
    "pageGlossary": ("glossary-editor", ""), "pageFilterRules": ("settings", "filter-rules"),
    "pageFile": ("source-updates", ""), "pageSourceWatch": ("source-updates", ""),
    "pageMcp": ("mcp-server", ""), "pagePlugins": ("settings", "plugins"),
    "pageShortcuts": ("settings", "shortcuts"),
}


def guide_url(page: str = "first-translation", anchor: str = "") -> str:
    url = f"{GUIDE_BASE_URL}guide/{quote(page, safe='')}"
    return url + ("#" + quote(anchor, safe="") if anchor else "")


def guide_target(widget: QWidget | None) -> tuple[str, str]:
    current = widget
    while current is not None:
        page = current.property("guidePage")
        if isinstance(page, str) and page:
            return page, str(current.property("guideAnchor") or "")
        if current.objectName() == "dockAiChat":
            return "ai-chat", ""
        if current.objectName() == "dockAiSettings":
            return "ai-settings", ""
        form = current.property("guideForm")
        if form == "MainWindow.ui":
            stack = current.findChild(QStackedWidget, "stackMain")
            if stack is not None and stack.currentIndex() == 0:
                return "first-translation", ""
            view = current.findChild(QStackedWidget, "stackTranslationView")
            return ("projects", "dashboard") if view is not None and view.currentWidget().objectName() == "pageDashboard" else ("translation", "")
        if form == "dialogs/settings/SettingsDialog.ui":
            stack = current.findChild(QStackedWidget, "stackSettings")
            selected = stack.currentWidget() if stack is not None else None
            return SETTINGS_TARGETS.get(selected.objectName() if selected else "", ("settings", "plugins"))
        if form == "dialogs/AutomationDialog.ui":
            tabs = current.findChild(QTabWidget, "automationTabs")
            return ("automation-triggers", "") if tabs is not None and tabs.currentIndex() == 1 else ("scripts", "")
        if form in FORM_TARGETS:
            return FORM_TARGETS[form]
        if current.isWindow() and not form:
            # A few controllers wrap the loaded Designer form in their own dialog.
            for child in current.findChildren(QWidget):
                if child.property("guideForm"):
                    return guide_target(child)
        current = current.parentWidget()
    return "first-translation", ""


def open_guide(widget: QWidget | None = None, *, page: str | None = None, anchor: str = "") -> bool:
    if page is None:
        page, anchor = guide_target(widget)
    url = guide_url(page, anchor)
    if QDesktopServices.openUrl(QUrl(url)):
        return True
    QMessageBox.warning(widget, tr("GuideLinks", "ガイドを開けませんでした"),
                        tr("GuideLinks", "次のURLをブラウザで開いてください。") + "\n" + url)
    return False


class _GuideKeys(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(event, QKeyEvent) and event.key() == Qt.Key.Key_F1 and not event.modifiers():
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress:
                if not event.isAutoRepeat():
                    app = QApplication.instance()
                    target = app.activeModalWidget() or app.focusWidget() or app.activeWindow()
                    open_guide(target)
                return True
        return super().eventFilter(watched, event)


_keys: _GuideKeys | None = None


def bind_guide(widget: QWidget, form: str) -> None:
    """Wire Designer-defined links without constructing any fixed UI in Python."""
    global _keys
    widget.setProperty("guideForm", form)
    for button in widget.findChildren(QAbstractButton):
        if button.objectName().startswith("buttonGuide"):
            button.setAutoRepeat(False)
            button.clicked.connect(lambda checked=False, target=button: open_guide(target))
    for action in widget.findChildren(QAction):
        if action.objectName() == "actionUserGuide":
            action.triggered.connect(lambda checked=False: open_guide(widget, page="first-translation"))
        elif action.objectName() == "actionContextGuide":
            action.triggered.connect(lambda checked=False: open_guide(QApplication.focusWidget() or widget))
        elif action.objectName() == "actionChatGuide":
            action.triggered.connect(lambda checked=False: open_guide(widget, page="ai-chat"))
    app = QApplication.instance()
    if app is not None and _keys is None:
        _keys = _GuideKeys(app)
        app.installEventFilter(_keys)
