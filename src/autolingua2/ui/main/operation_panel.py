"""Localized operation labels and the native, read-only material viewer."""
from autolingua2.ui.resources.i18n import translation_source
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout, QWidget

NAMES = {"set_language": translation_source('AiChat', '言語設定の変更'), "edit_units": translation_source('AiChat', '訳文・翻訳メモの変更'), "edit_glossary": translation_source('AiChat', '用語集の変更'), "edit_term": translation_source('AiChat', '用語の変更'),
         "edit_tone": translation_source('AiChat', '口調の変更'), "set_preferences": translation_source('AiChat', '用語集・口調の適用'), "start_translation": translation_source('AiChat', '翻訳'),
         "translation": translation_source('AiChat', '翻訳'), "review_units": translation_source('AiChat', 'AIレビュー'), "review": translation_source('AiChat', 'AIレビュー'),
         "source_changes": translation_source('AiChat', '原文の差分確認'), "apply_source_update": translation_source('AiChat', '原文の取り込み'), "source_update": translation_source('AiChat', '原文の取り込み'),
         "save_project": translation_source('AiChat', 'プロジェクト保存'), "export_plan": translation_source('AiChat', '書き出し内容の確認'), "start_export": translation_source('AiChat', '書き出し'),
         "export": translation_source('AiChat', '書き出し'), "external_resources_list": translation_source('AiChat', '外部資料の一覧'), "external_resources_read": translation_source('AiChat', '外部資料の取得'),
         "external_resources_templates_list": translation_source('AiChat', '外部資料テンプレートの一覧')}
STATUSES = {"awaiting_confirmation": translation_source('AiChat', '確認待ち'), "applied": translation_source('AiChat', '適用済み'), "discarded": translation_source('AiChat', '破棄済み'),
            "expired": translation_source('AiChat', '対象が終了しました'), "undone": translation_source('AiChat', '取り消し済み'), "waiting": translation_source('AiChat', '待機中'),
            "running": translation_source('AiChat', '実行中'), "completed": translation_source('AiChat', '完了'), "cancelled": translation_source('AiChat', '中止'), "failed": translation_source('AiChat', '失敗')}


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
