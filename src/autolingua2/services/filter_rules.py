from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from autolingua2.ir import TranslationUnit


@dataclass(slots=True)
class FilterRule:
    id: str
    enabled: bool = True
    rule_type: str = "デフォルト"  # デフォルト / 開始 / 終了 / カスタム
    pattern: str = ""
    example: str = ""
    is_builtin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FilterRule:
        return cls(
            id=str(data.get("id", "")),
            enabled=bool(data.get("enabled", True)),
            rule_type=str(data.get("rule_type", "デフォルト")),
            pattern=str(data.get("pattern", "")),
            example=str(data.get("example", "")),
            is_builtin=bool(data.get("is_builtin", False)),
        )


@dataclass(slots=True)
class AdapterFilterConfig:
    disable_all_builtin: bool = False
    rules: list[FilterRule] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "disable_all_builtin": self.disable_all_builtin,
            "rules": [rule.to_dict() for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], default_rules: list[FilterRule] | None = None) -> AdapterFilterConfig:
        disable_all = bool(data.get("disable_all_builtin", False))
        raw_rules = data.get("rules")
        if raw_rules is None:
            # 未保存時はデフォルトルールを使用
            rules = [FilterRule.from_dict(r.to_dict()) for r in (default_rules or [])]
        else:
            rules = [FilterRule.from_dict(item) for item in raw_rules if isinstance(item, dict)]
            # デフォルトルールで不足しているものがあれば補完
            if default_rules:
                existing_ids = {r.id for r in rules}
                for default_rule in default_rules:
                    if default_rule.id not in existing_ids:
                        rules.append(FilterRule.from_dict(default_rule.to_dict()))

        return cls(disable_all_builtin=disable_all, rules=rules)


# Paradox YAML 向けの事前定義ルール
PARADOX_YAML_BUILTIN_RULES: list[FilterRule] = [
    FilterRule(id="paradox_1", enabled=True, rule_type="デフォルト", pattern=r"@\w+\s?", example="", is_builtin=True),
    FilterRule(id="paradox_2", enabled=True, rule_type="デフォルト", pattern=r"@?\[[\^\[\]]+\]", example="", is_builtin=True),
    FilterRule(id="paradox_3", enabled=True, rule_type="デフォルト", pattern=r"£[\w\|]+?[£\s]", example="", is_builtin=True),
    FilterRule(id="paradox_4", enabled=True, rule_type="デフォルト", pattern=r"[@£]\$.+?\$", example="", is_builtin=True),
    FilterRule(id="paradox_5", enabled=True, rule_type="デフォルト", pattern=r"\$[\w.@-]+\$|*[^$]*\$", example="", is_builtin=True),
    FilterRule(id="paradox_6", enabled=True, rule_type="開始", pattern=r"§\w", example="", is_builtin=True),
    FilterRule(id="paradox_7", enabled=True, rule_type="終了", pattern=r"§!", example="", is_builtin=True),
    FilterRule(id="paradox_8", enabled=True, rule_type="デフォルト", pattern=r"¤", example="", is_builtin=True),
    FilterRule(id="paradox_9", enabled=True, rule_type="デフォルト", pattern=r"@[A-Z]+(\s|$)", example="", is_builtin=True),
]


def get_default_filter_config(adapter_id: str) -> AdapterFilterConfig:
    from autolingua2.adapters.registry import get_all_adapters
    for adapter in get_all_adapters():
        aid = getattr(adapter, "id", None) or adapter.name.lower().replace(" ", "_")
        if aid == adapter_id or adapter.name == adapter_id:
            builtin_rules = getattr(adapter, "default_filter_rules", [])
            rules = [FilterRule.from_dict(r.to_dict()) for r in builtin_rules]
            return AdapterFilterConfig(disable_all_builtin=False, rules=rules)
    return AdapterFilterConfig(disable_all_builtin=False, rules=[])


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
