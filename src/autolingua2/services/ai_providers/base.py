from __future__ import annotations

from abc import ABC, abstractmethod
import json
import logging
from typing import Any, Protocol, runtime_checkable
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)


class TranslationProviderError(RuntimeError):
    """AIプロバイダとの通信または翻訳処理で発生したエラー。"""
    pass


class TextTranslator(Protocol):
    """テキスト翻訳を実行する公開プロトコル契約。"""

    def translate(self, text: str, source_language: str, target_language: str) -> str: ...


@runtime_checkable
class AiProviderPlugin(Protocol):
    """AIプロバイダプラグインの公開プロトコル契約。"""

    id: str
    display_name: str
    api_key_env: str
    default_models: tuple[tuple[str, str], ...]

    def create(self, api_key: str, model: str) -> TextTranslator: ...


DEFAULT_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional video game localization translator. "
    "Translate the given text from {source_language} to {target_language}.\n"
    "Rules:\n"
    "1. Preserve all placeholders, variables, tags, and formatting codes exactly as they are "
    "(e.g., §Y, §!, [Tag], $VAR$, %s, \\n, etc.).\n"
    "2. Use natural and context-appropriate video game dialogue or UI phrasing.\n"
    "3. Output ONLY the translated text. Do not include commentary, explanations, greetings, or markdown quotes."
)


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

    def build_system_prompt(self, source_language: str, target_language: str) -> str:
        """ゲーム翻訳用のシステムプロンプトを構築します。"""
        return DEFAULT_SYSTEM_PROMPT_TEMPLATE.format(
            source_language=source_language,
            target_language=target_language,
        )

    def translate(self, text: str, source_language: str, target_language: str) -> str:
        if not text.strip():
            return text

        system_prompt = self.build_system_prompt(source_language, target_language)
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
