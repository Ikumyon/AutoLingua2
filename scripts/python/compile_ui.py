"""Compile one .ui beside its source, including its form and root type metadata."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


def compile_ui(source: Path, uic: Path) -> None:
    output = source.with_suffix(".py")
    if output.exists():
        raise FileExistsError(f"生成先が既に存在します: {output}")
    document = ET.parse(source).getroot()
    form_name = document.findtext("class")
    root_widget = document.find("widget")
    if form_name is None or not form_name.isidentifier() or root_widget is None:
        raise ValueError(f"UIのフォーム定義が不正です: {source}")
    root_name = root_widget.get("class")
    if root_name is None or not root_name.isidentifier():
        raise ValueError(f"UIのルート型が不正です: {source}")
    result = subprocess.run(
        [str(uic), str(source)], check=True, stdout=subprocess.PIPE, encoding="utf-8",
    )
    # 個々の生成モジュール自身が、ファイル名に依存せず型を公開する。
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(result.stdout)
        stream.write(
            f"\nfrom PySide6.QtWidgets import {root_name} as UI_ROOT_CLASS\n"
            f"UI_FORM_CLASS = Ui_{form_name}\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("uic", type=Path)
    args = parser.parse_args()
    compile_ui(args.source, args.uic)


if __name__ == "__main__":
    main()
