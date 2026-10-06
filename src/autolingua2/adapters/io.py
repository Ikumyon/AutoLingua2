from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import threading

from PySide6.QtCore import QRunnable, QThreadPool

from autolingua2.ir import TranslationProject
from autolingua2.ir.imported import ImportedTranslation, SourceRef
from .base import FileAdapter



def supported_file_filter(adapter: FileAdapter) -> str:
    suffixes = sorted(f"*{suffix}" for suffix in adapter.suffixes)
    return f"Supported Text ({' '.join(suffixes)});;All Files (*)"


def load_file(path: Path, adapter: FileAdapter) -> ImportedTranslation:
    if not adapter.can_load(path):
        raise ValueError(f"対応していないファイルです: {path}")
    imported = adapter.load(path)
    imported.project.adapter_id = adapter.id
    return imported


def load_folder(path: Path, adapter: FileAdapter) -> ImportedTranslation:
    return load_paths([path], adapter)


class _FileLoadRunnable(QRunnable):
    def __init__(
        self,
        index: int,
        path: Path,
        adapter: FileAdapter,
        results: list[ImportedTranslation | None],
        lock: threading.Lock,
        error_holder: list[Exception],
        on_done: Callable[[], None],
    ) -> None:
        super().__init__()
        self.index = index
        self.path = path
        self.adapter = adapter
        self.results = results
        self.lock = lock
        self.error_holder = error_holder
        self.on_done = on_done

    def run(self) -> None:
        if self.error_holder:
            return
        try:
            res = load_file(self.path, self.adapter)
            self.results[self.index] = res
        except Exception as exc:
            with self.lock:
                self.error_holder.append(exc)
        finally:
            self.on_done()


def load_paths(paths: list[Path], adapter: FileAdapter) -> ImportedTranslation:
    from autolingua2.infrastructure.operations import check_cancelled, report_progress
    files_to_load: list[Path] = []
    seen: set[Path] = set()

    for p in paths:
        check_cancelled()
        resolved = p.resolve()
        if not resolved.exists():
            raise ValueError(f"対象が見つかりません: {p}")
        if resolved.is_dir():
            for child in sorted(resolved.rglob("*")):
                if child.is_file() and adapter.can_load(child) and child not in seen:
                    seen.add(child)
                    files_to_load.append(child)
        elif resolved.is_file():
            if not adapter.can_load(resolved):
                raise ValueError(f"{adapter.name} で読み込めない対象です: {p}")
            if resolved not in seen:
                seen.add(resolved)
                files_to_load.append(resolved)

    total = len(files_to_load)
    if total == 0:
        imported = merge_imports([])
        imported.project.adapter_id = adapter.id
        return imported

    if total == 1:
        imported = merge_imports([load_file(files_to_load[0], adapter)])
        imported.project.adapter_id = adapter.id
        return imported

    results: list[ImportedTranslation | None] = [None] * total
    lock = threading.Lock()
    error_holder: list[Exception] = []
    completed_count = 0
    done_event = threading.Event()

    def on_done() -> None:
        nonlocal completed_count
        with lock:
            completed_count += 1
            if completed_count >= total or error_holder:
                done_event.set()

    pool = QThreadPool.globalInstance()
    for idx, file in enumerate(files_to_load):
        check_cancelled()
        runnable = _FileLoadRunnable(idx, file, adapter, results, lock, error_holder, on_done)
        pool.start(runnable)

    report_progress(f"0 / {total} ファイル解析中...")
    last_reported = 0

    while not done_event.wait(0.05):
        check_cancelled()
        with lock:
            if error_holder:
                break
            current = completed_count
        if current != last_reported:
            last_reported = current
            report_progress(f"{current} / {total} ファイル解析中...")

    check_cancelled()
    if error_holder:
        raise error_holder[0]

    report_progress(f"{total} / {total} ファイル解析完了")

    imports = [res for res in results if res is not None]
    imported = merge_imports(imports)
    imported.project.adapter_id = adapter.id
    return imported




def merge_imports(imports: list[ImportedTranslation]) -> ImportedTranslation:
    project = TranslationProject()
    source_refs: dict[str, SourceRef] = {}
    for imported in imports:
        if set(source_refs).intersection(imported.source_refs):
            raise ValueError("Duplicate translation unit IDs")
        project.extend(imported.project)
        source_refs.update(imported.source_refs)
    return ImportedTranslation(project=project, source_refs=source_refs)
