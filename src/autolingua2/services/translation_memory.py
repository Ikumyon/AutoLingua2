"""Per-game, bidirectional sentence pairs qualified by translation conditions."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import json
import sqlite3
import time

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ir.translation import text_hash


class TranslationMemoryError(RuntimeError):
    """Shared memory is unavailable; project translations remain intact."""


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    language_a: str
    text_a: str
    language_b: str
    text_b: str
    conditions: str
    updated_at: int


class TranslationMemoryStore:
    def __init__(self, root: Path = PROJECT_ROOT / ".runtime" / "translation_memory") -> None:
        self.root = root

    @contextmanager
    def _connection(self, adapter_id: str, game_id: str) -> Iterator[sqlite3.Connection]:
        if not adapter_id or not game_id:
            raise TranslationMemoryError("翻訳メモリのゲーム情報がありません。")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            scope = json.dumps([adapter_id, game_id], ensure_ascii=False)
            connection = sqlite3.connect(self.root / f"{text_hash(scope)}.sqlite3")
            try:
                with connection:
                    connection.execute("""CREATE TABLE IF NOT EXISTS sentence_pairs (
                        language_a TEXT NOT NULL, text_a TEXT NOT NULL, hash_a TEXT NOT NULL,
                        language_b TEXT NOT NULL, text_b TEXT NOT NULL, hash_b TEXT NOT NULL,
                        conditions TEXT NOT NULL, conditions_hash TEXT NOT NULL,
                        user_confirmed INTEGER NOT NULL, updated_at INTEGER NOT NULL,
                        PRIMARY KEY (language_a, text_a, language_b, text_b, conditions))""")
                    connection.execute("""CREATE INDEX IF NOT EXISTS sentence_pairs_a
                        ON sentence_pairs(language_a, hash_a, conditions_hash)""")
                    connection.execute("""CREATE INDEX IF NOT EXISTS sentence_pairs_b
                        ON sentence_pairs(language_b, hash_b, conditions_hash)""")
                    yield connection
            finally:
                connection.close()
        except (OSError, sqlite3.Error) as exc:
            raise TranslationMemoryError(str(exc)) from exc

    @staticmethod
    def language(value: str) -> str:
        return value.replace("_", "-").lower()

    def lookup(self, adapter_id: str, game_id: str, source_language: str, target_language: str,
               source: str, conditions: str) -> str | None:
        source_language, target_language = self.language(source_language), self.language(target_language)
        with self._connection(adapter_id, game_id) as connection:
            rows = connection.execute("""SELECT language_a, text_a, language_b, text_b, conditions
                FROM sentence_pairs WHERE conditions_hash = ? AND
                ((language_a = ? AND hash_a = ?) OR (language_b = ? AND hash_b = ?))
                ORDER BY user_confirmed DESC, updated_at DESC, text_a, text_b""",
                (text_hash(conditions), source_language, text_hash(source), source_language, text_hash(source)))
            for language_a, text_a, language_b, text_b, stored_conditions in rows:
                if stored_conditions != conditions:
                    continue
                if (language_a, text_a, language_b) == (source_language, source, target_language):
                    return text_b
                if (language_b, text_b, language_a) == (source_language, source, target_language):
                    return text_a
        return None

    def store(self, adapter_id: str, game_id: str, source_language: str, target_language: str,
              pairs: Sequence[tuple[str, str]], conditions: str, *, user_confirmed: bool) -> list[MemoryWrite]:
        created: list[MemoryWrite] = []
        with self._connection(adapter_id, game_id) as connection:
            for source, target in pairs:
                if not source.strip() or not target.strip():
                    raise TranslationMemoryError("空の文は翻訳メモリへ登録できません。")
                (language_a, text_a), (language_b, text_b) = sorted((
                    (self.language(source_language), source), (self.language(target_language), target),
                ))
                existed = connection.execute("""SELECT 1 FROM sentence_pairs WHERE language_a = ? AND text_a = ?
                    AND language_b = ? AND text_b = ? AND conditions = ?""",
                    (language_a, text_a, language_b, text_b, conditions)).fetchone() is not None
                timestamp = time.time_ns()
                connection.execute("""INSERT INTO sentence_pairs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (language_a, text_a, language_b, text_b, conditions) DO UPDATE SET
                    user_confirmed = MAX(sentence_pairs.user_confirmed, excluded.user_confirmed),
                    updated_at = CASE WHEN excluded.user_confirmed >= sentence_pairs.user_confirmed
                        THEN excluded.updated_at ELSE sentence_pairs.updated_at END""",
                    (language_a, text_a, text_hash(text_a), language_b, text_b, text_hash(text_b),
                     conditions, text_hash(conditions), int(user_confirmed), timestamp))
                if not existed and not user_confirmed:
                    created.append(MemoryWrite(language_a, text_a, language_b, text_b, conditions, timestamp))
        return created

    def undo_writes(self, adapter_id: str, game_id: str, writes: Sequence[MemoryWrite]) -> None:
        """Remove only new AI pairs still owned by this operation's write."""
        if not writes:
            return
        with self._connection(adapter_id, game_id) as connection:
            for entry in writes:
                connection.execute("""DELETE FROM sentence_pairs WHERE language_a = ? AND text_a = ?
                    AND language_b = ? AND text_b = ? AND conditions = ?
                    AND user_confirmed = 0 AND updated_at = ?""",
                    (entry.language_a, entry.text_a, entry.language_b, entry.text_b, entry.conditions, entry.updated_at))
