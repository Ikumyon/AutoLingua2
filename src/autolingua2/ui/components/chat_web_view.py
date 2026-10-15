from __future__ import annotations

from autolingua2.ui.i18n import translation_source

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QEvent, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QPalette
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage, QWebEngineProfile, QWebEngineUrlRequestInfo, QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from autolingua2.infrastructure.filesystem import ASSETS_DIR
from autolingua2.ui.i18n import tr
from autolingua2.ui.operation_panel import NAMES, STATUSES


logger = logging.getLogger(__name__)


class ChatRequests(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        allowed = url.scheme() in {"data", "blob", "about"}
        if url.scheme() == "qrc":
            allowed = url.path() == "/qtwebchannel/qwebchannel.js"
        elif url.isLocalFile():
            allowed = Path(url.toLocalFile()).resolve().is_relative_to((ASSETS_DIR / "chat").resolve())
        info.block(not allowed)
        if not allowed:
            logger.warning("Chat web request blocked: %s", url.toString())


class ChatPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level: QWebEnginePage.JavaScriptConsoleMessageLevel,
                                 message: str, lineNumber: int, sourceID: str) -> None:
        severity = {
            QWebEnginePage.JavaScriptConsoleMessageLevel.InfoMessageLevel: logging.INFO,
            QWebEnginePage.JavaScriptConsoleMessageLevel.WarningMessageLevel: logging.WARNING,
            QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel: logging.ERROR,
        }[level]
        logger.log(severity, "Chat JavaScript: %s (%s:%s)", message, sourceID, lineNumber)

    def acceptNavigationRequest(self, url: QUrl | str, type: QWebEnginePage.NavigationType,
                                isMainFrame: bool) -> bool:
        url = QUrl(url)
        if not isMainFrame:
            return url.scheme() in {"about", "data", "blob"}
        if url.scheme() == "data":
            return not (ASSETS_DIR / "chat/index.html").is_file()
        return url.isLocalFile() and Path(url.toLocalFile()).resolve() == (ASSETS_DIR / "chat/index.html").resolve()


class ChatBridge(QObject):
    changed = Signal(str)

    def __init__(self, view: ChatWebView) -> None:
        super().__init__(view)
        self.view = view

    @Slot(str)
    def ready(self, instructions: str) -> None:
        logger.info("Chat web bridge connected")
        self.view.is_ready = True
        self.view.ready.emit(instructions)
        self.view.publish()

    @Slot(str)
    def act(self, payload: str) -> None:
        self.view.action_requested.emit(payload)


class ChatWebView(QWebEngineView):
    ready = Signal(str)
    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_ready = False
        self.busy = False
        self.markdown_icon = ""
        self.items: dict[str, dict[str, Any]] = {}
        profile = QWebEngineProfile(self)
        self._requests = ChatRequests(profile)
        profile.setUrlRequestInterceptor(self._requests)
        self.setPage(ChatPage(profile, self))
        self._channel = QWebChannel(self.page())
        self._bridge = ChatBridge(self)
        self._channel.registerObject("chat", self._bridge)
        self.page().setWebChannel(self._channel)
        self.loadStarted.connect(self._load_started)
        self.loadFinished.connect(self._load_finished)
        self.page().renderProcessTerminated.connect(self._render_terminated)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        index = ASSETS_DIR / "chat/index.html"
        logger.info("Chat web initialization: %s (built=%s)", index, index.is_file())
        if index.is_file():
            self.load(QUrl.fromLocalFile(str(index.resolve())))
        else:
            self.setHtml("<html lang='ja'><body><p>チャット表示を先にビルドしてください。</p>"
                         "<code>cd web<br>npm install --include=peer --no-package-lock --ignore-scripts<br>npm run build</code></body></html>")

    @Slot()
    def _load_started(self) -> None:
        logger.info("Chat web load started")

    @Slot(bool)
    def _load_finished(self, success: bool) -> None:
        logger.log(logging.INFO if success else logging.ERROR,
                   "Chat web load finished: success=%s url=%s", success, self.url().toString())

    def _render_terminated(self, status: QWebEnginePage.RenderProcessTerminationStatus,
                           exit_code: int) -> None:
        logger.error("Chat web renderer terminated: status=%s exit_code=%s", status.name, exit_code)

    def append(self, role: str, text: str, model: str = "", provider: str = "", icon: str = "") -> None:
        key = uuid4().hex
        self.items[key] = {"id": key, "kind": "message", "role": role, "text": text, "model": model,
                           "provider": provider, "icon": icon}
        self.publish()

    def update_document(self, kind: str, document: dict[str, Any]) -> None:
        key = f"{kind}:" + str(document["operation_id" if kind == "operation" else "id"])
        self.items[key] = {"id": key, "kind": kind, "document": document}
        self.publish()

    def reset(self) -> None:
        self.items.clear()
        self.publish()

    def publish(self) -> None:
        if not self.is_ready:
            return
        palette = self.palette()
        labels = {key: tr("AiChat", label) for key, label in {
            "copy": translation_source('AiChat', 'コピー'), "copied": translation_source('AiChat', 'コピーしました'), "source": translation_source('AiChat', '原文'),
            "preview": translation_source('AiChat', 'プレビュー'), "code": translation_source('AiChat', 'コード'), "expand": translation_source('AiChat', '拡大'), "close": translation_source('AiChat', '閉じる'),
            "latest": translation_source('AiChat', '最新へ'), "empty": translation_source('AiChat', 'AIへの依頼を入力してください。ファイルや選択行を文中に挿入できます。'),
            "error": translation_source('AiChat', 'エラー'), "operation": translation_source('AiChat', '操作'), "apply": translation_source('AiChat', '選択した変更を適用'),
            "discard": translation_source('AiChat', '破棄'), "undo": translation_source('AiChat', '変更を取り消す'), "view": translation_source('AiChat', '対象を表示'),
            "cancel": translation_source('AiChat', '中止'), "results": translation_source('AiChat', '結果を表示'), "before": translation_source('AiChat', '現在'), "after": translation_source('AiChat', '提案'),
            "invalid": translation_source('AiChat', '構造化UIの形式が不正です'), "reply": translation_source('AiChat', '操作結果をAIへ送信'),
            "selected": translation_source('AiChat', '選択'), "thinking": translation_source('AiChat', 'AIが応答しています…'), "math": translation_source('AiChat', '数式をコピー'),
            "table": translation_source('AiChat', '表をコピー'), "markdown": translation_source('AiChat', 'Markdown原文'), "selectAll": translation_source('AiChat', 'すべて選択'),
        }.items()}
        labels.update({f"name:{key}": tr("AiChat", value) for key, value in NAMES.items()})
        labels.update({f"status:{key}": tr("AiChat", value) for key, value in STATUSES.items()})
        labels.update({f"field:{key}": tr("AiChat", value) for key, value in {
            "target_text": translation_source('AiChat', '訳文'), "translation": translation_source('AiChat', '訳文'), "source": translation_source('AiChat', '原文・用語'), "name": translation_source('AiChat', '名称'),
            "prompt": translation_source('AiChat', '口調'), "review": translation_source('AiChat', 'レビュー'), "rationale": translation_source('AiChat', '採用理由'), "candidates": translation_source('AiChat', '候補'),
            "memo": translation_source('AiChat', 'メモ'), "notes": translation_source('AiChat', '翻訳メモ'), "terms": translation_source('AiChat', '用語候補'), "path": translation_source('AiChat', '保存先'),
        }.items()})
        base_color = palette.color(QPalette.ColorRole.Base)
        dark = base_color.lightness() < 128
        colors = {key: palette.color(role).name() for key, role in {
            "base": QPalette.ColorRole.Base, "text": QPalette.ColorRole.Text,
            "border": QPalette.ColorRole.Mid,
            "accent": QPalette.ColorRole.Link,
        }.items()}
        # QSS themes may set Base/Text while leaving AlternateBase at its light default.
        colors["alternate"] = (base_color.lighter(120) if dark else base_color.darker(105)).name()
        accent = palette.color(QPalette.ColorRole.Link)
        channels = [channel / 255 for channel in (accent.red(), accent.green(), accent.blue())]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
                  for channel in channels]
        luminance = sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
        colors["accent-text"] = "#000000" if (luminance + 0.05) / 0.05 >= 1.05 / (luminance + 0.05) else "#ffffff"
        self._bridge.changed.emit(json.dumps({"items": list(self.items.values()), "busy": self.busy,
            "labels": labels, "colors": colors, "markdownIcon": self.markdown_icon,
            "dark": dark}, ensure_ascii=False, default=str))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.LanguageChange, QEvent.Type.FontChange}:
            self.publish()
