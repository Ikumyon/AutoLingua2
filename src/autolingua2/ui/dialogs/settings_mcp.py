"""MCP settings integrated into the application's existing settings dialog."""
from __future__ import annotations

from autolingua2.ui.i18n import translation_source

from copy import deepcopy
import secrets
from uuid import uuid4

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSpinBox, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from autolingua2.services.mcp_client import McpClient
from autolingua2.services.mcp_server import McpServer
from autolingua2.services.operation_contract import ExternalMcpConnection, McpSettings, PERMISSIONS, Permission
from autolingua2.services.settings_store import load_mcp_settings, save_mcp_settings
from autolingua2.ui.i18n import tr


class McpSettingsPage(QWidget):
    def __init__(self, server: McpServer | None, parent: QWidget) -> None:
        super().__init__(parent)
        self.server = server
        self.settings = load_mcp_settings()
        self.connections = deepcopy(self.settings.connections)
        self.tester = McpClient(self)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox(tr("SettingsDialog", "本体へのMCP接続を有効にする"), self)
        self.enabled.setChecked(self.settings.enabled)
        form.addRow(self.enabled)
        self.port = QSpinBox(self)
        self.port.setRange(0, 65535)
        self.port.setSpecialValueText(tr("SettingsDialog", "自動"))
        self.port.setValue(self.settings.port)
        form.addRow(tr("SettingsDialog", "ポート"), self.port)
        self.token = QLineEdit(self.settings.token or secrets.token_urlsafe(32), self)
        self.token.setEchoMode(QLineEdit.EchoMode.Password)
        token_row = QHBoxLayout()
        token_row.addWidget(self.token)
        regenerate = QPushButton(tr("SettingsDialog", "再生成"), self)
        regenerate.clicked.connect(lambda: self.token.setText(secrets.token_urlsafe(32)))
        token_row.addWidget(regenerate)
        form.addRow(tr("SettingsDialog", "接続トークン"), token_row)
        self.endpoint = QLabel(self)
        self.endpoint.setWordWrap(True)
        form.addRow(tr("SettingsDialog", "接続状態"), self.endpoint)
        copy = QPushButton(tr("SettingsDialog", "接続情報をコピー"), self)
        copy.clicked.connect(self._copy)
        form.addRow(copy)
        permissions = QHBoxLayout()
        self.permissions: dict[Permission, QCheckBox] = {}
        for permission, title in zip(PERMISSIONS, ("参照", translation_source('SettingsDialog', "編集"), "翻訳", "書き出し")):
            checkbox = QCheckBox(tr("SettingsDialog", title), self)
            checkbox.setChecked(permission in self.settings.permissions)
            self.permissions[permission] = checkbox
            permissions.addWidget(checkbox)
        form.addRow(tr("SettingsDialog", "公開する操作"), permissions)
        layout.addLayout(form)
        layout.addWidget(QLabel(tr("SettingsDialog", "外部資料への接続"), self))
        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels([tr("SettingsDialog", "名前"), tr("SettingsDialog", "接続方式"), tr("SettingsDialog", "状態")])
        self.tree.setRootIsDecorated(False)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        for title, callback in ((translation_source('SettingsDialog', "追加"), self._add), (translation_source('SettingsDialog', "編集"), self._edit), (translation_source('SettingsDialog', "削除"), self._delete), (translation_source('SettingsDialog', "接続確認"), self._check)):
            button = QPushButton(tr("SettingsDialog", title), self)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self._refresh_connections()
        self.refresh_status()
        if server is not None:
            server.status_changed.connect(self.refresh_status)

    def refresh_status(self, _value: str = "") -> None:
        self.endpoint.setText((self.server.error or self.server.endpoint) if self.server is not None
                              and (self.server.error or self.server.endpoint) else tr("SettingsDialog", "無効"))

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        if self.server is None or not self.server.endpoint:
            self.message.setText(tr("SettingsDialog", "有効にして設定を適用してください。"))
            return
        QApplication.clipboard().setText(self.server.endpoint + "\nAuthorization: Bearer " + self.server.settings.token)
        self.message.setText(tr("SettingsDialog", "接続情報をコピーしました。"))

    def _refresh_connections(self) -> None:
        self.tree.clear()
        for connection in self.connections:
            self.tree.addTopLevelItem(QTreeWidgetItem([connection.name,
                tr("SettingsDialog", "ローカルプロセス") if connection.transport == "stdio" else "HTTP",
                tr("SettingsDialog", "未確認")]))

    def _selected(self) -> int | None:
        item = self.tree.currentItem()
        return self.tree.indexOfTopLevelItem(item) if item is not None else None

    def _connection_dialog(self, existing: ExternalMcpConnection | None) -> ExternalMcpConnection | None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("SettingsDialog", "外部MCP接続"))
        layout = QFormLayout(dialog)
        name = QLineEdit(existing.name if existing else "", dialog)
        transport = QComboBox(dialog)
        transport.addItem(tr("SettingsDialog", "ローカルプロセス"), "stdio")
        transport.addItem("HTTP", "http")
        transport.setCurrentIndex(1 if existing and existing.transport == "http" else 0)
        address = QLineEdit(existing.address if existing else "", dialog)
        arguments = QPlainTextEdit(dialog)
        arguments.setPlainText("\n".join(existing.arguments) if existing else "")
        token = QLineEdit(existing.token if existing else "", dialog)
        token.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow(tr("SettingsDialog", "名前"), name)
        layout.addRow(tr("SettingsDialog", "接続方式"), transport)
        layout.addRow(tr("SettingsDialog", "実行ファイルまたはMCPのURL"), address)
        layout.addRow(tr("SettingsDialog", "起動引数（1行に1つ）"), arguments)
        layout.addRow(tr("SettingsDialog", "接続トークン"), token)
        error = QLabel(dialog)
        layout.addRow(error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, dialog)
        layout.addRow(buttons)

        def accept() -> None:
            if not name.text().strip() or not address.text().strip():
                error.setText(tr("SettingsDialog", "名前と接続先を入力してください。"))
                return
            dialog.accept()
        buttons.accepted.connect(accept)
        buttons.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return None
        result = ExternalMcpConnection(existing.id if existing else uuid4().hex, name.text().strip(),
            "http" if transport.currentData() == "http" else "stdio", address.text().strip(),
            arguments.toPlainText().splitlines(), token.text().strip())
        dialog.deleteLater()
        return result

    def _add(self) -> None:
        value = self._connection_dialog(None)
        if value is not None:
            self.connections.append(value)
            self._refresh_connections()

    def _edit(self) -> None:
        index = self._selected()
        if index is not None:
            value = self._connection_dialog(self.connections[index])
            if value is not None:
                self.connections[index] = value
                self._refresh_connections()

    def _delete(self) -> None:
        index = self._selected()
        if index is not None:
            self.connections.pop(index)
            self._refresh_connections()

    def _check(self) -> None:
        index = self._selected()
        if index is None:
            return
        self.tester.configure(self.connections)
        self.message.setText(tr("SettingsDialog", "接続を確認しています…"))
        self.tester.check(self.connections[index].id,
            lambda result: self.message.setText(tr("SettingsDialog", "資料の読み取りに接続できました。")),
            lambda error: self.message.setText(error))

    def save(self) -> None:
        token = self.token.text().strip()
        if self.enabled.isChecked() and not token:
            raise ValueError(tr("SettingsDialog", "接続トークンを入力してください。"))
        self.settings = McpSettings(self.enabled.isChecked(), self.port.value(), token,
            [permission for permission, checkbox in self.permissions.items() if checkbox.isChecked()],
            deepcopy(self.connections))
        save_mcp_settings(self.settings)
