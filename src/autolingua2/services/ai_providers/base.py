from __future__ import annotations

from abc import ABC, abstractmethod
import hashlib
import json
import locale
import logging
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
import urllib.error
import urllib.request

from autolingua2.infrastructure.filesystem import PROJECT_ROOT

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


MASTER_SYSTEM_PROMPT = (
    "あなたはゲーム翻訳者です。与えられたテキストを{source_language}から{target_language}に翻訳してください。\n"
    "翻訳結果のみを出力してください。\n"
    "{tone_section}"
)

PROMPT_CACHE_FILE = PROJECT_ROOT / ".runtime" / "cache" / "prompts_cache.json"


def get_prompt_hash(text: str) -> str:
    """プロンプト原本のSHA-256ハッシュ（先頭16文字）を返します。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def get_os_language() -> str:
    """ユーザーのOS言語コード（例: 'ja', 'en'）を取得します。"""
    try:
        lang, _ = locale.getlocale()
        if lang:
            return lang.split("_")[0].lower()
    except Exception:
        pass
    return "ja"


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
    os_language: str,
    translator: BaseHttpTranslator | None = None,
) -> str:
    """OS言語に応じたシステムプロンプトのテンプレートを取得します。

    原本ハッシュを用いてキャッシュの有効性を検証し、未作成または原本変更時は
    AIによりOS言語向けプロンプトを再生成・キャッシュ保存します。
    """
    if os_language == "ja":
        return MASTER_SYSTEM_PROMPT

    current_hash = get_prompt_hash(MASTER_SYSTEM_PROMPT)
    cache = _load_prompt_cache()
    cached_entry = cache.get(os_language)

    if (
        cached_entry
        and cached_entry.get("source_hash") == current_hash
        and "prompt" in cached_entry
    ):
        return cached_entry["prompt"]

    # キャッシュ未作成または原本更新時
    if translator is not None:
        try:
            translated = translator.translate(MASTER_SYSTEM_PROMPT, "Japanese", os_language)
            if "{source_language}" in translated and "{target_language}" in translated:
                cache[os_language] = {
                    "source_hash": current_hash,
                    "prompt": translated,
                }
                _save_prompt_cache(cache)
                return translated
        except Exception as exc:
            logger.warning("OS言語(%s)へのプロンプト翻訳に失敗しました: %s", os_language, exc)

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

    def extract_custom_error(self, error_data: dict[str, Any] | None, status_code: int) -> str | None:
        """プロバイダ固有のエラー形式からメッセージを抽出します（任意実装）。"""
        return None

    def build_system_prompt(
        self,
        source_language: str,
        target_language: str,
        tone: str | None = None,
    ) -> str:
        """ゲーム翻訳用のシステムプロンプトを構築します。"""
        os_lang = get_os_language()
        template = build_system_prompt_template(os_lang, translator=self)
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

        system_prompt = self.build_system_prompt(source_language, target_language, tone=tone)
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
