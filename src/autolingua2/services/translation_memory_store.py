from __future__ import annotations

import os
from pathlib import Path
import sqlite3

from autolingua2.core.translation_memory import MemoryEntry, structure_signature
from .settings_store import settings_path


MEMORY_ENV_VAR = "AUTOLINGUA_MEMORY_PATH"


def memory_path() -> Path:
    override = os.environ.get(MEMORY_ENV_VAR)
    return Path(override) if override else settings_path().with_name("translation_memory.sqlite3")


class TranslationMemoryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or memory_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                source_language TEXT NOT NULL,
                target_language TEXT NOT NULL,
                provenance TEXT NOT NULL,
                context TEXT NOT NULL DEFAULT '',
                signature TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                use_count INTEGER NOT NULL DEFAULT 0,
                supersedes_id INTEGER REFERENCES entries(id),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS entries_exact ON entries(source_language, target_language, source, active)"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS entries_structure ON entries(source_language, target_language, signature, active)"
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> TranslationMemoryStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def candidates(self, source: str, source_language: str, target_language: str) -> list[MemoryEntry]:
        signature = structure_signature(source)
        rows = self.connection.execute(
            """SELECT id, source, target, source_language, target_language, provenance, context
               FROM entries WHERE active = 1 AND source_language = ? AND target_language = ?
               AND (source = ? OR (signature != '' AND signature = ?))""",
            (source_language, target_language, source, signature),
        ).fetchall()
        return [MemoryEntry(**dict(row)) for row in rows]

    def record(
        self, source: str, target: str, source_language: str, target_language: str,
        provenance: str, context: str = "",
    ) -> int:
        if not source.strip() or not target.strip() or source == target:
            raise ValueError("有効な対訳を指定してください")
        with self.connection:
            previous = self.connection.execute(
                """SELECT id, target, provenance FROM entries WHERE active = 1
                   AND source = ? AND source_language = ? AND target_language = ? AND context = ?
                   ORDER BY id DESC LIMIT 1""",
                (source, source_language, target_language, context),
            ).fetchone()
            if previous and previous["target"] == target and previous["provenance"] == provenance:
                return int(previous["id"])
            if previous:
                self.connection.execute("UPDATE entries SET active = 0 WHERE id = ?", (previous["id"],))
            cursor = self.connection.execute(
                """INSERT INTO entries
                   (source, target, source_language, target_language, provenance, context, signature, supersedes_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (source, target, source_language, target_language, provenance, context,
                 structure_signature(source), previous["id"] if previous else None),
            )
        row_id = cursor.lastrowid
        if row_id is None:
            raise RuntimeError("翻訳メモリの登録IDを取得できませんでした")
        return row_id

    def mark_used(self, entry_id: int) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE entries SET use_count = use_count + 1 WHERE id = ?", (entry_id,)
            )

    def record_imported(
        self, source: str, target: str, source_language: str, target_language: str,
        context: str = "",
    ) -> int | None:
        if not target.strip() or target == source:
            return None
        trusted = self.connection.execute(
            """SELECT id FROM entries WHERE active = 1 AND source = ?
               AND source_language = ? AND target_language = ? AND context = ?
               AND provenance != 'imported_unverified' LIMIT 1""",
            (source, source_language, target_language, context),
        ).fetchone()
        if trusted:
            return None
        return self.record(source, target, source_language, target_language,
                           "imported_unverified", context)
