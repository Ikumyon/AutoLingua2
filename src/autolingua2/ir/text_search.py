from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from autolingua2.ir.workspace import UnitView


class SearchSyntaxError(ValueError):
    def __init__(self, reason: str, position: int) -> None:
        self.reason = reason
        self.position = position + 1
        super().__init__(f"{reason}（位置：{self.position}）")


@dataclass(frozen=True)
class _Condition:
    field: str | None
    pattern: re.Pattern[str]
    regex: bool


@dataclass(frozen=True)
class _Not:
    child: _Node


@dataclass(frozen=True)
class _Binary:
    operator: str
    left: _Node
    right: _Node


type _Node = _Condition | _Not | _Binary


@dataclass(frozen=True)
class _Token:
    kind: str
    position: int
    condition: _Condition | None = None


def _compile(expression: str, flags: int, position: int) -> re.Pattern[str]:
    try:
        return re.compile(expression, flags)
    except (re.error, ValueError) as error:
        raise SearchSyntaxError(f"正規表現が無効です：{error}", position) from error


class _Parser:
    def __init__(self, query: str, fields: Sequence[str], case_sensitive: bool) -> None:
        self.query = query
        self.fields = fields
        self.flags = 0 if case_sensitive else re.IGNORECASE
        self.index = 0
        self.token = self._next()

    def _next(self) -> _Token:
        text = self.query
        while self.index < len(text) and text[self.index].isspace():
            self.index += 1
        start = self.index
        if start == len(text):
            return _Token("END", start)
        if text[start] in "()-":
            self.index += 1
            return _Token("NOT" if text[start] == "-" else text[start], start)

        field: str | None = None
        prefix = re.match(r"([A-Za-z]+):", text[start:])
        if prefix is not None and prefix[1].casefold() in self.fields:
            field = prefix[1].casefold()
            self.index += len(prefix[0])
        value_start = self.index
        if text[self.index:self.index + 6].casefold() == "regex:":
            self.index += 6
            if self.index == len(text) or text[self.index] != "/":
                raise SearchSyntaxError("正規表現は regex:/パターン/ の形式で指定してください", value_start)
            self.index += 1
            pattern_start = self.index
            while self.index < len(text):
                if text[self.index] == "\\":
                    self.index += 2
                elif text[self.index] == "/":
                    break
                else:
                    self.index += 1
            if self.index >= len(text):
                raise SearchSyntaxError("正規表現の閉じ区切りがありません", pattern_start)
            expression = text[pattern_start:self.index]
            self.index += 1
            flags = 0
            flag_values = {"a": re.ASCII, "i": re.IGNORECASE, "m": re.MULTILINE,
                           "s": re.DOTALL, "u": re.UNICODE, "x": re.VERBOSE}
            while self.index < len(text) and not text[self.index].isspace() and text[self.index] not in "()":
                flag = text[self.index]
                if flag not in flag_values:
                    raise SearchSyntaxError(f"無効な正規表現フラグ：{flag}", self.index)
                flags |= flag_values[flag]
                self.index += 1
            return _Token("VALUE", start, _Condition(field, _compile(expression, flags, pattern_start), True))

        value: list[str] = []
        protected = False
        while self.index < len(text) and not text[self.index].isspace() and text[self.index] not in "()":
            char = text[self.index]
            if char == "\\":
                protected = True
                self.index += 1
                if self.index == len(text):
                    raise SearchSyntaxError("エスケープ対象がありません", self.index - 1)
                value.append(text[self.index])
                self.index += 1
            elif char == '"':
                protected = True
                quote_start = self.index
                self.index += 1
                while self.index < len(text) and text[self.index] != '"':
                    if (text[self.index] == "\\" and self.index + 1 < len(text)
                            and text[self.index + 1] in '\\"'):
                        self.index += 1
                    value.append(text[self.index])
                    self.index += 1
                if self.index == len(text):
                    raise SearchSyntaxError("引用符が閉じていません", quote_start)
                self.index += 1
            else:
                value.append(char)
                self.index += 1
        if not value:
            raise SearchSyntaxError("検索値がありません", value_start)
        literal = "".join(value)
        if field is None and not protected and literal.upper() in ("AND", "OR", "NOT"):
            return _Token(literal.upper(), start)
        return _Token("VALUE", start, _Condition(field, _compile(re.escape(literal), self.flags, start), False))

    def _advance(self) -> _Token:
        token = self.token
        self.token = self._next()
        return token

    def parse(self) -> _Node | None:
        if self.token.kind == "END":
            return None
        node = self._or()
        if self.token.kind != "END":
            raise SearchSyntaxError("予期しない閉じ括弧です", self.token.position)
        return node

    def _or(self) -> _Node:
        node = self._and()
        while self.token.kind == "OR":
            self._advance()
            node = _Binary("OR", node, self._and())
        return node

    def _and(self) -> _Node:
        node = self._unary()
        while self.token.kind in ("AND", "VALUE", "NOT", "("):
            if self.token.kind == "AND":
                self._advance()
            node = _Binary("AND", node, self._unary())
        return node

    def _unary(self) -> _Node:
        if self.token.kind == "NOT":
            self._advance()
            return _Not(self._unary())
        if self.token.kind == "(":
            start = self._advance().position
            node = self._or()
            if self.token.kind != ")":
                raise SearchSyntaxError("閉じ括弧がありません", start)
            self._advance()
            return node
        if self.token.kind != "VALUE":
            raise SearchSyntaxError("検索条件が必要です", self.token.position)
        condition = self._advance().condition
        if condition is None:
            raise SearchSyntaxError("検索条件が必要です", self.token.position)
        return condition


class TextSearch:
    """Compile one search expression for row filtering and target replacement."""

    def __init__(self, query: str, *, case_sensitive: bool = False,
                 whole_word: bool = False, regex: bool = False,
                 fields: Sequence[str] = ("key", "source", "target", "context", "file", "status")) -> None:
        self.whole_word = whole_word
        if regex:
            self._root: _Node | None = (
                _Condition(None, _compile(query, 0 if case_sensitive else re.IGNORECASE, 0), True)
                if query else None
            )
        else:
            self._root = _Parser(query, fields, case_sensitive).parse()

    def _matches(self, condition: _Condition, text: str) -> Iterator[re.Match[str]]:
        for match in condition.pattern.finditer(text):
            start, end = match.span()
            if self.whole_word and (
                (start > 0 and re.match(r"\w", text[start - 1]) is not None)
                or (end < len(text) and re.match(r"\w", text[end]) is not None)
            ):
                continue
            yield match

    def matches_fields(self, values: Mapping[str, Sequence[str]]) -> bool:
        def evaluate(node: _Node) -> bool:
            if isinstance(node, _Condition):
                groups = values.values() if node.field is None else (values[node.field],)
                return any(next(self._matches(node, value), None) is not None
                           for group in groups for value in group)
            if isinstance(node, _Not):
                return not evaluate(node.child)
            if node.operator == "AND":
                return evaluate(node.left) and evaluate(node.right)
            return evaluate(node.left) or evaluate(node.right)

        return self._root is None or evaluate(self._root)

    def matches(self, unit: UnitView, *, file_name: str = "", status: str = "") -> bool:
        return self.matches_fields({
            "key": (unit.label,), "source": (unit.source_text,),
            "target": (unit.target_text,), "context": (unit.context,),
            "file": (file_name,), "status": (status,),
        })

    @property
    def can_replace(self) -> bool:
        return isinstance(self._root, _Condition) and self._root.field in (None, "target")

    def count(self, text: str) -> int:
        condition = self._root
        if not isinstance(condition, _Condition) or not self.can_replace:
            return 0
        return sum(1 for _ in self._matches(condition, text))

    def replace(self, text: str, replacement: str, *, all_matches: bool) -> tuple[str, int]:
        condition = self._root
        if not isinstance(condition, _Condition) or not self.can_replace:
            return text, 0
        pieces: list[str] = []
        end = count = 0
        for match in self._matches(condition, text):
            pieces.append(text[end:match.start()])
            pieces.append(match.expand(replacement) if condition.regex else replacement)
            end = match.end()
            count += 1
            if not all_matches:
                break
        pieces.append(text[end:])
        return "".join(pieces), count
