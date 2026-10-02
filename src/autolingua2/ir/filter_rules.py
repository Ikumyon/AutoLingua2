from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re

from .unit import TranslationUnit
from .validation import array, boolean, record, required, string_field, text


@dataclass(slots=True)
class FilterRule:
    id: str
    enabled: bool = True
    rule_type: str = "デフォルト"  # デフォルト / 開始 / 終了 / カスタム
    pattern: str = ""
    example: str = ""
    is_builtin: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> FilterRule:
        data = record(value)
        return cls(
            id=text(required(data, "id"), nonempty=True),
            enabled=boolean(data.get("enabled", True)),
            rule_type=string_field(data, "rule_type", "デフォルト"),
            pattern=string_field(data, "pattern"),
            example=string_field(data, "example"),
            is_builtin=boolean(data.get("is_builtin", False)),
        )


@dataclass(slots=True)
class AdapterFilterConfig:
    disable_all_builtin: bool = False
    rules: list[FilterRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "disable_all_builtin": self.disable_all_builtin,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, value: object, default_rules: list[FilterRule] | None = None) -> AdapterFilterConfig:
        data = record(value)
        disable_all = boolean(data.get("disable_all_builtin", False))
        if "rules" not in data:
            # 未保存時はデフォルトルールを使用
            rules = [FilterRule.from_dict(r.to_dict()) for r in (default_rules or [])]
        else:
            rules = [FilterRule.from_dict(item) for item in array(data["rules"])]
            # デフォルトルールで不足しているものがあれば補完
            if default_rules:
                existing_ids = {r.id for r in rules}
                for default_rule in default_rules:
                    if default_rule.id not in existing_ids:
                        rules.append(FilterRule.from_dict(default_rule.to_dict()))

        return cls(disable_all_builtin=disable_all, rules=rules)


def should_hide_unit(unit: TranslationUnit, config: AdapterFilterConfig) -> bool:
    """ユニット（文章・キー）が有効な非表示ルールにマッチするか判定する。"""
    text = unit.source_text
    label = unit.label

    # 空白のみの行は常に非表示対象
    if not text.strip():
        return True

    for rule in config.rules:
        if not rule.enabled:
            continue
        if rule.is_builtin and config.disable_all_builtin:
            continue
        if not rule.pattern.strip():
            continue

        try:
            regex = re.compile(rule.pattern)
            # 原文テキストにマッチするか、またはキー名にマッチするか判定
            if regex.search(text) is not None or regex.search(label) is not None:
                return True
        except re.error:
            # 不正な正規表現はスキップ
            continue

    return False
