"""Game-scoped, undirected correspondences between language-tagged texts."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from autolingua2.infrastructure.filesystem import PROJECT_ROOT


TRANSLATION_MEMORY_PATH = PROJECT_ROOT / ".runtime" / "translation_memory.sqlite3"


class TranslationMemoryError(RuntimeError):
    """A correspondence could not be stored; the translation remains intact."""


class TranslationMemoryStore:
    def __init__(self, path: Path = TRANSLATION_MEMORY_PATH) -> None:
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA secure_delete = ON")
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("""CREATE TABLE IF NOT EXISTS correspondences (
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL,
                    a_language TEXT NOT NULL, a_text TEXT NOT NULL,
                    b_language TEXT NOT NULL, b_text TEXT NOT NULL,
                    PRIMARY KEY (adapter_id, game_id, a_language, a_text, b_language, b_text)
                ) WITHOUT ROWID""")
                connection.execute("""CREATE TABLE IF NOT EXISTS correspondence_counts (
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL,
                    source_root TEXT NOT NULL,
                    source_language TEXT NOT NULL, target_language TEXT NOT NULL,
                    a_language TEXT NOT NULL, a_text TEXT NOT NULL,
                    b_language TEXT NOT NULL, b_text TEXT NOT NULL,
                    usage_count INTEGER NOT NULL CHECK (usage_count > 0),
                    PRIMARY KEY (adapter_id, game_id, source_root, source_language, target_language,
                                 a_language, a_text, b_language, b_text),
                    FOREIGN KEY (adapter_id, game_id, a_language, a_text, b_language, b_text)
                        REFERENCES correspondences (adapter_id, game_id, a_language, a_text, b_language, b_text)
                ) WITHOUT ROWID""")
                legacy = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'correspondence_usages'").fetchone()
                if legacy is not None:
                    connection.execute("""INSERT INTO correspondence_counts
                        SELECT adapter_id, game_id, source_root, source_language, target_language,
                               a_language, a_text, b_language, b_text, COUNT(*)
                        FROM correspondence_usages
                        GROUP BY adapter_id, game_id, source_root, source_language, target_language,
                                 a_language, a_text, b_language, b_text""")
                    connection.execute("DROP VIEW IF EXISTS correspondence_usage_counts")
                    connection.execute("DROP TABLE correspondence_usages")
                connection.execute("""CREATE INDEX IF NOT EXISTS usage_correspondence
                    ON correspondence_counts (adapter_id, game_id, a_language, a_text, b_language, b_text)""")
                connection.execute("""CREATE VIEW IF NOT EXISTS correspondence_usage_counts AS
                    SELECT c.*, COALESCE((SELECT SUM(u.usage_count) FROM correspondence_counts u
                        WHERE u.adapter_id = c.adapter_id AND u.game_id = c.game_id
                        AND u.a_language = c.a_language AND u.a_text = c.a_text
                        AND u.b_language = c.b_language AND u.b_text = c.b_text), 0) AS usage_count
                    FROM correspondences c""")
                yield connection
        finally:
            connection.close()

    def record_snapshots(
        self, adapter_id: str, game_id: str, source_root: str,
        source_language: str, snapshots: Mapping[str, Sequence[tuple[str, str]]],
    ) -> None:
        """Replace current counts for complete language workspaces; never store item keys."""
        if not snapshots:
            return
        if not adapter_id or not game_id or not source_root or not source_language or any(not language for language in snapshots):
            raise TranslationMemoryError("翻訳メモリの記録に必要なゲーム・読み込み元・言語の情報がありません。")
        try:
            with self._connection() as connection:
                for target_language, items in snapshots.items():
                    counts: Counter[tuple[str, str, str, str]] = Counter()
                    for source_text, target_text in items:
                        if not source_text.strip() or not target_text.strip():
                            continue
                        first, second = sorted(((source_language, source_text), (target_language, target_text)))
                        counts[(first[0], first[1], second[0], second[1])] += 1
                    scope = (adapter_id, game_id, source_root, source_language, target_language)
                    rows = connection.execute("""SELECT a_language, a_text, b_language, b_text, usage_count
                        FROM correspondence_counts WHERE adapter_id = ? AND game_id = ?
                        AND source_root = ? AND source_language = ? AND target_language = ?""", scope).fetchall()
                    existing = {tuple(row[:4]): row[4] for row in rows}
                    if existing == counts:
                        continue
                    connection.execute("""DELETE FROM correspondence_counts
                        WHERE adapter_id = ? AND game_id = ? AND source_root = ?
                        AND source_language = ? AND target_language = ?""", scope)
                    for pair, count in counts.items():
                        connection.execute("""INSERT INTO correspondences VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT (adapter_id, game_id, a_language, a_text, b_language, b_text) DO NOTHING""",
                            (adapter_id, game_id, *pair))
                        connection.execute("INSERT INTO correspondence_counts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                           (*scope, *pair, count))
        except (OSError, sqlite3.Error) as exc:
            raise TranslationMemoryError(str(exc)) from exc
