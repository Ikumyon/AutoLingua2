"""Localized operation labels and the native, read-only material viewer."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout, QWidget

NAMES = {"set_language": "言語設定の変更", "edit_units": "訳文・翻訳メモの変更", "edit_glossary": "用語集の変更", "edit_term": "用語の変更",
         "edit_tone": "口調の変更", "set_preferences": "用語集・口調の適用", "start_translation": "翻訳",
         "translation": "翻訳", "review_units": "AIレビュー・候補比較", "review": "AIレビュー・候補比較",
         "source_changes": "原文の差分確認", "apply_source_update": "原文の取り込み", "source_update": "原文の取り込み",
         "save_project": "プロジェクト保存", "export_plan": "書き出し内容の確認", "start_export": "書き出し",
         "export": "書き出し", "external_resources_list": "外部資料の一覧", "external_resources_read": "外部資料の取得",
         "external_resources_templates_list": "外部資料テンプレートの一覧"}
STATUSES = {"awaiting_confirmation": "確認待ち", "applied": "適用済み", "discarded": "破棄済み",
            "expired": "対象が終了しました", "undone": "取り消し済み", "waiting": "待機中",
            "running": "実行中", "completed": "完了", "cancelled": "中止", "failed": "失敗"}


def show_details(parent: QWidget, title: str, content: str) -> None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    dialog.resize(760, 520)
    layout = QVBoxLayout(dialog)
    editor = QPlainTextEdit(dialog)
    editor.setReadOnly(True)
    editor.setPlainText(content)
    layout.addWidget(editor)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
    dialog.deleteLater()
