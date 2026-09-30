from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QLabel, QWidget

from autolingua2.adapters.base import FileAdapter
from autolingua2.ui.i18n import tr
from .base import SimpleDialogController, require_child


FALLBACK_LANGUAGES: list[tuple[str, str]] = [
    ("en", "English"),
    ("ja", "Japanese"),
    ("zh", "Simplified Chinese"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("ru", "Russian"),
    ("ko", "Korean"),
]


class ProjectLanguageDialogController(SimpleDialogController):
    def __init__(self, path: Path, adapter: FileAdapter, parent: QWidget | None = None) -> None:
        super().__init__("ProjectLanguageDialog.ui", parent)
        self.path = path
        self.adapter = adapter

        self.label_target_path = require_child(self.dialog, QLabel, "labelTargetPath")
        self.label_detected_hint = require_child(self.dialog, QLabel, "labelDetectedHint")
        self.combo_source = require_child(self.dialog, QComboBox, "comboSourceLanguage")
        self.combo_target = require_child(self.dialog, QComboBox, "comboTargetLanguage")

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.label_target_path.setText(
            f"{tr('ProjectLanguageDialog', '対象')}: {self.path.name} ({self.adapter.name})"
        )

        languages = getattr(self.adapter, "supported_languages", None) or FALLBACK_LANGUAGES

        self.combo_source.clear()
        self.combo_target.clear()

        for code, name in languages:
            self.combo_source.addItem(name, code)
            self.combo_target.addItem(name, code)

        # 翻訳元言語の自動検出
        detected: str | None = None
        if hasattr(self.adapter, "detect_source_language"):
            try:
                detected = self.adapter.detect_source_language(self.path)
            except Exception:
                detected = None

        if detected:
            idx = self.combo_source.findData(detected)
            if idx >= 0:
                self.combo_source.setCurrentIndex(idx)
            self.label_detected_hint.show()
        else:
            self.label_detected_hint.hide()

        # 翻訳先言語の初期選択（日本語を優先）
        target_idx = -1
        for jp_code in ("l_japanese", "ja", "ja_JP", "Japanese"):
            target_idx = self.combo_target.findData(jp_code)
            if target_idx >= 0:
                break
        if target_idx >= 0:
            self.combo_target.setCurrentIndex(target_idx)
        elif self.combo_target.count() > 1:
            self.combo_target.setCurrentIndex(1)

    @property
    def selected_source_language(self) -> str:
        return str(self.combo_source.currentData() or "")

    @property
    def selected_target_language(self) -> str:
        return str(self.combo_target.currentData() or "")
