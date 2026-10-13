"""Independent tone persistence with atomic JSON saves."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from PySide6.QtCore import QIODevice, QSaveFile

from autolingua2.infrastructure.filesystem import PROJECT_ROOT
from autolingua2.infrastructure.platform import qt_file_path
from autolingua2.ir.tone import (
    COMPARISONS, OPERATORS, TARGETS, ConditionalTone, Tone, ToneBlock,
    ToneBranch, ToneComparison, ToneCondition, ToneExpression, ToneGroup,
    ToneItem, ToneOperator, ToneTarget,
    default_tone, validate_tones,
)
from autolingua2.ir.validation import array, record, required, text


TONE_PATH = PROJECT_ROOT / ".runtime" / "tones.json"


def _operator(value: object) -> ToneOperator:
    for operator in OPERATORS:
        if operator == value:
            return operator
    raise ValueError("条件の演算子が不正です。")


def _target(value: object) -> ToneTarget:
    for target in TARGETS:
        if target == value:
            return target
    raise ValueError("条件の対象が不正です。")


def _comparison(value: object) -> ToneComparison:
    for comparison in COMPARISONS:
        if comparison == value:
            return comparison
    raise ValueError("条件の判定方法が不正です。")


def _expression(value: object) -> ToneExpression:
    data = record(value)
    if "operator" in data:
        operator = _operator(required(data, "operator"))
        return ToneGroup(operator, [_expression(child) for child in array(required(data, "children"))])
    target = _target(required(data, "target"))
    comparison = _comparison(required(data, "comparison"))
    return ToneCondition(target, comparison, text(required(data, "value")))


def _block(value: object) -> ToneBlock:
    branches: list[ToneBranch] = []
    for value in array(required(record(value), "branches")):
        data = record(value)
        condition = required(data, "condition")
        tone_id = data.get("tone_id")
        block = data.get("block")
        branches.append(ToneBranch(
            _expression(condition) if condition is not None else None,
            text(tone_id, nonempty=True) if tone_id is not None else None,
            _block(block) if block is not None else None,
        ))
    return ToneBlock(branches)


def tone_from_document(value: object) -> Tone:
    item = record(value)
    tone_id = text(required(item, "id"), nonempty=True)
    name = text(required(item, "name"), nonempty=True)
    if "block" in item:
        return ConditionalTone(tone_id, name, _block(item["block"]))
    return ToneItem(tone_id, name, text(required(item, "prompt"), nonempty=True))


class ToneStore:
    def __init__(self, path: Path = TONE_PATH) -> None:
        self.path = path

    def load(self) -> list[Tone]:
        if not self.path.exists():
            tones: list[Tone] = [default_tone()]
            self.save(tones)
            return tones
        data = record(json.loads(self.path.read_text(encoding="utf-8")))
        if type(data.get("version")) is not int or data["version"] != 1:
            raise ValueError("対応していない口調データのバージョンです。")
        tones = []
        for value in array(required(data, "tones")):
            tones.append(tone_from_document(value))
        validate_tones(tones)
        return tones

    def save(self, tones: list[Tone]) -> None:
        validate_tones(tones)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = (json.dumps({"version": 1, "tones": [asdict(tone) for tone in tones]},
                              ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        output = QSaveFile(qt_file_path(self.path))
        output.setDirectWriteFallback(False)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload):
            error = output.errorString()
            output.cancelWriting()
            raise OSError(error)
        if not output.commit():
            raise OSError(output.errorString())
