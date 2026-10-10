from __future__ import annotations

import re
from collections.abc import Callable
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QColorDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .eu4 import PAGE_ID, ParadoxPalette
from .translations import tr


class ColorPickerButton(QPushButton):
    """色見本を表示し、クリックでカラーピッカーを開くボタン。"""

    def __init__(self, initial_color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = initial_color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        self._update_style()
        self.clicked.connect(self._pick_color)
        self.color_changed_callback: Callable[[str], None] | None = None

    @property
    def color(self) -> str:
        return self._color

    def set_color(self, hex_color: str) -> None:
        self._color = hex_color
        self._update_style()

    def _update_style(self) -> None:
        self.setStyleSheet(
            f"QPushButton {{ background-color: {self._color}; "
            f"border: 1px solid rgba(128, 128, 128, 0.4); "
            f"border-radius: 4px; min-width: 80px; }}"
            f"QPushButton:hover {{ border: 1.5px solid #3b82f6; }}"
        )

    def _pick_color(self) -> None:
        c = QColorDialog.getColor(QColor(self._color), self, tr("ParadoxPlugin", "色を選択"))
        if c.isValid():
            hex_color = c.name(QColor.NameFormat.HexRgb).lower()
            self.set_color(hex_color)
            if callable(self.color_changed_callback):
                self.color_changed_callback(hex_color)


class ParadoxSettingsWidget(QWidget):
    """Paradox YAMLプラグインの色タグ設定UI。"""

    def __init__(self, palette: ParadoxPalette, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._drafts: dict[str, list[tuple[str, str]]] = {}
        self._current_game_id: str | None = None
        self._init_ui()
        self._select_game(self.combo_game.currentIndex())

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header_label = QLabel(tr("ParadoxPlugin", "テキスト色タグの配色設定"), self)
        header_label.setStyleSheet("font-size: 13pt; font-weight: bold;")
        layout.addWidget(header_label)
        game_layout = QHBoxLayout()
        game_layout.addWidget(QLabel(tr("ParadoxPlugin", "対象ゲーム："), self))
        self.combo_game = QComboBox(self)
        for game in self._palette.games:
            self.combo_game.addItem(game.name, game.id)
        game_layout.addWidget(self.combo_game)
        game_layout.addStretch()
        layout.addLayout(game_layout)

        sub_label = QLabel(
            tr("ParadoxPlugin", "ゲーム内テキストの色制御タグ（§W, §B, §b 等）と文字色の対応を設定します。\n"
               "※ 大文字・小文字は厳密に区別されます（例: B=青、b=黒）。"),
            self,
        )
        sub_label.setStyleSheet("color: gray;")
        layout.addWidget(sub_label)

        self.table = QTableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels([tr("ParadoxPlugin", label) for label in
                                              ("タグ文字", "色プレビュー (クリックで変更)", "カラーコード")])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_add = QPushButton(tr("ParadoxPlugin", "＋ タグ追加"), self)
        self.btn_add.clicked.connect(self._add_row)
        btn_layout.addWidget(self.btn_add)

        self.btn_remove = QPushButton(tr("ParadoxPlugin", "一 選択したタグを削除"), self)
        self.btn_remove.clicked.connect(self._remove_row)
        btn_layout.addWidget(self.btn_remove)

        btn_layout.addStretch()

        self.btn_reset = QPushButton(tr("ParadoxPlugin", "初期値に戻す"), self)
        self.btn_reset.clicked.connect(self._reset_defaults)
        btn_layout.addWidget(self.btn_reset)

        layout.addLayout(btn_layout)
        self.combo_game.currentIndexChanged.connect(self._select_game)

    def _store_table(self) -> None:
        if self._current_game_id is None:
            return
        rows: list[tuple[str, str]] = []
        for row in range(self.table.rowCount()):
            code = self.table.cellWidget(row, 0)
            color = self.table.cellWidget(row, 2)
            if not isinstance(code, QLineEdit) or not isinstance(color, QLineEdit):
                raise RuntimeError("配色設定の編集行が不完全です。")
            rows.append((code.text(), color.text()))
        self._drafts[self._current_game_id] = rows

    def _select_game(self, index: int) -> None:
        self._store_table()
        game_id = self.combo_game.itemData(index)
        if not isinstance(game_id, str):
            raise TypeError("配色設定のゲームIDが不正です。")
        self._current_game_id = game_id
        if game_id not in self._drafts:
            self._drafts[game_id] = list(self._palette.colors_for_game(game_id).items())
        self._load_data()

    def _load_data(self) -> None:
        if self._current_game_id is None:
            return
        self.table.setRowCount(0)
        for code, hex_code in self._drafts[self._current_game_id]:
            self._insert_tag_row(code, hex_code)

    def _insert_tag_row(self, code: str, hex_code: str) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 0. タグ文字エディタ
        edit_code = QLineEdit(code, self.table)
        edit_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit_code.setMaxLength(1)
        self.table.setCellWidget(row, 0, edit_code)

        # 2. カラーコードエディタ (先に作成して連動)
        edit_hex = QLineEdit(hex_code, self.table)
        edit_hex.setAlignment(Qt.AlignmentFlag.AlignCenter)
        edit_hex.setMaxLength(7)
        self.table.setCellWidget(row, 2, edit_hex)

        # 1. カラーピッカーボタン
        color_btn = ColorPickerButton(hex_code, self.table)
        self.table.setCellWidget(row, 1, color_btn)

        # 相互連動
        def on_color_picked(new_hex: str) -> None:
            edit_hex.setText(new_hex)

        def on_hex_edited(text: str) -> None:
            text = text.strip()
            if re.match(r"^#[0-9a-fA-F]{6}$", text):
                color_btn.set_color(text.lower())

        color_btn.color_changed_callback = on_color_picked
        edit_hex.textChanged.connect(on_hex_edited)

    def _add_row(self) -> None:
        self._insert_tag_row("", "#ffffff")
        self.table.scrollToBottom()
        last_row = self.table.rowCount() - 1
        widget = self.table.cellWidget(last_row, 0)
        if isinstance(widget, QLineEdit):
            widget.setFocus()

    def _remove_row(self) -> None:
        current_row = self.table.currentRow()
        if current_row >= 0:
            self.table.removeRow(current_row)

    def _reset_defaults(self) -> None:
        if self._current_game_id is None:
            return
        self._drafts[self._current_game_id] = list(
            self._palette.default_colors(self._current_game_id).items(),
        )
        self._load_data()

    def get_game_color_tags(self) -> dict[str, dict[str, str]]:
        self._store_table()
        changed: dict[str, dict[str, str]] = {}
        for game_id, rows in self._drafts.items():
            tags: dict[str, str] = {}
            for raw_code, raw_hex in rows:
                code = raw_code.strip()
                hex_str = raw_hex.strip()
                if re.fullmatch(r"[a-zA-Z0-9]", code) and re.fullmatch(r"#[0-9a-fA-F]{6}", hex_str):
                    tags[code] = hex_str.lower()
            if tags != self._palette.colors_for_game(game_id):
                changed[game_id] = tags
        return changed


class ParadoxSettingsPageProvider:
    """SettingsPageProvider プロトコルの実装。"""

    def __init__(self, palette: ParadoxPalette) -> None:
        self._palette = palette

    @property
    def id(self) -> str:
        return PAGE_ID

    @property
    def title(self) -> str:
        return tr("ParadoxPlugin", "Paradox 設定")

    def create_widget(self, parent: QWidget | None = None) -> QWidget:
        return ParadoxSettingsWidget(self._palette, parent)

    def save_settings(self, widget: QWidget) -> None:
        if not isinstance(widget, ParadoxSettingsWidget):
            raise TypeError("Unexpected Paradox settings widget")
        self._palette.save(widget.get_game_color_tags())
