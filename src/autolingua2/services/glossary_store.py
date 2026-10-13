"""Transactional SQLite storage for independent, shared glossaries."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.ir.glossary import (
    Glossary, GlossaryTerm, PARTS_OF_SPEECH, glossary_chain, resolve_terms,
)


GLOSSARY_PATH = PROJECT_ROOT / ".runtime" / "glossary.sqlite3"


class GlossaryStore:
    def __init__(self, path: Path = GLOSSARY_PATH) -> None:
        self.path = path

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                connection.execute("""CREATE TABLE IF NOT EXISTS glossaries (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    adapter_id TEXT NOT NULL, game_id TEXT NOT NULL,
                    parent_id TEXT REFERENCES glossaries(id))""")
                connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS glossary_root
                    ON glossaries(adapter_id, game_id) WHERE parent_id IS NULL""")
                connection.execute("""CREATE TABLE IF NOT EXISTS glossary_terms (
                    id TEXT PRIMARY KEY, glossary_id TEXT NOT NULL REFERENCES glossaries(id),
                    source_language TEXT NOT NULL, target_language TEXT NOT NULL,
                    part_of_speech TEXT NOT NULL, source TEXT NOT NULL, translation TEXT NOT NULL,
                    variants TEXT NOT NULL, memo TEXT NOT NULL, case_sensitive INTEGER NOT NULL,
                    UNIQUE(glossary_id, source_language, target_language, source))""")
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _glossary(row: sqlite3.Row) -> Glossary:
        return Glossary(row["id"], row["name"], row["adapter_id"], row["game_id"], row["parent_id"])

    def list_glossaries(self, adapter_id: str, game_id: str) -> list[Glossary]:
        with self._connection() as connection:
            return [self._glossary(row) for row in connection.execute(
                "SELECT * FROM glossaries WHERE adapter_id = ? AND game_id = ? ORDER BY name, id",
                (adapter_id, game_id))]

    def ensure_root(self, adapter_id: str, game_id: str, game_name: str) -> Glossary:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM glossaries WHERE adapter_id = ? AND game_id = ? AND parent_id IS NULL",
                (adapter_id, game_id)).fetchone()
            if row is not None:
                return self._glossary(row)
            item = Glossary(str(uuid4()), f"{game_name}共通", adapter_id, game_id, None)
            connection.execute("INSERT INTO glossaries VALUES (?, ?, ?, ?, ?)",
                               (item.id, item.name, adapter_id, game_id, None))
            return item

    def add_glossary(self, parent_id: str, name: str) -> Glossary:
        name = name.strip()
        if not name:
            raise ValueError("用語集の名前を入力してください。")
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM glossaries WHERE id = ?", (parent_id,)).fetchone()
            if row is None:
                raise ValueError("親用語集が見つかりません。")
            parent = self._glossary(row)
            item = Glossary(str(uuid4()), name, parent.adapter_id, parent.game_id, parent.id)
            connection.execute("INSERT INTO glossaries VALUES (?, ?, ?, ?, ?)",
                               (item.id, item.name, item.adapter_id, item.game_id, item.parent_id))
            return item

    def rename_glossary(self, glossary_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("用語集の名前を入力してください。")
        with self._connection() as connection:
            if connection.execute("UPDATE glossaries SET name = ? WHERE id = ?",
                                  (name, glossary_id)).rowcount != 1:
                raise ValueError("用語集が見つかりません。")

    def delete_glossary(self, glossary_id: str) -> None:
        with self._connection() as connection:
            row = connection.execute("SELECT parent_id FROM glossaries WHERE id = ?",
                                     (glossary_id,)).fetchone()
            if row is None:
                raise ValueError("用語集が見つかりません。")
            if row["parent_id"] is None:
                raise ValueError("ゲームの共通用語集は削除できません。")
            if connection.execute("SELECT 1 FROM glossaries WHERE parent_id = ?",
                                  (glossary_id,)).fetchone() is not None:
                raise ValueError("子用語集がある用語集は削除できません。")
            connection.execute("DELETE FROM glossary_terms WHERE glossary_id = ?", (glossary_id,))
            connection.execute("DELETE FROM glossaries WHERE id = ?", (glossary_id,))

    def list_terms(self, glossary_id: str) -> list[GlossaryTerm]:
        with self._connection() as connection:
            result: list[GlossaryTerm] = []
            for row in connection.execute("SELECT * FROM glossary_terms WHERE glossary_id = ? ORDER BY id", (glossary_id,)):
                variants = json.loads(row["variants"])
                if not isinstance(variants, list) or any(not isinstance(value, str) for value in variants):
                    raise ValueError("用語の他形態データが不正です。")
                result.append(GlossaryTerm(row["id"], row["glossary_id"], row["source_language"],
                    row["target_language"], row["part_of_speech"], row["source"], row["translation"],
                    tuple(variants), row["memo"], bool(row["case_sensitive"])))
            return result

    def restore_glossary(self, glossary: Glossary, terms: list[GlossaryTerm]) -> None:
        """Restore an operation's deleted leaf and its terms in one transaction."""
        with self._connection() as connection:
            connection.execute("INSERT INTO glossaries VALUES (?, ?, ?, ?, ?)",
                (glossary.id, glossary.name, glossary.adapter_id, glossary.game_id, glossary.parent_id))
            for term in terms:
                connection.execute("INSERT INTO glossary_terms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (term.id, term.glossary_id, term.source_language, term.target_language, term.part_of_speech,
                     term.source, term.translation, json.dumps(term.variants, ensure_ascii=False),
                     term.memo, int(term.case_sensitive)))

    def effective_terms(self, glossaries: list[Glossary], glossary_id: str,
                        source_language: str, target_language: str) -> list[GlossaryTerm]:
        chain = glossary_chain(glossaries, glossary_id)
        terms: list[GlossaryTerm] = []
        with self._connection() as connection:
            for glossary in chain:
                for row in connection.execute(
                    "SELECT * FROM glossary_terms WHERE glossary_id = ? AND source_language = ? AND target_language = ?",
                    (glossary.id, source_language, target_language)):
                    variants = json.loads(row["variants"])
                    if not isinstance(variants, list) or any(not isinstance(v, str) for v in variants):
                        raise ValueError("用語の他形態データが不正です。")
                    terms.append(GlossaryTerm(
                        row["id"], row["glossary_id"], row["source_language"], row["target_language"],
                        row["part_of_speech"], row["source"], row["translation"],
                        tuple(variants), row["memo"], bool(row["case_sensitive"])))
        return resolve_terms(chain, terms, source_language, target_language)

    @staticmethod
    def _normalize_term(term: GlossaryTerm) -> GlossaryTerm:
        source, translation = term.source.strip(), term.translation.strip()
        if not source or not translation:
            raise ValueError("原語と指定訳を入力してください。")
        if not term.source_language or not term.target_language:
            raise ValueError("原語と訳語の言語を選択してください。")
        if term.part_of_speech not in PARTS_OF_SPEECH:
            raise ValueError("品詞を選択してください。")
        variants = tuple(dict.fromkeys(v.strip() for v in term.variants if v.strip()))
        return replace(term, id=term.id or str(uuid4()), source=source,
                       translation=translation, variants=variants)

    @staticmethod
    def _write_term(connection: sqlite3.Connection, saved: GlossaryTerm) -> None:
        connection.execute("""INSERT INTO glossary_terms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET part_of_speech = excluded.part_of_speech,
            source = excluded.source, translation = excluded.translation,
            variants = excluded.variants, memo = excluded.memo, case_sensitive = excluded.case_sensitive""",
            (saved.id, saved.glossary_id, saved.source_language, saved.target_language,
             saved.part_of_speech, saved.source, saved.translation,
             json.dumps(saved.variants, ensure_ascii=False), saved.memo, int(saved.case_sensitive)))

    def save_term(self, term: GlossaryTerm) -> GlossaryTerm:
        saved = self._normalize_term(term)
        with self._connection() as connection:
            existing = connection.execute("SELECT glossary_id FROM glossary_terms WHERE id = ?",
                                          (saved.id,)).fetchone()
            if existing is not None and existing["glossary_id"] != saved.glossary_id:
                raise ValueError("別の用語集の用語を変更できません。")
            try:
                self._write_term(connection, saved)
            except sqlite3.IntegrityError as exc:
                raise ValueError("同じ原語の用語が登録済みか、保存先の用語集が存在しません。") from exc
        return saved

    def import_paratranz_terms(self, path: Path, glossary_id: str,
                              source_language: str, target_language: str) -> tuple[int, int]:
        """Validate every entry before atomically importing into the selected glossary."""
        if not source_language or not target_language:
            raise ValueError("原語と訳語の言語を選択してください。")
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONの形式が不正です（{exc.lineno}行、{exc.colno}列）。") from exc
        if not isinstance(data, list):
            raise ValueError("ParaTranz用語集はJSON配列で指定してください。")
        parts = {"noun": "名詞", "verb": "動詞", "adjective": "形容詞",
                 "adverb": "副詞", "pronoun": "代名詞"}
        terms: list[GlossaryTerm] = []
        sources: set[str] = set()
        for index, entry in enumerate(data, 1):
            try:
                if not isinstance(entry, dict):
                    raise ValueError("用語はJSONオブジェクトで指定してください。")
                source, translation = entry.get("term"), entry.get("translation")
                variants, memo = entry.get("variants", []), entry.get("note", "")
                pos = entry.get("pos", "")
                if not isinstance(source, str) or not isinstance(translation, str):
                    raise ValueError("termとtranslationは文字列で指定してください。")
                if not isinstance(variants, list) or any(not isinstance(v, str) for v in variants):
                    raise ValueError("variantsは文字列の配列で指定してください。")
                if not isinstance(memo, str):
                    raise ValueError("noteは文字列で指定してください。")
                if not isinstance(pos, str):
                    raise ValueError("posは文字列で指定してください。")
                term = self._normalize_term(GlossaryTerm(
                    "", glossary_id, source_language, target_language,
                    parts.get(pos, "その他"), source, translation, tuple(variants), memo))
                if term.source in sources:
                    raise ValueError(f"ファイル内で原語が重複しています：{term.source}")
                sources.add(term.source)
                terms.append(term)
            except ValueError as exc:
                raise ValueError(f"用語{index}件目：{exc}") from exc
        added = updated = 0
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM glossaries WHERE id = ?", (glossary_id,)).fetchone() is None:
                raise ValueError("保存先の用語集が存在しません。")
            for term in terms:
                existing = connection.execute(
                    """SELECT id FROM glossary_terms WHERE glossary_id = ?
                    AND source_language = ? AND target_language = ? AND source = ?""",
                    (glossary_id, source_language, target_language, term.source)).fetchone()
                if existing is None:
                    added += 1
                else:
                    term = replace(term, id=existing["id"])
                    updated += 1
                self._write_term(connection, term)
        return added, updated

    def delete_term(self, glossary_id: str, term_id: str) -> None:
        with self._connection() as connection:
            if connection.execute("DELETE FROM glossary_terms WHERE id = ? AND glossary_id = ?",
                                  (term_id, glossary_id)).rowcount != 1:
                raise ValueError("この用語集で追加・上書きした用語を選択してください。")
