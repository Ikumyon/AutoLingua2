from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import urllib.error
import urllib.request

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.services.ai_providers.chat import ChatMessage, ChatReply, ChatToolCall
from autolingua2.ui.i18n import is_default_language, system_language

logger = logging.getLogger(__name__)


class TranslationProviderError(RuntimeError):
    """AIプロバイダとの通信または翻訳処理で発生したエラー。"""
    pass


class TextTranslator(Protocol):
    """テキスト翻訳を実行する公開プロトコル契約。"""

    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        tone: str | None = None,
    ) -> str: ...


@runtime_checkable
class AiProviderPlugin(Protocol):
    """AIプロバイダプラグインの公開プロトコル契約。"""

    id: str
    display_name: str
    api_key_env: str
    default_models: tuple[tuple[str, str], ...]

    def create(self, api_key: str, model: str) -> TextTranslator: ...

    def create_settings_widget(
        self,
        parent: Any = None,
        *,
        current_api_key: str = "",
        on_api_key_changed: Any = None,
    ) -> Any | None: ...


MASTER_SYSTEM_PROMPT = (
    "あなたはゲーム翻訳者です。与えられたテキストを{source_language}から{target_language}に翻訳してください。\n"
    "翻訳結果のみを出力してください。\n"
    "{tone_section}"
)

PROMPT_CACHE_FILE = PROJECT_ROOT / ".runtime" / "cache" / "prompts_cache.json"


def get_prompt_hash(text: str) -> str:
    """プロンプト原本のSHA-256ハッシュ（先頭16文字）を返します。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_prompt_cache() -> dict[str, dict[str, str]]:
    if PROMPT_CACHE_FILE.is_file():
        try:
            with open(PROMPT_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as exc:
            logger.warning("プロンプトキャッシュの読み込みに失敗しました: %s", exc)
    return {}


def _save_prompt_cache(cache_data: dict[str, dict[str, str]]) -> None:
    try:
        PROMPT_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PROMPT_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("プロンプトキャッシュの保存に失敗しました: %s", exc)


def build_system_prompt_template(
    target_language: str | None = None,
    translator: BaseHttpTranslator | None = None,
    *,
    allow_sync_translation: bool = False,
) -> str:
    """言語に応じたシステムプロンプトのテンプレートを取得します。

    デフォルト言語（ja-JP）の場合は原本を即座に返します。
    他言語でキャッシュがない場合、安全ガード（allow_sync_translation）が有効な場合のみ
    翻訳を実行し、それ以外（接続テスト中など）は原本を返してUIフリーズを防ぎます。
    """
    # 口調システムは、ユーザーが自然言語の母語で指示を書くことを想定している。
    # 日本語の共通指示文と母語の口調指示が混在するのを防ぐため、
    # 共通指示文をOS言語へ翻訳し、ユーザーが口調を書く言語に合わせる。
    lang = target_language or system_language()
    if is_default_language(lang):
        return MASTER_SYSTEM_PROMPT

    # 同じ原本は翻訳済みテンプレートを再利用し、指示文の翻訳を繰り返さない。
    # 原本の改訂後に古い翻訳を使わないよう、ハッシュで更新を検出する。
    current_hash = get_prompt_hash(MASTER_SYSTEM_PROMPT)
    cache = _load_prompt_cache()
    cached_entry = cache.get(lang)

    if (
        cached_entry
        and cached_entry.get("source_hash") == current_hash
        and "prompt" in cached_entry
    ):
        return cached_entry["prompt"]

    # キャッシュ未作成かつ同期翻訳が明示的に許可されている場合のみ実行（UIフリーズ防止）
    if allow_sync_translation and translator is not None:
        try:
            translated = translator.translate(MASTER_SYSTEM_PROMPT, "Japanese", lang)
            if "{source_language}" in translated and "{target_language}" in translated:
                cache[lang] = {
                    "source_hash": current_hash,
                    "prompt": translated,
                }
                _save_prompt_cache(cache)
                return translated
        except Exception as exc:
            logger.warning("言語(%s)へのプロンプト翻訳に失敗しました: %s", lang, exc)

    return MASTER_SYSTEM_PROMPT


class BaseHttpTranslator(TextTranslator, ABC):
    """すべてのHTTPベースAI翻訳プロバイダの共通抽象基底クラス。

    通信制御、タイムアウト管理、共通HTTPエラーハンドリング、プロンプト生成を集約し、
    各プロバイダはAPI差分（エンドポイント、ヘッダー、JSON構造）のみを実装します。
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout = timeout

        if not self.api_key:
            raise TranslationProviderError("APIキーが指定されていません。")
        if not self.model:
            raise TranslationProviderError("モデル名が指定されていません。")

    @property
    @abstractmethod
    def endpoint(self) -> str:
        """APIエンドポイントURL。"""
        ...

    @abstractmethod
    def build_headers(self) -> dict[str, str]:
        """APIリクエストヘッダー（認証トークン等）を構築して返します。"""
        ...

    @abstractmethod
    def build_payload(
        self,
        text: str,
        source_language: str,
        target_language: str,
        system_prompt: str,
    ) -> dict[str, Any]:
        """APIリクエストのJSONペイロードを構築して返します。"""
        ...

    @abstractmethod
    def extract_translation(self, response_data: dict[str, Any]) -> str:
        """APIレスポンスのJSONから翻訳後テキストを抽出して返します。"""
        ...

    supports_chat = False

    def build_chat_payload(
        self, messages: list[ChatMessage], system_prompt: str,
        tools: list[dict[str, Any]], continuation: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raise NotImplementedError("このプロバイダはチャットに対応していません。")

    def extract_chat_reply(self, data: dict[str, Any]) -> ChatReply:
        raise NotImplementedError("このプロバイダはチャットに対応していません。")

    def chat_tool_result(self, call: ChatToolCall, result: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("このプロバイダはチャットに対応していません。")

    def extract_custom_error(self, error_data: dict[str, Any] | None, status_code: int) -> str | None:
        """プロバイダ固有のエラー形式からメッセージを抽出します（任意実装）。"""
        return None

    def build_system_prompt(
        self,
        source_language: str,
        target_language: str,
        tone: str | None = None,
        *,
        allow_sync_translation: bool = False,
    ) -> str:
        """ゲーム翻訳用のシステムプロンプトを構築します。"""
        template = build_system_prompt_template(
            system_language(),
            translator=self,
            allow_sync_translation=allow_sync_translation,
        )
        # ユーザーが母語で記述した口調指示を、OS言語に合わせた共通指示文へ差し込む。
        tone_section = f"口調: {tone}\n" if tone and tone.strip() else ""
        return template.format(
            source_language=source_language,
            target_language=target_language,
            tone_section=tone_section,
        )

    def translate(
        self,
        text: str,
        source_language: str,
        target_language: str,
        tone: str | None = None,
    ) -> str:
        if not text.strip():
            return text

        system_prompt = self.build_system_prompt(
            source_language, target_language, tone=tone, allow_sync_translation=True
        )
        payload = self.build_payload(text, source_language, target_language, system_prompt)
        headers = self.build_headers()

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status_code = response.getcode()
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            error_message = self._resolve_http_error(raw_error, exc.code)
            logger.error("AI Provider HTTPError %d: %s", exc.code, error_message)
            raise TranslationProviderError(error_message) from exc
        except urllib.error.URLError as exc:
            logger.error("AI Provider URLError: %s", exc.reason)
            raise TranslationProviderError(f"APIサーバーへの接続に失敗しました: {exc.reason}") from exc
        except TimeoutError as exc:
            logger.error("AI Provider timeout after %.1fs", self.timeout)
            raise TranslationProviderError(f"APIリクエストがタイムアウトしました ({self.timeout}秒)") from exc
        except Exception as exc:
            logger.error("AI Provider unexpected error: %s", exc)
            raise TranslationProviderError(f"翻訳中に予期しないエラーが発生しました: {exc}") from exc

        return self._parse_response(response_body)

    def _resolve_http_error(self, raw_json: str, status_code: int) -> str:
        error_data: dict[str, Any] | None = None
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                error_data = parsed
        except Exception:
            pass

        custom_msg = self.extract_custom_error(error_data, status_code)
        if custom_msg:
            return custom_msg

        if status_code == 401:
            return "APIキーが無効または設定されていません。"
        if status_code == 429:
            return "APIレートリミットまたは利用可能残高（Quota）を超過しました。"
        if status_code == 404:
            return f"指定されたモデル '{self.model}' が見つかりません。"
        if status_code >= 500:
            return f"APIサーバー側で一時的なエラーが発生しました (HTTP {status_code})。"
        return f"APIリクエストエラー (HTTP {status_code})"

    def _parse_response(self, response_body: str) -> str:
        try:
            data = json.loads(response_body)
            if not isinstance(data, dict):
                raise ValueError("Response root is not a JSON object")
            return self.extract_translation(data)
        except TranslationProviderError:
            raise
        except Exception as exc:
            logger.error("Failed to parse API response: %s", exc)
            raise TranslationProviderError(f"APIレスポンスの解析に失敗しました: {exc}") from exc


class BaseAiProvider(AiProviderPlugin, ABC):
    """すべてのAIプロバイダプラグインの共通基底クラス。"""

    id: str = ""
    display_name: str = ""
    api_key_env: str = ""
    default_models: tuple[tuple[str, str], ...] = ()
    translator_class: type[BaseHttpTranslator]

    def create(self, api_key: str, model: str) -> TextTranslator:
        return self.translator_class(api_key=api_key, model=model)

    def create_settings_widget(
        self,
        parent: Any = None,
        *,
        current_api_key: str = "",
        on_api_key_changed: Any = None,
    ) -> Any | None:
        """設定ダイアログのスタックに表示するプロバイダー固有ウィジェット（None の場合は標準APIキー画面）。"""
        return None
