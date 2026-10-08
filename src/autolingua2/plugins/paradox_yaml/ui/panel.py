from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from PySide6.QtCore import QEvent, Qt
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

from autolingua2.plugins.api import PluginContext
from ..parser import reader
from ..parser.mod_parser import parse_mod_file
from .translations import tr


class ParadoxCreationAdapter:
    """UI hooks supplied through the common plugin entrance."""

    def __init__(self) -> None:
        self._panels: set[ParadoxCreationPanel] = set()

    def create_creation_panel(self, context: PluginContext) -> QWidget:
        panel = ParadoxCreationPanel(context)
        self._panels.add(panel)
        return panel

    def on_paths_dropped(self, paths: list[Path], context: PluginContext) -> list[Path]:
        return handle_paths_dropped(paths, context)

    def on_game_selected(self, game_id: str, context: PluginContext) -> None:
        for game in reader.PARADOX_GAMES:
            if game.id == game_id and game.default_slot_id:
                context.creation.set_target_slot(game.default_slot_id)
                break

    def format_target_path_label(self, path: Path, current_source_lang: str) -> tuple[str, str, str]:
        return format_target_label(path, current_source_lang)

    def dispose_creation_panel(self, panel: QWidget) -> None:
        if not isinstance(panel, ParadoxCreationPanel):
            raise TypeError("Unexpected Paradox panel")
        self._panels.discard(panel)

    def change_language(self, language: str) -> None:
        for panel in self._panels:
            panel.retranslate_ui()

    def close(self) -> None:
        self._panels.clear()



class ParadoxCreationPanel(QWidget):
    """Paradox YAMLプラグイン専用の中央IOパネルウィジェット。"""

    def __init__(self, context: PluginContext, parent: QWidget | None = None) -> None:
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

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


    def _browse_mod_file(self) -> None:
        parent = self
        file_filter = tr("ParadoxPlugin", "Paradox Mod ファイル (*.mod descriptor.mod);;すべてのファイル (*.*)")
        path_str, _ = QFileDialog.getOpenFileName(parent, tr("ParadoxPlugin", ".modファイルを選択"), "", file_filter)
        if path_str:
            self._run(lambda: import_mod_file(Path(path_str), self.context))

    def _run(self, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:
            QMessageBox.warning(self, tr("ParadoxPlugin", "エラー"), str(exc))

    def _browse_folder(self) -> None:
        parent = self
        folder = QFileDialog.getExistingDirectory(parent, tr("ParadoxPlugin", "翻訳対象のMODフォルダを選択"))
        if folder:
            self._run(lambda: self.context.creation.add_target_path(Path(folder)))

    def _browse_file(self) -> None:
        parent = self
        file_filter = tr("ParadoxPlugin", "Paradox YAML ファイル (*.yml *.yaml);;すべてのファイル (*.*)")
        files, _ = QFileDialog.getOpenFileNames(parent, tr("ParadoxPlugin", "翻訳対象のYAMLファイルを選択"), "", file_filter)
        for f in files:
            self._run(lambda: self.context.creation.add_target_path(Path(f)))


def import_mod_file(path: Path, context: PluginContext) -> None:
    """Paradox の .mod ファイルを解析し、コンテキストに情報を設定する。"""
    try:
        info = parse_mod_file(path, lambda p: context.files.read_text_auto(p)[0])
    except Exception as exc:
        parent = None
        QMessageBox.warning(parent, tr("ParadoxPlugin", "エラー"), tr("ParadoxPlugin", f".modファイルの読み込みに失敗しました: {exc}"))
        return

    if info.name:
        context.creation.set_project_name(info.name)

    if info.target_path and (info.target_path.is_dir() or info.target_path.is_file()):
        context.creation.add_target_path(info.target_path)

    if info.game_id:
        context.creation.select_game(info.game_id)


def handle_paths_dropped(paths: list[Path], context: PluginContext) -> list[Path]:
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
    from ..parser.reader import detect_file_language_from_name


    if path.is_file():
        return path.name, "", str(path)

    # フォルダ内の対象YAMLファイルをファイル名から瞬時に走査
    yaml_files = [f for f in path.rglob("*") if f.is_file() and f.suffix.lower() in {".yml", ".yaml"}]
    if not yaml_files:
        raise ValueError(tr("ParadoxPlugin", "対象となるYAMLファイルが見つかりません"))

    if current_source_lang and current_source_lang != "auto":
        matching = [f for f in yaml_files if detect_file_language_from_name(f) == current_source_lang]
        count = len(matching)
        if count == 0:
            raise ValueError(tr("ParadoxPlugin", f"選択言語（{current_source_lang}）の対象ファイルがありません"))
        text = tr("ParadoxPlugin", "{name} ({count}件)").format(name=path.name, count=count)
        tooltip = tr("ParadoxPlugin", "{path}\n対象ファイル数: {count}件").format(path=str(path), count=count)
        return text, "", tooltip

    # auto の場合
    lang_counts: dict[str, int] = {}
    for f in yaml_files:
        lang = detect_file_language_from_name(f)
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

    if len(lang_counts) == 1:
        count = next(iter(lang_counts.values()))
        text = tr("ParadoxPlugin", "{name} ({count}件)").format(name=path.name, count=count)
        tooltip = tr("ParadoxPlugin", "{path}\n対象ファイル数: {count}件").format(path=str(path), count=count)
        return text, "", tooltip
    elif len(lang_counts) > 1:
        total = sum(lang_counts.values())
        detail = ", ".join(f"{l}: {c}件" for l, c in lang_counts.items())
        text = tr("ParadoxPlugin", "{name} ({count}件)").format(name=path.name, count=total)
        tooltip = tr("ParadoxPlugin", "{path}\n合計: {count}件 ({detail})").format(path=str(path), count=total, detail=detail)
        return text, "", tooltip
    else:
        count = len(yaml_files)
        text = tr("ParadoxPlugin", "{name} ({count}件)").format(name=path.name, count=count)
        tooltip = tr("ParadoxPlugin", "{path}\n対象ファイル数: {count}件").format(path=str(path), count=count)
        return text, "", tooltip
