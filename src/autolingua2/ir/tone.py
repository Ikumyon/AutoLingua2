"""Shared tones and pure, ordered conditional tone evaluation."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from collections.abc import Sequence
from typing import Literal


ToneTarget = Literal["filename", "key", "original"]
ToneComparison = Literal["equals", "contains", "starts_with", "ends_with", "regex"]
ToneOperator = Literal["and", "or", "not"]
TARGETS: tuple[ToneTarget, ...] = ("filename", "key", "original")
COMPARISONS: tuple[ToneComparison, ...] = (
    "equals", "contains", "starts_with", "ends_with", "regex",
)
OPERATORS: tuple[ToneOperator, ...] = ("and", "or", "not")


@dataclass(slots=True)
class ToneCondition:
    target: ToneTarget = "filename"
    comparison: ToneComparison = "contains"
    value: str = ""


@dataclass(slots=True)
class ToneGroup:
    operator: ToneOperator
    children: list[ToneExpression] = field(default_factory=list)


ToneExpression = ToneCondition | ToneGroup


@dataclass(slots=True)
class ToneBranch:
    condition: ToneExpression | None
    tone_id: str | None = None
    block: ToneBlock | None = None


@dataclass(slots=True)
class ToneBlock:
    branches: list[ToneBranch] = field(default_factory=lambda: [
        ToneBranch(ToneCondition()), ToneBranch(None),
    ])


@dataclass(slots=True)
class ToneItem:
    id: str
    name: str
    prompt: str


@dataclass(slots=True)
class ConditionalTone:
    id: str
    name: str
    block: ToneBlock = field(default_factory=ToneBlock)


Tone = ToneItem | ConditionalTone
DEFAULT_TONE_ID = "tone_joutai"


def default_tone() -> ToneItem:
    return ToneItem(DEFAULT_TONE_ID, "常態", "常体（だ・である調）で翻訳してください。")


def add_tone_branch(parent: ConditionalTone | ToneBranch) -> None:
    """Add to the selected parent's chain, preserving a leaf's default tone."""
    if isinstance(parent, ToneBranch) and parent.block is None:
        parent.block = ToneBlock()
        parent.block.branches[-1].tone_id = parent.tone_id
        parent.tone_id = None
        return
    block = parent.block
    if block is None:
        raise ValueError("条件分岐の親がありません。")
    if not block.branches:
        block.branches.extend(ToneBlock().branches)
    else:
        block.branches.insert(len(block.branches) - 1, ToneBranch(ToneCondition()))


def remove_nested_branches(branch: ToneBranch) -> None:
    """Restore the final ELSE's tone when returning a parent to a leaf."""
    block = branch.block
    while block is not None:
        last = block.branches[-1]
        branch.tone_id = last.tone_id
        block = last.block
    branch.block = None


def tone_references(tones: Sequence[Tone], tone_id: str) -> list[ToneBranch]:
    references: list[ToneBranch] = []

    def collect(block: ToneBlock) -> None:
        for branch in block.branches:
            if branch.tone_id == tone_id:
                references.append(branch)
            if branch.block is not None:
                collect(branch.block)

    for tone in tones:
        if isinstance(tone, ConditionalTone):
            collect(tone.block)
    return references


def delete_tone(tones: list[Tone], tone_id: str) -> None:
    index = next((i for i, tone in enumerate(tones) if tone.id == tone_id), None)
    if index is None:
        raise ValueError("削除する口調が存在しません。")
    for branch in tone_references(tones, tone_id):
        branch.tone_id = None
    tones.pop(index)


@dataclass(frozen=True, slots=True)
class ToneContext:
    filename: str
    key: str
    original: str


def validate_expression(expression: ToneExpression) -> None:
    if isinstance(expression, ToneCondition):
        if expression.target not in TARGETS or expression.comparison not in COMPARISONS:
            raise ValueError("条件の対象または判定方法が不正です。")
        if not expression.value:
            raise ValueError("比較する文字列を入力してください。")
        if expression.comparison == "regex":
            try:
                re.compile(expression.value)
            except re.error as exc:
                raise ValueError(f"正規表現が不正です：{exc}") from exc
        return
    if expression.operator not in OPERATORS:
        raise ValueError("条件の演算子が不正です。")
    if expression.operator == "not":
        if len(expression.children) != 1:
            raise ValueError("NOTには条件またはグループを1つ指定してください。")
    elif len(expression.children) < 2:
        raise ValueError("AND・ORには条件またはグループを2つ以上指定してください。")
    for child in expression.children:
        validate_expression(child)


def validate_block(block: ToneBlock, tone_ids: set[str]) -> None:
    if len(block.branches) < 2 or block.branches[-1].condition is not None:
        raise ValueError("条件分岐にはIFと末尾のELSEが必要です。")
    for index, branch in enumerate(block.branches):
        try:
            if index < len(block.branches) - 1:
                if branch.condition is None:
                    raise ValueError("ELSEは末尾だけに配置できます。")
                validate_expression(branch.condition)
            if branch.block is not None:
                if branch.tone_id is not None:
                    raise ValueError("口調と条件分岐を同時に指定できません。")
                validate_block(branch.block, tone_ids)
            elif branch.tone_id is not None and branch.tone_id not in tone_ids:
                raise ValueError("参照する個別口調が存在しません。口調を選び直してください。")
        except ValueError as exc:
            label = "それ以外の場合" if branch.condition is None else f"分岐{index + 1}"
            raise ValueError(f"{label}：{exc}") from exc


def validate_tones(tones: Sequence[Tone]) -> None:
    ids: set[str] = set()
    normal_ids = {tone.id for tone in tones if isinstance(tone, ToneItem)}
    for tone in tones:
        if not tone.id.strip() or tone.id in ids:
            raise ValueError("口調IDが空か重複しています。")
        ids.add(tone.id)
        if not tone.name.strip():
            raise ValueError("口調名を入力してください。")
        try:
            if isinstance(tone, ToneItem):
                if not tone.prompt.strip():
                    raise ValueError("指示プロンプトを入力してください。")
            else:
                validate_block(tone.block, normal_ids)
        except ValueError as exc:
            raise ValueError(f"{tone.name}：{exc}") from exc


def matches(expression: ToneExpression, context: ToneContext) -> bool:
    if isinstance(expression, ToneGroup):
        if expression.operator == "and":
            return all(matches(child, context) for child in expression.children)
        if expression.operator == "or":
            return any(matches(child, context) for child in expression.children)
        return not matches(expression.children[0], context)
    value = {"filename": context.filename, "key": context.key, "original": context.original}[expression.target]
    match expression.comparison:
        case "equals":
            return value == expression.value
        case "contains":
            return expression.value in value
        case "starts_with":
            return value.startswith(expression.value)
        case "ends_with":
            return value.endswith(expression.value)
        case "regex":
            return re.search(expression.value, value) is not None


def resolve_tone(block: ToneBlock, tones: Sequence[ToneItem], context: ToneContext) -> ToneItem | None:
    """Walk IF/ELSEIF/ELSE from top to bottom; only normal tones are destinations."""
    for branch in block.branches:
        if branch.condition is not None and not matches(branch.condition, context):
            continue
        if branch.block is not None:
            return resolve_tone(branch.block, tones, context)
        if branch.tone_id is None:
            return None
        tone = next((item for item in tones if item.id == branch.tone_id), None)
        if tone is None:
            raise ValueError("参照する個別口調が存在しません。")
        return tone
    raise ValueError("条件分岐にELSEがありません。")
