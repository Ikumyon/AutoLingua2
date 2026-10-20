"""Event definitions for managed triggers; reuse ALS types and expressions."""
from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
import json
import re

from autolingua2.ir.automation_script import (
    Binding, Checker, Expression, Parser, ReadValue, Scope, Script, ScriptError,
    SCREEN_FUNCTIONS, Statement, Step, Value,
)


EVENTS = {"app_started", "project_opened", "translation_completed", "schedule"}
CONTEXT_TYPES = {"project_is_open": "bool", "project_name": "string",
                 "project_target_language": "string", "project_source_language": "string"}
EXAMPLE = '''on translation_completed {
    if project.is_open {
        run("D:/scripts/export.als")
    }
}
'''


@dataclass(frozen=True)
class TriggerDefinition:
    id: str
    name: str
    source: str
    enabled: bool = False


@dataclass(frozen=True)
class Handler:
    event: str
    time: str | None
    body: tuple[Statement, ...]


class TriggerChecker(Checker):
    def expression(self, node: Expression, scope: dict[str, Binding], expected: str | None = None) -> str:
        if node.kind == "name" and node.token.text in CONTEXT_TYPES:
            return CONTEXT_TYPES[node.token.text]
        if node.kind == "call" and node.token.text == "run":
            if len(node.args) != 1:
                raise ScriptError(node.token, "runにはスクリプトの絶対パスを1つ指定してください。")
            self.require(node.args[0], scope, "string")
            return "void"
        if node.kind == "call" and node.token.text in SCREEN_FUNCTIONS:
            raise ScriptError(node.token, "画面操作は処理用.alsに記述し、runで呼び出してください。")
        return super().expression(node, scope, expected)

    def block(self, body, scope, result=None, loop=False, *, top=False):
        for node in body:
            if node.name in CONTEXT_TYPES or (node.kind == "function" and node.name == "run"):
                raise ScriptError(node.token, "予約された名前は変更できません。")
        return super().block(body, scope, result, loop, top=top)


class TriggerEvaluation(Script):
    def __init__(self, program: tuple[Statement, ...], context: dict[str, Value]) -> None:
        self.program = program
        checker = TriggerChecker(program)
        checker.block(program, {}, top=True)
        self.functions, self.read_types = checker.functions, checker.read_types
        self.depth = 0
        self.context = context
        self.paths: list[str] = []

    def evaluate(self, node: Expression, scope: Scope) -> Generator[Step, ReadValue, Value]:
        if node.kind == "name" and node.token.text in CONTEXT_TYPES:
            yield Step(node.token)
            return self.context[node.token.text]
        if node.kind == "call" and node.token.text == "run":
            path = yield from self.evaluate(node.args[0], scope)
            if not isinstance(path, str) or not path.strip():
                raise ScriptError(node.token, "スクリプトのパスが空です。")
            self.paths.append(path)
            if len(self.paths) > 32:
                raise ScriptError(node.token, "1回に呼び出せるスクリプトは32件までです。")
            return None
        return (yield from super().evaluate(node, scope))


class TriggerScript:
    def __init__(self, source: str) -> None:
        # Preserve strings/comments and source positions while mapping project fields
        # to ALS identifiers. No Python or other host-language code is evaluated.
        source = re.sub(
            r'"(?:[^"\\\n]|\\.)*"|//[^\n]*|\bproject\.(is_open|name|target_language|source_language)\b',
            lambda match: match.group().replace(".", "_", 1) if match.group(1) else match.group(), source,
        )
        parser = Parser(source)
        self.handlers: list[Handler] = []
        functions: list[Statement] = []
        try:
            while parser.current.text != "<EOF>":
                if parser.current.text == "function":
                    functions.append(parser.statement())
                    continue
                parser.take("on")
                event = parser.take()
                if event.text not in EVENTS:
                    raise ScriptError(event, "未対応のトリガーです。")
                time = None
                if event.text == "schedule":
                    parser.take("(")
                    token = parser.take()
                    if token.kind != "string":
                        raise ScriptError(token, '時刻は"09:00"の形式で指定してください。')
                    time = json.loads(token.text)
                    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", time):
                        raise ScriptError(token, "時刻は00:00〜23:59で指定してください。")
                    parser.take(")")
                self.handlers.append(Handler(event.text, time, parser.block()))
            if not self.handlers:
                raise ScriptError(parser.current, "onでトリガーを1つ以上定義してください。")
            self.functions = tuple(functions)
            for handler in self.handlers:
                checker = TriggerChecker(self.functions + handler.body)
                checker.block(self.functions + handler.body, {}, top=True)
        except (RecursionError, json.JSONDecodeError) as exc:
            raise ScriptError(parser.current, "トリガー定義を解釈できません。") from exc

    def paths(self, event: str, context: dict[str, Value], time: str | None = None) -> list[str]:
        paths: list[str] = []
        for handler in self.handlers:
            if handler.event != event or handler.time != time:
                continue
            evaluation = TriggerEvaluation(self.functions + handler.body, context)
            iterator = evaluation.steps()
            try:
                for count, _step in enumerate(iterator):
                    if count >= 10000:
                        raise ValueError("トリガー条件の計算上限を超えました。")
            finally:
                iterator.close()
            paths.extend(evaluation.paths)
            if len(paths) > 32:
                raise ValueError("1回に呼び出せるスクリプトは32件までです。")
        return paths
