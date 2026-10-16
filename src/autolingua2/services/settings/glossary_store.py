"""Persistence of directionless bilingual records and inherited root languages."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from autolingua2.infrastructure.filesystem import LIBRARY_DIR
from autolingua2.ir.glossary import (
    DirectedTerm, Glossary, GlossaryTerm, TermSide, PARTS_OF_SPEECH,
    glossary_chain, orient_term, resolve_terms,
)
from .glossary_io import GlossaryDocument, ImportMode, ImportResult, document_data, parse_document

GLOSSARY_PATH = LIBRARY_DIR / "glossary.sqlite3"


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
                columns = {row[1] for row in connection.execute("PRAGMA table_info(glossaries)")}
                if columns and "language_a" not in columns:
                    raise ValueError("旧形式の用語集DBです。glossary.sqlite3を削除して作り直してください。")
                connection.execute("""CREATE TABLE IF NOT EXISTS glossaries (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, adapter_id TEXT NOT NULL,
                    game_id TEXT NOT NULL, parent_id TEXT REFERENCES glossaries(id),
                    language_a TEXT, language_b TEXT,
                    CHECK ((language_a IS NULL AND language_b IS NULL) OR
                        (parent_id IS NULL AND language_a IS NOT NULL AND language_b IS NOT NULL
                         AND language_a <> language_b)))""")
                connection.execute("""CREATE UNIQUE INDEX IF NOT EXISTS glossary_root
                    ON glossaries(adapter_id, game_id) WHERE parent_id IS NULL""")
                connection.execute("""CREATE TABLE IF NOT EXISTS glossary_terms (
                    id TEXT PRIMARY KEY, glossary_id TEXT NOT NULL REFERENCES glossaries(id),
                    entry_key TEXT NOT NULL, part_of_speech TEXT NOT NULL,
                    text_a TEXT NOT NULL, variants_a TEXT NOT NULL, sensitive_a INTEGER NOT NULL,
                    text_b TEXT NOT NULL, variants_b TEXT NOT NULL, sensitive_b INTEGER NOT NULL,
                    memo TEXT NOT NULL, UNIQUE(glossary_id, entry_key),
                    UNIQUE(glossary_id, text_a), UNIQUE(glossary_id, text_b))""")
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _glossary(row: sqlite3.Row) -> Glossary:
        languages = None if row["language_a"] is None else (str(row["language_a"]), str(row["language_b"]))
        return Glossary(row["id"], row["name"], row["adapter_id"], row["game_id"], row["parent_id"], languages)

    @staticmethod
    def _insert(connection: sqlite3.Connection, item: Glossary) -> None:
        a, b = item.languages if item.languages is not None else (None, None)
        connection.execute("INSERT INTO glossaries VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.id, item.name, item.adapter_id, item.game_id, item.parent_id, a, b))

    def list_glossaries(self, adapter_id: str, game_id: str) -> list[Glossary]:
        with self._connection() as connection:
            return [self._glossary(row) for row in connection.execute(
                "SELECT * FROM glossaries WHERE adapter_id = ? AND game_id = ? ORDER BY name, id", (adapter_id, game_id))]

    @staticmethod
    def _chain(connection: sqlite3.Connection, glossary_id: str) -> list[Glossary]:
        row = connection.execute("SELECT * FROM glossaries WHERE id = ?", (glossary_id,)).fetchone()
        if row is None:
            raise ValueError("用語集が見つかりません。")
        items = [GlossaryStore._glossary(r) for r in connection.execute(
            "SELECT * FROM glossaries WHERE adapter_id = ? AND game_id = ?", (row["adapter_id"], row["game_id"]))]
        return glossary_chain(items, glossary_id)

    def ensure_root(self, adapter_id: str, game_id: str, game_name: str) -> Glossary:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM glossaries WHERE adapter_id = ? AND game_id = ? AND parent_id IS NULL",
                                     (adapter_id, game_id)).fetchone()
            if row is not None:
                return self._glossary(row)
            item = Glossary(str(uuid4()), f"{game_name}共通", adapter_id, game_id, None)
            self._insert(connection, item)
            return item

    def set_root_languages(self, glossary_id: str, a: str, b: str) -> None:
        if not a or not b or a == b:
            raise ValueError("異なる2言語を選択してください。")
        with self._connection() as connection:
            chain = self._chain(connection, glossary_id)
            if len(chain) != 1:
                raise ValueError("言語は最上位の親で設定してください。")
            root = chain[0]
            if root.languages == (a, b):
                return
            if connection.execute("""SELECT 1 FROM glossary_terms t JOIN glossaries g ON g.id = t.glossary_id
                    WHERE g.adapter_id = ? AND g.game_id = ? LIMIT 1""", (root.adapter_id, root.game_id)).fetchone() is not None:
                raise ValueError("用語があるため言語の組は変更できません。表示の入れ替えを使用してください。")
            connection.execute("UPDATE glossaries SET language_a = ?, language_b = ? WHERE id = ?", (a, b, root.id))

    def add_glossary(self, parent_id: str, name: str) -> Glossary:
        if not name.strip():
            raise ValueError("用語集の名前を入力してください。")
        with self._connection() as connection:
            parent = self._chain(connection, parent_id)[-1]
            item = Glossary(str(uuid4()), name.strip(), parent.adapter_id, parent.game_id, parent.id)
            self._insert(connection, item)
            return item

    def rename_glossary(self, glossary_id: str, name: str) -> None:
        if not name.strip():
            raise ValueError("用語集の名前を入力してください。")
        with self._connection() as connection:
            if connection.execute("UPDATE glossaries SET name = ? WHERE id = ?", (name.strip(), glossary_id)).rowcount != 1:
                raise ValueError("用語集が見つかりません。")

    def delete_glossary(self, glossary_id: str) -> None:
        with self._connection() as connection:
            if len(self._chain(connection, glossary_id)) == 1:
                raise ValueError("ゲームの共通用語集は削除できません。")
            if connection.execute("SELECT 1 FROM glossaries WHERE parent_id = ?", (glossary_id,)).fetchone() is not None:
                raise ValueError("子用語集がある用語集は削除できません。")
            connection.execute("DELETE FROM glossary_terms WHERE glossary_id = ?", (glossary_id,))
            connection.execute("DELETE FROM glossaries WHERE id = ?", (glossary_id,))

    @staticmethod
    def _terms(connection: sqlite3.Connection, glossary_id: str) -> list[GlossaryTerm]:
        def side(row: sqlite3.Row, suffix: str) -> TermSide:
            values = json.loads(row[f"variants_{suffix}"])
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise ValueError("他形態データが不正です。")
            return TermSide(row[f"text_{suffix}"], tuple(values), bool(row[f"sensitive_{suffix}"]))
        return [GlossaryTerm(r["id"], r["glossary_id"], r["part_of_speech"], side(r, "a"), side(r, "b"), r["memo"], r["entry_key"])
                for r in connection.execute("SELECT * FROM glossary_terms WHERE glossary_id = ? ORDER BY id", (glossary_id,))]

    def list_terms(self, glossary_id: str) -> list[GlossaryTerm]:
        with self._connection() as connection:
            return self._terms(connection, glossary_id)

    def restore_glossary(self, glossary: Glossary, terms: list[GlossaryTerm]) -> None:
        with self._connection() as connection:
            self._insert(connection, glossary)
            for term in terms:
                self._write_term(connection, term)

    def effective_terms(self, glossaries: list[Glossary], glossary_id: str,
                        source_language: str, target_language: str) -> list[DirectedTerm]:
        chain = glossary_chain(glossaries, glossary_id)
        languages = chain[0].languages
        if languages is None or source_language == target_language or set(languages) != {source_language, target_language}:
            return []
        with self._connection() as connection:
            terms = resolve_terms(chain, [t for g in chain for t in self._terms(connection, g.id)])
        return sorted((orient_term(t, languages, source_language) for t in terms), key=lambda t: (t.source.casefold(), t.source))

    @staticmethod
    def _write_term(connection: sqlite3.Connection, term: GlossaryTerm) -> None:
        connection.execute("""INSERT INTO glossary_terms VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET entry_key = excluded.entry_key, part_of_speech = excluded.part_of_speech,
            text_a = excluded.text_a, variants_a = excluded.variants_a, sensitive_a = excluded.sensitive_a,
            text_b = excluded.text_b, variants_b = excluded.variants_b, sensitive_b = excluded.sensitive_b,
            memo = excluded.memo""", (term.id, term.glossary_id, term.key, term.part_of_speech,
            term.a.text, json.dumps(term.a.variants, ensure_ascii=False), int(term.a.case_sensitive),
            term.b.text, json.dumps(term.b.variants, ensure_ascii=False), int(term.b.case_sensitive), term.memo))

    @staticmethod
    def _save(connection: sqlite3.Connection, term: GlossaryTerm) -> GlossaryTerm:
        if not term.a.text.strip() or not term.b.text.strip():
            raise ValueError("両言語の表現を入力してください。")
        if term.part_of_speech not in PARTS_OF_SPEECH:
            raise ValueError("品詞を選択してください。")
        def normalize(side: TermSide) -> TermSide:
            return replace(side, text=side.text.strip(), variants=tuple(dict.fromkeys(v.strip() for v in side.variants if v.strip())))
        saved = replace(term, id=term.id or str(uuid4()), a=normalize(term.a), b=normalize(term.b))
        chain = GlossaryStore._chain(connection, saved.glossary_id)
        if chain[0].languages is None:
            raise ValueError("最上位の親で2言語を設定してください。")
        old = connection.execute("SELECT glossary_id FROM glossary_terms WHERE id = ?", (saved.id,)).fetchone()
        if old is not None and old["glossary_id"] != saved.glossary_id:
            raise ValueError("別の用語集の用語を変更できません。")
        effective = resolve_terms(chain, [t for g in chain for t in GlossaryStore._terms(connection, g.id)])
        if not saved.key:
            matches = {t.key for t in effective if t.a.text == saved.a.text or t.b.text == saved.b.text}
            if len(matches) > 1:
                raise ValueError("両言語の表現が別々の用語と重複しています。")
            saved = replace(saved, key=next(iter(matches)) if matches else str(uuid4()))
        if any(t.key != saved.key and (t.a.text == saved.a.text or t.b.text == saved.b.text) for t in effective):
            raise ValueError("いずれかの言語の表現が別の用語と重複しています。")
        GlossaryStore._write_term(connection, saved)
        return saved

    def save_term(self, term: GlossaryTerm) -> GlossaryTerm:
        with self._connection() as connection:
            return self._save(connection, term)

    def import_document(self, document: GlossaryDocument, glossary_id: str, mode: ImportMode,
                        *, combine: bool = False) -> ImportResult:
        document = parse_document(document_data(document))
        if mode == ImportMode.MERGE and len(document.glossaries) != 1:
            raise ValueError("継承付き用語集は配下に新規作成してください。")
        added = updated = created = 0
        with self._connection() as connection:
            chain = self._chain(connection, glossary_id)
            destination, root = chain[-1], chain[0]
            incoming = document.glossaries[0].languages
            if incoming is None:
                raise ValueError("ファイルの2言語が未設定です。")
            languages = root.languages
            if languages is None:
                connection.execute("UPDATE glossaries SET language_a = ?, language_b = ? WHERE id = ?", (*incoming, root.id))
                languages = incoming
            if set(languages) != set(incoming):
                raise ValueError("取り込み先とファイルの2言語が一致しません。")
            ids: dict[str, str] = {}
            keys: dict[str, str] = {}
            for glossary in document.glossaries:
                if mode == ImportMode.MERGE:
                    ids[glossary.id] = glossary_id
                else:
                    ids[glossary.id] = str(uuid4())
                    parent = glossary_id if glossary.parent_id is None else ids[glossary.parent_id]
                    self._insert(connection, Glossary(ids[glossary.id], glossary.name, destination.adapter_id, destination.game_id, parent))
                    created += 1
                for original in (t for t in document.terms if t.glossary_id == glossary.id):
                    a, b = (original.a, original.b) if languages == incoming else (original.b, original.a)
                    local = self._terms(connection, ids[glossary.id])
                    if combine and mode == ImportMode.MERGE:
                        ancestors = self._chain(connection, ids[glossary.id])
                        effective = resolve_terms(ancestors, [t for g in ancestors for t in self._terms(connection, g.id)])
                        existing = [t for t in effective if self._overlap(t.a, a) or self._overlap(t.b, b)]
                    else:
                        existing = [t for t in local if t.a.text == a.text or t.b.text == b.text]
                    if len(existing) > 1:
                        raise ValueError("取り込み先の複数用語と表現が重複しています。")
                    if existing:
                        keys[original.key] = existing[0].key
                        if existing[0].glossary_id == ids[glossary.id]:
                            updated += 1
                        else:
                            added += 1
                    else:
                        added += 1
                    memo = original.memo
                    if existing and combine and mode == ImportMode.MERGE:
                        previous = existing[0]
                        if previous.part_of_speech != original.part_of_speech:
                            raise ValueError("既存用語と取り込む用語の品詞が一致しません。")
                        a, b = self._combine_side(previous.a, a), self._combine_side(previous.b, b)
                        memo = "\n\n".join(dict.fromkeys(p for p in
                            (*previous.memo.split("\n\n"), *memo.split("\n\n")) if p))
                    record_id = existing[0].id if existing and existing[0].glossary_id == ids[glossary.id] else ""
                    saved = self._save(connection, replace(original, id=record_id,
                        glossary_id=ids[glossary.id], a=a, b=b, memo=memo, key=keys.get(original.key, "")))
                    keys[original.key] = saved.key
        return ImportResult(created, added, updated, ids[document.glossaries[0].id])

    @staticmethod
    def _overlap(a: TermSide, b: TermSide) -> bool:
        return bool({a.text, *a.variants} & {b.text, *b.variants})

    @staticmethod
    def _combine_side(previous: TermSide, incoming: TermSide) -> TermSide:
        variants = tuple(dict.fromkeys(v for v in (*previous.variants, incoming.text, *incoming.variants)
                                      if v != previous.text))
        return replace(previous, variants=variants)

    def delete_term(self, glossary_id: str, term_id: str) -> None:
        with self._connection() as connection:
            if connection.execute("DELETE FROM glossary_terms WHERE id = ? AND glossary_id = ?", (term_id, glossary_id)).rowcount != 1:
                raise ValueError("この用語集で追加・上書きした用語を選択してください。")
