from __future__ import annotations

from collections import Counter, deque
from collections.abc import Mapping
from functools import lru_cache
import json
from pathlib import Path
import re
from uuid import uuid4
import xml.etree.ElementTree as ET
import PySide6

from PySide6.QtCore import QIODevice, QObject, QProcess, QSaveFile, QStandardPaths, QTemporaryDir, QLibraryInfo, Signal
from PySide6.QtCore import QTranslator

from autolingua2.infrastructure.filesystem import ASSETS_DIR, PROJECT_ROOT
from autolingua2.ir.localization import LanguageInfo, TranslationCoverage, UiMessage
from autolingua2.ir.validation import record, text
from autolingua2.services.ai.ai_network import AiNetworkClient
from autolingua2.services.ai_providers.registry import ProviderRegistry
from autolingua2.services.settings.language_tags import fallback_tags, is_default_language, normalize_language
from autolingua2.services.settings.settings_store import load_ai_settings


@lru_cache(maxsize=1)
def source_messages() -> tuple[UiMessage, ...]:
    result: list[UiMessage] = []
    for path in sorted((ASSETS_DIR / "i18n").glob("*.ts")):
        document = ET.parse(path).getroot()
        for context in document.findall("context"):
            for message in context.findall("message"):
                source = message.findtext("source", "")
                if source:
                    result.append(UiMessage(context.findtext("name", ""), source,
                                            message.findtext("translation", source), message.findtext("comment", ""),
                                            path.name, message.findtext("extracomment", "")))
    if not result:
        raise ValueError("本体UIの原文カタログが空です。")
    return tuple(result)


def existing_translations(tag: str, languages: Mapping[str, LanguageInfo]) -> dict[tuple[str, str, str], str]:
    messages = source_messages()
    if is_default_language(tag):
        return {message.key: message.original for message in messages}
    translators: list[QTranslator] = []
    for candidate in fallback_tags(tag):
        info = languages.get(candidate)
        if info is None:
            continue
        for path in reversed(info.qm_paths):
            translator = QTranslator()
            if translator.load(str(path)):
                translators.append(translator)
    result: dict[tuple[str, str, str], str] = {}
    for message in messages:
        for translator in translators:
            translated = translator.translate(message.context, message.source, message.comment)
            if translated:
                result[message.key] = translated
                break
    return result


def coverage(tag: str, languages: Mapping[str, LanguageInfo]) -> TranslationCoverage:
    tag = normalize_language(tag)
    existing = existing_translations(tag, languages)
    return TranslationCoverage(tag, len(source_messages()), len(source_messages()) - len(existing))


def _protected(value: str) -> Counter[str]:
    return Counter(re.findall(
        r"\{\{|\}\}|\{[^{}]+\}|%(?:L?\d+|n)|</?[A-Za-z][^>]*>|https?://[^\s<>]+|&|\b(?:Ctrl|Alt|Shift|Meta)(?:\+[A-Za-z0-9]+)+",
        value,
    ))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("AIの応答に重複する項目があります。")
        result[key] = value
    return result


def _write(path: Path, data: bytes) -> None:
    file = QSaveFile(str(path))
    if not file.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(file.errorString())
    if file.write(data) != len(data):
        file.cancelWriting()
        raise OSError(file.errorString())
    if not file.commit():
        raise OSError(file.errorString())


def translation_catalogs(tag: str, values: Mapping[tuple[str, str, str], str]) -> dict[str, bytes]:
    """Build context catalogs from packaged originals, independent of the UI."""
    roots: dict[str, ET.Element] = {}
    contexts: dict[tuple[str, str], ET.Element] = {}
    for message in source_messages():
        root = roots.get(message.filename)
        if root is None:
            root = ET.Element("TS", version="2.1", language=normalize_language(tag), sourcelanguage="ja")
            if message.context == "LanguageNames":
                root.append(ET.Comment("Language names: Unicode CLDR 48.0.0, main/ja. Unicode License v3; see CLDR-LICENSE.txt."))
            roots[message.filename] = root
        section = contexts.get((message.filename, message.context))
        if section is None:
            section = ET.SubElement(root, "context")
            ET.SubElement(section, "name").text = message.context
            contexts[(message.filename, message.context)] = section
        item = ET.SubElement(section, "message")
        ET.SubElement(item, "source").text = message.source
        if message.comment:
            ET.SubElement(item, "comment").text = message.comment
        notes = [message.extra_comment] if message.extra_comment else []
        if message.original != message.source:
            notes.append(message.original)
        if notes:
            ET.SubElement(item, "extracomment").text = "\n".join(notes)
        translated = values.get(message.key, "")
        translation = ET.SubElement(item, "translation")
        translation.text = translated
        if not translated:
            translation.set("type", "unfinished")
    catalogs: dict[str, bytes] = {}
    for filename, root in roots.items():
        ET.indent(root, space="  ")
        catalogs[filename] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return catalogs


def export_ts(folder: Path, tag: str, *, overwrite: bool = False) -> int:
    """Export untranslated TS and its license; restore overwritten files on failure."""
    catalogs = translation_catalogs(tag, {})
    count = len(catalogs)
    catalogs["CLDR-LICENSE.txt"] = (ASSETS_DIR / "i18n/CLDR-LICENSE.txt").read_bytes()
    conflicts = [folder / name for name in catalogs if (folder / name).exists()]
    for path in conflicts:
        if not path.is_file():
            raise IsADirectoryError(str(path))
    if conflicts and not overwrite:
        raise FileExistsError("\n".join(str(path) for path in conflicts))
    originals: dict[Path, bytes | None] = {}
    try:
        for filename, data in catalogs.items():
            path = folder / filename
            originals[path] = path.read_bytes() if path.is_file() else None
            _write(path, data)
    except Exception:
        for path, original in reversed(tuple(originals.items())):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _write(path, original)
        raise
    return count


class UiTranslationService(QObject):
    progress = Signal(int, int)
    running_changed = Signal(bool)
    failed = Signal(str)
    completed = Signal(str, str)  # tag, committed resource folder
    cancelled = Signal()

    def __init__(self, registry: ProviderRegistry, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.client = AiNetworkClient(self)
        self.client.translation_completed.connect(self._translated)
        self.client.translation_failed.connect(self._network_failed)
        self.process = QProcess(self)
        self.process.finished.connect(self._compiled)
        self.process.errorOccurred.connect(self._process_failed)
        self.busy = False
        self._queue: deque[tuple[UiMessage, ...]] = deque()
        self._pending: dict[str, UiMessage] = {}
        self._request = ""
        self._values: dict[tuple[str, str, str], str] = {}
        self._tag = ""
        self._name = ""
        self._provider_id = ""
        self._model = ""
        self._api_key = ""
        self._done = 0
        self._total = 0
        self._folder = PROJECT_ROOT / "translations"
        self._temporary: QTemporaryDir | None = None
        self._lrelease = ""
        self._published: dict[Path, bytes | None] = {}
        self._compile_queue: deque[str] = deque()
        self._catalog_names: tuple[str, ...] = ()
        self._compiling = ""

    def start(self, tag: str, name: str, provider_id: str, model: str,
              languages: Mapping[str, LanguageInfo]) -> None:
        if self.busy or self.process.state() != QProcess.ProcessState.NotRunning:
            raise RuntimeError("翻訳はすでに実行中です。")
        tag = normalize_language(tag)
        if not name.strip():
            raise ValueError("言語の表示名を入力してください。")
        settings = load_ai_settings(self.registry)
        provider = self.registry.get(provider_id)
        api_key = settings.api_keys.get(provider_id, "") or self.registry.get_env_api_key(provider_id)
        if provider is None or not api_key or not model:
            raise ValueError("AI設定を保存し、利用するAIとモデルを選択してください。")
        if not any(item.enabled and item.model == model for item in settings.models.get(provider_id, [])):
            raise ValueError("保存済みの有効なモデルを選択してください。")
        self._lrelease = QStandardPaths.findExecutable("lrelease", [
            str(Path(PySide6.__file__).parent), QLibraryInfo.path(QLibraryInfo.LibraryPath.LibraryExecutablesPath),
            QLibraryInfo.path(QLibraryInfo.LibraryPath.BinariesPath),
        ])
        if not self._lrelease:
            raise RuntimeError("Qtの翻訳コンパイラが見つかりません。")
        existing = existing_translations(tag, languages)
        missing = [message for message in source_messages() if message.key not in existing]
        if not missing:
            raise ValueError("この言語の表示文言はすでに揃っています。")
        self._values = existing
        info = languages.get(tag)
        self._folder = info.folder if info is not None else PROJECT_ROOT / "translations" / tag
        self._tag, self._name = tag, name.strip()
        self._provider_id, self._model, self._api_key = provider_id, model, api_key
        self._queue.clear()
        batch: list[UiMessage] = []
        size = 0
        for message in missing:
            if len(message.original) > 8000:
                raise ValueError("原文が1項目の翻訳上限（8000文字）を超えています。")
            if batch and (len(batch) >= 50 or size + len(message.original) > 8000):
                self._queue.append(tuple(batch))
                batch, size = [], 0
            batch.append(message)
            size += len(message.original)
        if batch:
            self._queue.append(tuple(batch))
        self._done, self._total = 0, len(missing)
        self._published.clear()
        self.busy = True
        self.running_changed.emit(True)
        self.progress.emit(0, self._total)
        self._send()

    def _send(self) -> None:
        if not self.busy:
            return
        if not self._queue:
            self._compile()
            return
        provider = self.registry.get(self._provider_id)
        if provider is None:
            self._fail("選択したAIは利用できません。")
            return
        batch = self._queue.popleft()
        self._pending = {str(index): message for index, message in enumerate(batch)}
        self._request = uuid4().hex
        payload = json.dumps({key: {"source": message.source, "original": message.original,
                                   "context": message.context,
                                   "comment": "\n".join(note for note in (message.comment, message.extra_comment) if note)}
                              for key, message in self._pending.items()}, ensure_ascii=False)
        self.client.translate_text(self._request, provider, self._api_key, self._model, payload,
                                   "ja", self._tag, target_language_name=self._name, purpose="ui")

    def _translated(self, request_id: str, response: str) -> None:
        if not self.busy or request_id != self._request:
            return
        try:
            values = record(json.loads(response, object_pairs_hook=_unique_object))
            if set(values) != set(self._pending):
                raise ValueError("AIの応答に項目の不足・重複・余分な項目があります。")
            for key, message in self._pending.items():
                translated = text(values[key], nonempty=True)
                if _protected(message.original) != _protected(translated):
                    raise ValueError(f"書式指定またはHTMLが変更されています: {message.original}")
                self._values[message.key] = translated
            self._done += len(self._pending)
            self._pending.clear()
            self.progress.emit(self._done, self._total)
            self._send()
        except Exception as error:
            self._fail(str(error))

    def _compile(self) -> None:
        try:
            temporary = QTemporaryDir()
            if not temporary.isValid():
                raise OSError("翻訳用の一時フォルダを作成できません。")
            self._temporary = temporary
            catalogs = translation_catalogs(self._tag, self._values)
            self._catalog_names = tuple(catalogs)
            self._compile_queue = deque(catalogs)
            for filename, data in catalogs.items():
                _write(Path(temporary.path()) / filename, data)
            self._compile_next()
        except Exception as error:
            self._fail(str(error))

    def _compile_next(self) -> None:
        temporary = self._temporary
        if temporary is None:
            raise RuntimeError("翻訳用の一時フォルダがありません。")
        if not self._compile_queue:
            self._publish()
            return
        self._compiling = self._compile_queue.popleft()
        ts_path = Path(temporary.path()) / self._compiling
        self.process.start(self._lrelease, [str(ts_path), "-qm", str(ts_path.with_suffix(".qm"))])

    def _compiled(self, code: int, status: QProcess.ExitStatus) -> None:
        if not self.busy:
            self._temporary = None
            return
        try:
            if code != 0 or status != QProcess.ExitStatus.NormalExit:
                raise RuntimeError(bytes(self.process.readAllStandardError().data()).decode("utf-8", errors="replace") or "翻訳辞書のコンパイルに失敗しました。")
            temporary = self._temporary
            if temporary is None:
                raise RuntimeError("翻訳用の一時フォルダがありません。")
            qm_path = (Path(temporary.path()) / self._compiling).with_suffix(".qm")
            translator = QTranslator()
            if not translator.load(str(qm_path)):
                raise ValueError(f"生成した翻訳辞書を読み込めません: {qm_path.name}")
            self._compile_next()
        except Exception as error:
            self._fail(str(error))

    def _publish(self) -> None:
        temporary = self._temporary
        if temporary is None:
            raise RuntimeError("翻訳用の一時フォルダがありません。")
        self._folder.mkdir(parents=True, exist_ok=True)
        for filename in self._catalog_names:
            qm_name = Path(filename).with_suffix(".qm").name
            destination = self._folder / qm_name
            self._published[destination] = destination.read_bytes() if destination.is_file() else None
            _write(destination, (Path(temporary.path()) / qm_name).read_bytes())
        metadata = self._folder / "metadata.json"
        if not metadata.exists():
            self._published[metadata] = None
            _write(metadata, json.dumps({"code": self._tag, "name": self._name}, ensure_ascii=False, indent=2).encode("utf-8"))
        # The legacy QM was read through existing_translations before replacement.
        # Remove both legacy artifacts only after every new QM has been compiled.
        for filename in ("personal.ts", "personal.qm"):
            path = self._folder / filename
            if path.is_file():
                self._published[path] = path.read_bytes()
                path.unlink()
        # Keep busy until resource registration and language switching succeed.
        self.completed.emit(self._tag, str(self._folder))

    def confirm(self) -> None:
        self._published.clear()
        self._finish()

    def reject(self, message: str) -> None:
        self._fail(message)

    def _network_failed(self, request_id: str, message: str) -> None:
        if self.busy and request_id == self._request:
            self._fail(message)

    def _process_failed(self, error: QProcess.ProcessError) -> None:
        if self.busy:
            self._fail(self.process.errorString())

    def _rollback(self) -> None:
        for path, original in reversed(tuple(self._published.items())):
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _write(path, original)
        self._published.clear()

    def _finish(self) -> None:
        self.busy = False
        self._request = ""
        self.client.cancel_all()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
        else:
            self._temporary = None
        self._queue.clear()
        self.running_changed.emit(False)
        self._compile_queue.clear()
        self._catalog_names = ()
        self._compiling = ""

    def _fail(self, message: str) -> None:
        try:
            self._rollback()
        except Exception as error:
            message += f"\n辞書の復元に失敗しました: {error}"
        self._finish()
        self.failed.emit(message)

    def cancel(self) -> None:
        if self.busy:
            self._fail("翻訳を中止しました。")
            self.cancelled.emit()
