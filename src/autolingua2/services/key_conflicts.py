"""Resolve parser-declared key conflicts before importing either side."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

from autolingua2.adapters.base import FileAdapter, KeyConflictAdapter
from autolingua2.infrastructure.operations import OperationCancelled, check_cancelled, report_progress
from autolingua2.ir.key_conflict import KeyCandidate, KeyConflict, KeyConflictSide, KeyFile


ConflictConfirmation = Callable[[KeyConflict], tuple[int, ...] | None]


def resolve_key_conflicts(
    adapter: FileAdapter, source_files: list[Path], translation_files: list[Path],
    confirm: ConflictConfirmation | None,
) -> None:
    if not isinstance(adapter, KeyConflictAdapter):
        return
    completed = 0
    while True:
        check_cancelled()
        snapshots: dict[Path, KeyFile] = {}
        grouped: dict[str, dict[tuple[str, str], list[KeyCandidate]]] = {}
        for role, files in (("source", source_files), ("translation", translation_files)):
            for path in files:
                check_cancelled()
                snapshot = snapshots.get(path)
                if snapshot is None:
                    snapshot = adapter.inspect_key_file(path)
                    snapshots[path] = snapshot
                for entry in snapshot.entries:
                    grouped.setdefault(entry.key, {}).setdefault((role, entry.language_code), []).append(
                        KeyCandidate(snapshot, entry))
        conflicts = [key for key, sides in grouped.items() if any(len(items) > 1 for items in sides.values())]
        if not conflicts:
            return
        key = conflicts[0]
        sides = tuple(KeyConflictSide("source" if role == "source" else "translation", language, tuple(items))
                      for (role, language), items in grouped[key].items())
        conflict = KeyConflict(key, completed + 1, completed + len(conflicts), sides)
        if confirm is None:
            raise ValueError(f"同じ言語のキーが競合しています: {key}")
        selected = confirm(conflict)
        if selected is None:
            raise OperationCancelled("読み込みを中止しました。確定済みのファイル修正は保持されます。")
        check_cancelled()
        if len(selected) != len(sides):
            raise ValueError("採用する候補が指定されていません。")
        deletions: dict[Path, set[int]] = {}
        retained: set[tuple[Path, int]] = set()
        for side, index in zip(sides, selected, strict=True):
            if not 0 <= index < len(side.candidates):
                raise ValueError("採用する候補が見つかりません。")
            chosen = side.candidates[index]
            retained.add((chosen.file.path, chosen.entry.line_number))
            for other_index, candidate in enumerate(side.candidates):
                if other_index != index:
                    deletions.setdefault(candidate.file.path, set()).add(candidate.entry.line_number)
        if any((path, line) in retained for path, lines in deletions.items() for line in lines):
            raise ValueError("同じファイルの採用行と削除行が一致しています。選択を確認してください。")
        # Include kept files in the check: an external edit can introduce another duplicate.
        if any(path.read_bytes() != snapshot.content for path, snapshot in snapshots.items()):
            report_progress("確認中に元ファイルが変更されました。再読み込みして選び直してください。")
            continue
        replacements = {path: adapter.remove_key_lines(snapshots[path], lines)
                        for path, lines in deletions.items()}
        written: list[Path] = []
        try:
            for path, content in replacements.items():
                if path.read_bytes() != snapshots[path].content:
                    raise OSError(f"書き込み直前に元ファイルが変更されました: {path}")
                output = QSaveFile(str(path))
                if not output.open(QIODevice.OpenModeFlag.WriteOnly):
                    raise OSError(output.errorString())
                if output.write(content) != len(content):
                    error = output.errorString()
                    output.cancelWriting()
                    raise OSError(error)
                if not output.commit():
                    raise OSError(output.errorString())
                written.append(path)
        except OSError as exc:
            done = "\n".join(map(str, written)) or "なし"
            pending = "\n".join(str(path) for path in replacements if path not in written) or "なし"
            raise OSError(f"元ファイルの修正に失敗しました: {exc}\n修正済み:\n{done}\n未修正:\n{pending}") from exc
        completed += 1
        report_progress(f"キー {key} の競合を修正しました。再読み込みしています…")
