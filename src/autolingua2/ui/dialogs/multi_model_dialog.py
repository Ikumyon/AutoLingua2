from __future__ import annotations

from typing import TYPE_CHECKING
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from autolingua2.ui.i18n import tr
from autolingua2.ui.dialogs.base import load_ui, require_child

if TYPE_CHECKING:
    from autolingua2.services.ai_network import AiNetworkClient
    from autolingua2.services.ai_providers.registry import ProviderRegistry


class ModelResultCard(QFrame):
    """単一モデルの翻訳結果表示カード"""

    adopted = Signal(str)  # 採用された翻訳テキスト

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        model_id: str,
        is_default: bool = False,
        parent: QWidget | None = None,
        *, provider_id: str,
    ) -> None:
        super().__init__(parent)
        self.provider_name = provider_name
        self.provider_id = provider_id
        self.model_name = model_name
        self.model_id = model_id
        self._translated_text: str = ""

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "ModelResultCard {"
            "  background-color: palette(base);"
            "  border: 1px solid palette(mid);"
            "  border-radius: 6px;"
            "  padding: 6px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        # ヘッダー行: モデル名と「この訳を採用」ボタン
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        badge = f" [{tr('MultiModelDialog', '既定')}]" if is_default else ""
        self.label_title = QLabel(f"[{provider_name}] {model_name}{badge}", self)
        self.label_title.setStyleSheet("font-weight: 600;")
        header_layout.addWidget(self.label_title)

        header_layout.addStretch()

        self.button_adopt = QPushButton(tr("MultiModelDialog", "この訳を採用"), self)
        self.button_adopt.setEnabled(False)
        self.button_adopt.clicked.connect(self._on_adopt_clicked)
        header_layout.addWidget(self.button_adopt)

        layout.addLayout(header_layout)

        # 訳文表示エリア
        self.edit_text = QPlainTextEdit(self)
        self.edit_text.setReadOnly(True)
        self.edit_text.setMaximumHeight(80)
        self.edit_text.setPlaceholderText(tr("MultiModelDialog", "翻訳中..."))
        layout.addWidget(self.edit_text)

    def set_loading(self) -> None:
        self.edit_text.setPlainText("")
        self.edit_text.setPlaceholderText(tr("MultiModelDialog", "翻訳中..."))
        self.button_adopt.setEnabled(False)

    def set_result(self, text: str) -> None:
        self._translated_text = text
        self.edit_text.setPlainText(text)
        self.button_adopt.setEnabled(bool(text.strip()))

    def set_error(self, message: str) -> None:
        self._translated_text = ""
        self.edit_text.setPlainText(f"エラー: {message}")
        self.button_adopt.setEnabled(False)

    def _on_adopt_clicked(self) -> None:
        if self._translated_text:
            self.adopted.emit(self._translated_text)


class MultiModelTranslationDialog(QDialog):
    """登録全モデルでの同時翻訳・比較ダイアログ"""

    translation_adopted = Signal(str)

    def __init__(
        self,
        source_text: str,
        active_models: list[tuple[str, str, str, str]],  # (provider_id, provider_name, model_id, model_name)
        providers: ProviderRegistry,
        api_keys_map: dict[str, str],
        default_model_id: str,
        ai_client: AiNetworkClient,
        source_lang: str = "en",
        target_lang: str = "ja",
        parent: QWidget | None = None,
        *, default_provider_id: str = "",
        source_language_name: str = "",
        target_language_name: str = "",
    ) -> None:
        super().__init__(parent)
        self.source_text = source_text
        self.active_models = active_models
        self.providers = providers
        self.api_keys_map = api_keys_map
        self.default_model_id = default_model_id
        self.default_provider_id = default_provider_id
        self.ai_client = ai_client
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.source_language_name = source_language_name
        self.target_language_name = target_language_name

        self._cards: dict[str, ModelResultCard] = {}  # req_id -> card
        self._adopted_text: str | None = None

        self._setup_ui()
        self._connect_signals()
        self._start_translations()

    def _setup_ui(self) -> None:
        loaded = load_ui("MultiModelTranslationDialog.ui")
        if not isinstance(loaded, QDialog):
            raise TypeError("MultiModelTranslationDialog.ui は QDialog ではありません")
        self.setWindowTitle(loaded.windowTitle())
        self.resize(loaded.size())
        loaded.setWindowFlags(Qt.WindowType.Widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(loaded)
        self.edit_source = require_child(self, QPlainTextEdit, "editSource")
        self.button_close = require_child(self, QPushButton, "buttonClose")
        self.layout_results_list = require_child(self, QVBoxLayout, "layoutResultsList")

        self.edit_source.setPlainText(self.source_text)
        self.button_close.clicked.connect(self.reject)

        # 各モデルのカードを配置
        for provider_id, provider_name, model_id, model_name in self.active_models:
            is_default = (provider_id == self.default_provider_id and model_id == self.default_model_id)
            card = ModelResultCard(provider_name, model_name, model_id, is_default, self,
                                   provider_id=provider_id)
            card.adopted.connect(self._on_text_adopted)
            self.layout_results_list.addWidget(card)
            req_id = f"multimodel_{provider_id}_{model_id}_{id(card)}"
            self._cards[req_id] = card

        self.layout_results_list.addStretch()

    def _connect_signals(self) -> None:
        self.ai_client.translation_completed.connect(self._on_translation_completed)
        self.ai_client.translation_failed.connect(self._on_translation_failed)

    def _disconnect_signals(self) -> None:
        try:
            self.ai_client.translation_completed.disconnect(self._on_translation_completed)
        except Exception:
            pass
        try:
            self.ai_client.translation_failed.disconnect(self._on_translation_failed)
        except Exception:
            pass

    def _start_translations(self) -> None:
        text = self.source_text.strip()
        if not text:
            return

        for req_id, card in self._cards.items():
            card.set_loading()
            target_p = self.providers.get(card.provider_id)
            target_key = (self.api_keys_map.get(card.provider_id, "").strip()
                          or self.providers.get_env_api_key(card.provider_id))

            if target_p is None or not target_key:
                card.set_error(tr("MultiModelDialog", "APIキー未設定またはプロバイダ無効"))
                continue

            self.ai_client.translate_text(
                request_id=req_id,
                provider=target_p,
                api_key=target_key,
                model=card.model_id,
                text=text,
                source_language=self.source_lang,
                target_language=self.target_lang,
                source_language_name=self.source_language_name,
                target_language_name=self.target_language_name,
            )

    def _on_translation_completed(self, req_id: str, translated_text: str) -> None:
        card = self._cards.get(req_id)
        if card is not None:
            card.set_result(translated_text)

    def _on_translation_failed(self, req_id: str, error_message: str) -> None:
        card = self._cards.get(req_id)
        if card is not None:
            card.set_error(error_message)

    def _on_text_adopted(self, text: str) -> None:
        self._adopted_text = text
        self.translation_adopted.emit(text)
        self._disconnect_signals()
        self.accept()

    def closeEvent(self, event) -> None:
        self._disconnect_signals()
        super().closeEvent(event)

    @property
    def adopted_text(self) -> str | None:
        return self._adopted_text
