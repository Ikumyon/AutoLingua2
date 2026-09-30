from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from autolingua2.adapters.base import CreationContext
from autolingua2.adapters.paradox_yaml.mod_parser import parse_mod_file
from autolingua2.ui.i18n import tr

class ParadoxCreationPanel(QWidget):
    """Paradox YAMLプラグイン専用の中央IOパネルウィジェット。"""

    def __init__(self, context: CreationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.context = context
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 案内ラベル
        self.label_prompt = QLabel(
            tr("ParadoxPlugin", "MODフォルダ、.mod、または翻訳ファイルをここにドロップ"),
            self,
        )
        self.label_prompt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label_prompt.setStyleSheet("font-weight: bold; font-size: 12px;")
        layout.addWidget(self.label_prompt)

        # ボタン行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        btn_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # .modから自動入力
        self.btn_import_mod = QPushButton(tr("ParadoxPlugin", ".modから自動入力..."), self)
        self.btn_import_mod.setIcon(self.context.get_icon("file"))
        self.btn_import_mod.setToolTip(tr("ParadoxPlugin", "ParadoxゲームのMOD定義ファイル（.mod / descriptor.mod）から自動設定"))
        self.btn_import_mod.clicked.connect(self._browse_mod_file)
        btn_layout.addWidget(self.btn_import_mod)

        # フォルダ追加
        self.btn_browse_folder = QPushButton(tr("ParadoxPlugin", "フォルダ追加"), self)
        self.btn_browse_folder.setIcon(self.context.get_icon("folder"))
        self.btn_browse_folder.clicked.connect(self._browse_folder)
        btn_layout.addWidget(self.btn_browse_folder)

        # ファイル追加
        self.btn_browse_file = QPushButton(tr("ParadoxPlugin", "ファイル追加"), self)
        self.btn_browse_file.setIcon(self.context.get_icon("file"))
        self.btn_browse_file.clicked.connect(self._browse_file)
        btn_layout.addWidget(self.btn_browse_file)

        btn_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        layout.addLayout(btn_layout)

    def retranslate_ui(self) -> None:
        """UIテキストを現在の翻訳言語に再設定する。"""
        self.label_prompt.setText(tr("ParadoxPlugin", "MODフォルダ、.mod、または翻訳ファイルをここにドロップ"))
        self.btn_import_mod.setText(tr("ParadoxPlugin", ".modから自動入力..."))
        self.btn_import_mod.setToolTip(tr("ParadoxPlugin", "ParadoxゲームのMOD定義ファイル（.mod / descriptor.mod）から自動設定"))
        self.btn_browse_folder.setText(tr("ParadoxPlugin", "フォルダ追加"))
        self.btn_browse_file.setText(tr("ParadoxPlugin", "ファイル追加"))
        self.btn_import_mod.setIcon(self.context.get_icon("file"))
        self.btn_browse_folder.setIcon(self.context.get_icon("folder"))
        self.btn_browse_file.setIcon(self.context.get_icon("file"))

    def changeEvent(self, event: Any) -> None:
        from PySide6.QtCore import QEvent
        if isinstance(event, QEvent) and event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


    def _browse_mod_file(self) -> None:
        parent = getattr(self.context, "parent_widget", self)
        file_filter = tr("ParadoxPlugin", "Paradox Mod ファイル (*.mod descriptor.mod);;すべてのファイル (*.*)")
        path_str, _ = QFileDialog.getOpenFileName(parent, tr("ParadoxPlugin", ".modファイルを選択"), "", file_filter)
        if path_str:
            self._run(lambda: import_mod_file(Path(path_str), self.context))

    def _run(self, action) -> None:
        try:
            action()
        except Exception as exc:
            QMessageBox.warning(self, tr("ParadoxPlugin", "エラー"), str(exc))

    def _browse_folder(self) -> None:
        parent = getattr(self.context, "parent_widget", self)
        folder = QFileDialog.getExistingDirectory(parent, tr("ParadoxPlugin", "翻訳対象のMODフォルダを選択"))
        if folder:
            self._run(lambda: self.context.add_target_path(Path(folder)))

    def _browse_file(self) -> None:
        parent = getattr(self.context, "parent_widget", self)
        file_filter = tr("ParadoxPlugin", "Paradox YAML ファイル (*.yml *.yaml);;すべてのファイル (*.*)")
        files, _ = QFileDialog.getOpenFileNames(parent, tr("ParadoxPlugin", "翻訳対象のYAMLファイルを選択"), "", file_filter)
        for f in files:
            self._run(lambda: self.context.add_target_path(Path(f)))


def import_mod_file(path: Path, context: CreationContext) -> None:
    """Paradox の .mod ファイルを解析し、コンテキストに情報を設定する。"""
    try:
        info = parse_mod_file(path)
    except Exception as exc:
        parent = getattr(context, "parent_widget", None)
        QMessageBox.warning(parent, tr("ParadoxPlugin", "エラー"), tr("ParadoxPlugin", f".modファイルの読み込みに失敗しました: {exc}"))
        return

    if info.name:
        context.set_project_name(info.name)

    if info.target_path and (info.target_path.is_dir() or info.target_path.is_file()):
        context.add_target_path(info.target_path)

    if info.game_id:
        context.select_game(info.game_id)


def handle_paths_dropped(paths: list[Path], context: CreationContext) -> list[Path]:
    """中央DnD枠にドロップされたパス群をParadoxプラグインとして処理する。"""
    mod_files = [p for p in paths if p.suffix.lower() == ".mod" or p.name.lower() == "descriptor.mod"]
    other_paths = [p for p in paths if p not in mod_files]

    # 1. .mod ファイルがあればプロジェクト情報設定
    for path in mod_files:
        import_mod_file(path, context)

    # 3. その他のフォルダやYAMLファイルを追加
    return other_paths


def format_target_label(path: Path, current_source_lang: str) -> tuple[str, str, str]:
    """対象フォルダ/ファイルの表示ラベル、スタイル、ツールチップを生成する。"""
    if path.is_file():
        return path.name, "", str(path)

    text = tr("ParadoxPlugin", "{name}（作成時に解析）").format(name=path.name)
    return text, "", str(path)
