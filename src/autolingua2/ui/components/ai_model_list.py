from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from autolingua2.services.settings.settings_store import AiModel
from autolingua2.ui.resources.icons import IconManager
from .ai_model_row import ModelRowWidget


class ModelListController(QObject):
    """Shared editable model list for settings and initial setup."""

    changed = Signal()

    def __init__(self, parent: QWidget, layout: QVBoxLayout, icons: IconManager) -> None:
        super().__init__(parent)
        self.container = parent
        self.layout = layout
        self.icons = icons
        self.rows: list[ModelRowWidget] = []
        self.layout.addStretch()

    def populate(self, models: list[AiModel]) -> None:
        for row in self.rows:
            self.layout.removeWidget(row)
            row.deleteLater()
        self.rows.clear()
        for model in models:
            self.add(model)
        self.changed.emit()

    def add(self, model: AiModel) -> ModelRowWidget:
        row = ModelRowWidget(model, self.icons, self.container)
        row.deleted.connect(lambda: self.remove(row))
        row.modelCommitted.connect(lambda: self._model_changed(row))
        row.field_name.valueChanged.connect(lambda: self.changed.emit())
        row.check_enabled.toggled.connect(lambda: self.changed.emit())
        self.layout.insertWidget(len(self.rows), row)
        self.rows.append(row)
        self.changed.emit()
        return row

    def add_empty(self) -> None:
        from autolingua2.ui.resources.i18n import tr
        row = self.add(AiModel(tr("SettingsDialog", "新規モデル"), ""))
        row.field_model.start_edit()

    def remove(self, row: ModelRowWidget) -> None:
        if row not in self.rows:
            return
        self.rows.remove(row)
        self.layout.removeWidget(row)
        row.deleteLater()
        self.changed.emit()

    def _model_changed(self, row: ModelRowWidget) -> None:
        row.set_status(None)
        self.changed.emit()

    def read(self) -> list[AiModel]:
        models: list[AiModel] = []
        seen: set[str] = set()
        for row in self.rows:
            model = row.to_ai_model()
            if model.model and model.model not in seen:
                models.append(model)
                seen.add(model.model)
        return models

    def invalidate(self) -> None:
        for row in self.rows:
            row.set_status(None)

