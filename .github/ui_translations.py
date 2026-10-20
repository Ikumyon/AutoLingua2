"""Extract Qt UI messages with lupdate and split packaged originals by context.

Run normally to update assets/i18n; --check reports translation gaps without
changing catalogs, and --compile builds runtime QM dictionaries.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def find_qt_tool(name: str) -> str:
    for directory in (sysconfig.get_path("scripts"), str(Path(sys.executable).parent)):
        executable = shutil.which(name, path=directory)
        if executable is not None:
            return executable
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"{name} が見つかりません。同じ仮想環境で実行してください。")
    return executable


def catalogs() -> dict[str, bytes]:
    executable = find_qt_tool("pyside6-lupdate")
    with tempfile.TemporaryDirectory() as temporary:
        extracted = Path(temporary) / "extracted.ts"
        subprocess.run([
            executable, str(ROOT / "src/autolingua2/ui"), str(ROOT / "ui"),
            "-extensions", "py,ui",
            "-tr-function-alias", "tr=unusedTr,translate+=tr,QT_TRANSLATE_NOOP+=translation_source",
            "-source-language", "ja", "-target-language", "ja",
            "-locations", "none", "-no-obsolete", "-silent", "-ts", str(extracted),
        ], check=True, stdout=sys.stderr)
        document = ET.parse(extracted).getroot()

    # Qt's Python extractor does not reliably recognize our tr(context, text)
    # wrapper aliases. Include literal wrapper calls directly from the AST.
    for path in sorted((ROOT / "src/autolingua2/ui").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in ("tr", "translation_source") or len(node.args) < 2:
                continue
            context_arg, source_arg = node.args[:2]
            if not all(isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                       for arg in (context_arg, source_arg)):
                continue
            context = ET.SubElement(document, "context")
            ET.SubElement(context, "name").text = context_arg.value
            message = ET.SubElement(context, "message")
            ET.SubElement(message, "source").text = source_arg.value

    sections: dict[str, dict[tuple[str, str], ET.Element]] = {}
    for context in document.findall("context"):
        name = context.findtext("name", "")
        if not name:
            raise ValueError("翻訳コンテキスト名が空です。")
        if name == "LanguageNames":
            continue
        messages = sections.setdefault(name, {})
        for item in context.findall("message"):
            source = item.findtext("source", "")
            if not source:
                continue
            message = deepcopy(item)
            translation = message.find("translation")
            if translation is None:
                translation = ET.SubElement(message, "translation")
            translation.attrib.clear()
            translation.text = source
            messages[(source, message.findtext("comment", ""))] = message

    # Language identifiers deliberately differ from their Japanese display names.
    # Retain the existing licensed dictionary as the source of that association.
    names = ET.parse(ROOT / "assets/i18n/LanguageNames.ts").getroot()
    for context in names.findall("context"):
        messages = sections.setdefault(context.findtext("name", ""), {})
        for message in context.findall("message"):
            messages[(message.findtext("source", ""), message.findtext("comment", ""))] = deepcopy(message)

    output: dict[str, bytes] = {}
    for name, messages in sorted(sections.items()):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ValueError(f"翻訳ファイル名に使用できないコンテキストです: {name}")
        root = ET.Element("TS", version="2.1", language="ja", sourcelanguage="ja")
        if name == "LanguageNames":
            root.append(ET.Comment("Language names: Unicode CLDR 48.0.0, main/ja. Unicode License v3; see CLDR-LICENSE.txt."))
        section = ET.SubElement(root, "context")
        ET.SubElement(section, "name").text = name
        for _, message in sorted(messages.items()):
            section.append(message)
        ET.indent(root, space="  ")
        output[f"{name}.ts"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if not output:
        raise ValueError("本体UIの原文カタログが空です。")
    return output


def message_entries(document: ET.Element) -> dict[tuple[str, str, str], ET.Element]:
    entries: dict[tuple[str, str, str], ET.Element] = {}
    for context in document.findall("context"):
        for message in context.findall("message"):
            translation = message.find("translation")
            if translation is not None and translation.get("type") in ("obsolete", "vanished"):
                continue
            key = (context.findtext("name", ""), message.findtext("source", ""),
                   message.findtext("comment", ""))
            if key in entries:
                raise ValueError(f"重複する翻訳キー: {key}")
            entries[key] = message
    return entries


def check_translations(output: dict[str, bytes]) -> bool:
    originals: dict[tuple[str, str, str], ET.Element] = {}
    for content in output.values():
        entries = message_entries(ET.fromstring(content))
        if originals.keys() & entries.keys():
            raise ValueError("日本語原文カタログに重複する翻訳キーがあります。")
        originals.update(entries)
    print(f"日本語: 100% ({len(originals)}項目)")
    complete = True
    for folder in sorted((ROOT / "translations").iterdir()):
        if not folder.is_dir() or not (folder / "metadata.json").is_file():
            continue
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        tag = metadata["code"].replace("_", "-")
        if tag.lower() in ("ja", "ja-jp"):
            continue
        entries: dict[tuple[str, str, str], ET.Element] = {}
        for path in sorted(folder.glob("*.ts")):
            catalog = message_entries(ET.parse(path).getroot())
            if entries.keys() & catalog.keys():
                raise ValueError(f"{tag}: ファイル間で翻訳キーが重複しています: {path.name}")
            entries.update(catalog)
        missing = originals.keys() - entries.keys()
        extra = entries.keys() - originals.keys()
        unfinished = set()
        for key in originals.keys() & entries.keys():
            translation = entries[key].find("translation")
            if translation is None or translation.get("type") == "unfinished":
                unfinished.add(key)
                continue
            forms = translation.findall("numerusform")
            if not all("".join(item.itertext()).strip() for item in (forms or [translation])):
                unfinished.add(key)
        print(f"{tag}: 不足 {len(missing)} / 未翻訳 {len(unfinished)} / 旧項目 {len(extra)}")
        for label, keys in (("不足", missing), ("未翻訳", unfinished), ("旧項目", extra)):
            for key in sorted(keys):
                print(f"  {label}: {key!r}")
        complete = complete and not (missing or unfinished or extra)
    return complete


def compile_translations() -> None:
    executable = find_qt_tool("pyside6-lrelease")
    for folder in sorted((ROOT / "translations").iterdir()):
        if not folder.is_dir() or not (folder / "metadata.json").is_file():
            continue
        for path in sorted(folder.glob("*.ts")):
            subprocess.run([executable, "-nounfinished", str(path), "-qm", str(path.with_suffix(".qm"))],
                           check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--print", action="store_true", dest="print_only")
    mode.add_argument("--check", action="store_true", help="日本語原文と各言語のTSを比較（差分ありは終了コード1）")
    mode.add_argument("--compile", action="store_true", dest="compile_only", help="各言語のTSをQMに変換")
    options = parser.parse_args()
    if options.compile_only:
        compile_translations()
        return 0
    output = catalogs()
    if options.check:
        return 0 if check_translations(output) else 1
    elif options.print_only:
        print(json.dumps({name: content.decode("utf-8") for name, content in output.items()}, ensure_ascii=True))
    else:
        destination = ROOT / "assets/i18n"
        destination.mkdir(parents=True, exist_ok=True)
        for name, content in output.items():
            (destination / name).write_bytes(content)
        (destination / "CLDR-LICENSE.txt").write_bytes((ROOT / "translations/ja_JP/CLDR-LICENSE.txt").read_bytes())
        for obsolete in destination.glob("*.ts"):
            if obsolete.name not in output:
                obsolete.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
