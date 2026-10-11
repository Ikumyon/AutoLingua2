"""Game/project text correspondences, tone snapshots, and current usage counts."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ir.project import TranslationProject
from autolingua2.ir.tone import ToneItem


TRANSLATION_MEMORY_PATH = PROJECT_ROOT / ".runtime" / "translation_memory.sqlite3"
TranslationPair = tuple[str, str, ToneItem | None]


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
                connection.execute("""CREATE TABLE IF NOT EXISTS translation_projects (
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    name TEXT NOT NULL, source_root TEXT NOT NULL,
                    PRIMARY KEY (adapter_id, game_id, project_id)
                ) WITHOUT ROWID""")
                connection.execute("""CREATE TABLE IF NOT EXISTS project_correspondences (
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    a_language TEXT NOT NULL, a_text TEXT NOT NULL,
                    b_language TEXT NOT NULL, b_text TEXT NOT NULL,
                    PRIMARY KEY (adapter_id, game_id, project_id, a_language, a_text, b_language, b_text),
                    FOREIGN KEY (adapter_id, game_id, project_id)
                        REFERENCES translation_projects (adapter_id, game_id, project_id),
                    FOREIGN KEY (adapter_id, game_id, a_language, a_text, b_language, b_text)
                        REFERENCES correspondences (adapter_id, game_id, a_language, a_text, b_language, b_text)
                ) WITHOUT ROWID""")
                connection.execute("""CREATE TABLE IF NOT EXISTS project_tones (
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    a_language TEXT NOT NULL, a_text TEXT NOT NULL,
                    b_language TEXT NOT NULL, b_text TEXT NOT NULL,
                    target_language TEXT NOT NULL, target_text TEXT NOT NULL,
                    tone_id TEXT NOT NULL, tone_name TEXT NOT NULL, tone_prompt TEXT NOT NULL,
                    PRIMARY KEY (adapter_id, game_id, project_id, a_language, a_text, b_language, b_text,
                                 target_language, target_text, tone_id, tone_name, tone_prompt),
                    FOREIGN KEY (adapter_id, game_id, project_id, a_language, a_text, b_language, b_text)
                        REFERENCES project_correspondences (adapter_id, game_id, project_id,
                                                          a_language, a_text, b_language, b_text)
                ) WITHOUT ROWID""")
                connection.execute("""CREATE TABLE IF NOT EXISTS project_usage_counts (
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL, project_id TEXT NOT NULL,
                    source_language TEXT NOT NULL, target_language TEXT NOT NULL,
                    a_language TEXT NOT NULL, a_text TEXT NOT NULL,
                    b_language TEXT NOT NULL, b_text TEXT NOT NULL,
                    tone_text TEXT NOT NULL, tone_id TEXT NOT NULL, tone_name TEXT NOT NULL, tone_prompt TEXT NOT NULL,
                    usage_count INTEGER NOT NULL CHECK (usage_count > 0),
                    PRIMARY KEY (adapter_id, game_id, project_id, source_language, target_language,
                                 a_language, a_text, b_language, b_text, tone_text, tone_id, tone_name, tone_prompt),
                    FOREIGN KEY (adapter_id, game_id, project_id, a_language, a_text, b_language, b_text)
                        REFERENCES project_correspondences (adapter_id, game_id, project_id,
                                                          a_language, a_text, b_language, b_text)
                ) WITHOUT ROWID""")
                self._migrate_counts(connection)
                connection.execute("""CREATE INDEX IF NOT EXISTS project_usage_correspondence
                    ON project_usage_counts (adapter_id, game_id, a_language, a_text, b_language, b_text)""")
                connection.execute("""CREATE VIEW IF NOT EXISTS correspondence_usage_counts AS
                    SELECT c.*, COALESCE((SELECT SUM(u.usage_count) FROM project_usage_counts u
                        WHERE u.adapter_id = c.adapter_id AND u.game_id = c.game_id
                        AND u.a_language = c.a_language AND u.a_text = c.a_text
                        AND u.b_language = c.b_language AND u.b_text = c.b_text), 0) AS usage_count
                    FROM correspondences c""")
                connection.execute("""CREATE VIEW IF NOT EXISTS project_correspondence_usage_counts AS
                    SELECT c.*, COALESCE((SELECT SUM(u.usage_count) FROM project_usage_counts u
                        WHERE u.adapter_id = c.adapter_id AND u.game_id = c.game_id AND u.project_id = c.project_id
                        AND u.a_language = c.a_language AND u.a_text = c.a_text
                        AND u.b_language = c.b_language AND u.b_text = c.b_text), 0) AS usage_count
                    FROM project_correspondences c""")
                yield connection
        finally:
            connection.close()

    def _migrate_counts(self, connection: sqlite3.Connection) -> None:
        for table in ("correspondence_usages", "correspondence_counts"):
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()
            if exists is None:
                continue
            count = "COUNT(*)" if table == "correspondence_usages" else "SUM(usage_count)"
            rows = connection.execute(f"""SELECT adapter_id, game_id, source_root, source_language, target_language,
                        a_language, a_text, b_language, b_text, {count}
                    FROM {table} GROUP BY adapter_id, game_id, source_root, source_language, target_language,
                                         a_language, a_text, b_language, b_text""").fetchall()
            for adapter, game, root, source, target, a_lang, a_text, b_lang, b_text, uses in rows:
                identity = json.dumps([adapter, game, root], ensure_ascii=False)
                project_id = "legacy:" + uuid5(NAMESPACE_URL, identity).hex
                connection.execute("INSERT OR IGNORE INTO translation_projects VALUES (?, ?, ?, ?, ?)",
                                   (adapter, game, project_id, Path(root).name, root))
                pair = (adapter, game, project_id, a_lang, a_text, b_lang, b_text)
                connection.execute("INSERT OR IGNORE INTO project_correspondences VALUES (?, ?, ?, ?, ?, ?, ?)", pair)
                connection.execute("INSERT INTO project_usage_counts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (adapter, game, project_id, source, target, a_lang, a_text, b_lang, b_text,
                                    "", "", "", "", uses))
            connection.execute("DROP VIEW IF EXISTS correspondence_usage_counts")
            connection.execute(f"DROP TABLE {table}")

    def _register_project(self, connection: sqlite3.Connection, project: TranslationProject) -> None:
        scope = (project.adapter_id, project.game_id, project.memory_id)
        connection.execute("""INSERT INTO translation_projects VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (adapter_id, game_id, project_id)
            DO UPDATE SET name = excluded.name, source_root = excluded.source_root""",
            (*scope, project.name, project.source_root))
        # Attach old root-only counts once; later projects using the same root stay independent.
        old = connection.execute("""SELECT project_id FROM translation_projects
            WHERE adapter_id = ? AND game_id = ? AND source_root = ? AND project_id LIKE 'legacy:%'""",
            (project.adapter_id, project.game_id, project.source_root)).fetchall()
        fields = "a_language, a_text, b_language, b_text"
        for row in old:
            previous = (project.adapter_id, project.game_id, row[0])
            for table, columns in (
                ("project_correspondences", fields),
                ("project_tones", fields + ", target_language, target_text, tone_id, tone_name, tone_prompt"),
                ("project_usage_counts", "source_language, target_language, " + fields
                    + ", tone_text, tone_id, tone_name, tone_prompt, usage_count"),
            ):
                connection.execute(f"""INSERT OR IGNORE INTO {table}
                    SELECT adapter_id, game_id, ?, {columns} FROM {table}
                    WHERE adapter_id = ? AND game_id = ? AND project_id = ?""", (project.memory_id, *previous))
            for table in ("project_usage_counts", "project_tones", "project_correspondences", "translation_projects"):
                connection.execute(f"DELETE FROM {table} WHERE adapter_id = ? AND game_id = ? AND project_id = ?", previous)

    def record_snapshots(self, project: TranslationProject,
                         snapshots: Mapping[str, Sequence[TranslationPair]]) -> None:
        """Replace current project/workspace counts without storing keys or translation states."""
        if not snapshots:
            return
        if (not project.adapter_id or not project.game_id or not project.memory_id or not project.source_root
                or not project.source_language or any(not language for language in snapshots)):
            raise TranslationMemoryError("翻訳メモリの記録に必要なゲーム・プロジェクト・言語の情報がありません。")
        try:
            with self._connection() as connection:
                self._register_project(connection, project)
                for target_language, items in snapshots.items():
                    counts: Counter[tuple[str, str, str, str, str, str, str, str]] = Counter()
                    for source_text, target_text, tone in items:
                        if not source_text.strip() or not target_text.strip():
                            continue
                        if tone is not None and (not tone.id or not tone.name.strip() or not tone.prompt.strip()):
                            raise TranslationMemoryError("記録する口調の名前・説明がありません。")
                        first, second = sorted(((project.source_language, source_text), (target_language, target_text)))
                        pair = (first[0], first[1], second[0], second[1])
                        tone_attributes: tuple[str, str, str, str] = (
                            (target_text, tone.id, tone.name, tone.prompt) if tone is not None else ("", "", "", ""))
                        counts[(pair[0], pair[1], pair[2], pair[3], tone_attributes[0],
                                tone_attributes[1], tone_attributes[2], tone_attributes[3])] += 1
                    scope = (project.adapter_id, project.game_id, project.memory_id, project.source_language, target_language)
                    rows = connection.execute("""SELECT a_language, a_text, b_language, b_text,
                        tone_text, tone_id, tone_name, tone_prompt, usage_count FROM project_usage_counts
                        WHERE adapter_id = ? AND game_id = ? AND project_id = ?
                        AND source_language = ? AND target_language = ?""", scope).fetchall()
                    if {tuple(row[:8]): row[8] for row in rows} == counts:
                        continue
                    connection.execute("""DELETE FROM project_usage_counts WHERE adapter_id = ? AND game_id = ?
                        AND project_id = ? AND source_language = ? AND target_language = ?""", scope)
                    for attributes, count in counts.items():
                        pair = attributes[:4]
                        game_pair = (project.adapter_id, project.game_id, *pair)
                        project_pair = (project.adapter_id, project.game_id, project.memory_id, *pair)
                        connection.execute("INSERT OR IGNORE INTO correspondences VALUES (?, ?, ?, ?, ?, ?)", game_pair)
                        connection.execute("INSERT OR IGNORE INTO project_correspondences VALUES (?, ?, ?, ?, ?, ?, ?)", project_pair)
                        tone_text, tone_id, tone_name, tone_prompt = attributes[4:]
                        if tone_id:
                            connection.execute("INSERT OR IGNORE INTO project_tones VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                               (*project_pair, target_language, tone_text, tone_id, tone_name, tone_prompt))
                        connection.execute("INSERT INTO project_usage_counts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                           (*scope, *attributes, count))
        except (OSError, sqlite3.Error) as exc:
            raise TranslationMemoryError(str(exc)) from exc
