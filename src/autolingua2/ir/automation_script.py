"""Typed, single-file automation language. No host code is evaluated."""
from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
import json
import math
import re


type Value = str | int | float | bool | list[Value] | None
type ReadValue = str | int | float | bool | None


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    column: int
    kind: str = "symbol"


class ScriptError(ValueError):
    def __init__(self, token: Token, message: str) -> None:
        self.token = token
        super().__init__(f"{token.line}行 {token.column}列: {message}")


@dataclass(frozen=True)
class Expression:
    token: Token
    kind: str
    args: tuple[Expression, ...] = ()


@dataclass(frozen=True)
class Statement:
    token: Token
    kind: str
    name: str = ""
    dtype: str = "void"
    expression: Expression | None = None
    body: tuple[Statement, ...] = ()
    other: tuple[Statement, ...] = ()
    parameters: tuple[tuple[str, str], ...] = ()


TYPES = {"string", "int", "float", "bool"}
READ_FUNCTIONS = {
    "spin_get": ("int", "float"),
    "combo_get": ("string",),
    "text_get": ("string",),
    "check_get": ("bool",),
    "slider_get": ("int",),
    "table_row_get": ("string",),
}
SCREEN_FUNCTIONS = {"click", "table_row", "combo_select", "spin_set", "spin_add", "spin_sub"} | READ_FUNCTIONS.keys()
RESERVED = TYPES | {"void", "function", "if", "else", "for", "in", "return", "break", "continue", "true", "false"}
LEXER = re.compile(r'(?P<space>[^\S\n]+)|(?P<comment>//[^\n]*)|(?P<newline>\n)|(?P<string>"(?:[^"\\\n]|\\.)*")|(?P<number>\d+(?:\.\d+)?)|(?P<name>[^\W\d]\w*)|(?P<symbol>==|!=|<=|>=|&&|\|\||[{}()\[\],:=+*/%<>!\-])')
PRECEDENCE = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}


class Parser:
    def __init__(self, source: str) -> None:
        self.tokens: list[Token] = []
        line = column = 1
        position = 0
        while position < len(source):
            match = LEXER.match(source, position)
            if match is None:
                raise ScriptError(Token(source[position], line, column), "解釈できない文字です。")
            text = match.group()
            kind = match.lastgroup
            if kind == "newline":
                line += 1
                column = 1
            else:
                if kind not in {"space", "comment"}:
                    self.tokens.append(Token(text, line, column, kind or "symbol"))
                column += len(text)
            position = match.end()
        self.tokens.append(Token("<EOF>", line, column))
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self, text: str | None = None) -> Token:
        token = self.current
        if text is not None and token.text != text:
            raise ScriptError(token, f"'{text}' が必要です。")
        if token.text == "<EOF>":
            raise ScriptError(token, "途中でファイルが終了しました。")
        self.index += 1
        return token

    def accept(self, text: str) -> bool:
        if self.current.text != text:
            return False
        self.take()
        return True

    def identifier(self) -> str:
        token = self.take()
        if token.kind != "name" or token.text in RESERVED:
            raise ScriptError(token, "識別子が必要です。")
        return token.text

    def dtype(self, *, allow_void: bool = False) -> str:
        token = self.take()
        if token.text not in TYPES and not (allow_void and token.text == "void"):
            raise ScriptError(token, "型の指定が必要です。")
        dtype = token.text
        if self.accept("["):
            if dtype == "void":
                raise ScriptError(token, "voidの配列は宣言できません。")
            self.take("]")
            dtype += "[]"
        return dtype

    def block(self) -> tuple[Statement, ...]:
        self.take("{")
        body: list[Statement] = []
        while not self.accept("}"):
            body.append(self.statement())
        return tuple(body)

    def statement(self) -> Statement:
        token = self.current
        if token.text == "function":
            self.take()
            name = self.identifier()
            self.take("(")
            parameters: list[tuple[str, str]] = []
            if not self.accept(")"):
                while True:
                    dtype = self.dtype()
                    parameters.append((self.identifier(), dtype))
                    if self.accept(")"):
                        break
                    self.take(",")
            self.take(":")
            dtype = self.dtype(allow_void=True)
            return Statement(token, "function", name, dtype, body=self.block(), parameters=tuple(parameters))
        if self.accept("if"):
            expression = self.expression()
            body = self.block()
            other: tuple[Statement, ...] = ()
            if self.accept("else"):
                other = (self.statement(),) if self.current.text == "if" else self.block()
            return Statement(token, "if", expression=expression, body=body, other=other)
        if self.accept("for"):
            dtype = self.dtype()
            name = self.identifier()
            self.take("in")
            expression = self.expression()
            return Statement(token, "for", name, dtype, expression, self.block())
        if token.text in {"break", "continue"}:
            self.take()
            return Statement(token, token.text)
        if self.accept("return"):
            expression = None
            if self.current.text != "}" and self.current.line == token.line:
                expression = self.expression()
            return Statement(token, "return", expression=expression)
        if token.text in TYPES:
            dtype = self.dtype()
            name = self.identifier()
            expression = self.expression() if self.accept("=") else None
            return Statement(token, "declare", name, dtype, expression)
        if self.current.kind == "name" and self.tokens[self.index + 1].text == "=":
            name = self.identifier()
            self.take("=")
            return Statement(token, "assign", name, expression=self.expression())
        return Statement(token, "expression", expression=self.expression())

    def expression(self, minimum: int = 0) -> Expression:
        token = self.take()
        if token.text in {"!", "-", "+"}:
            left = Expression(token, "unary", (self.expression(7),))
        elif token.text == "(":
            left = self.expression()
            self.take(")")
        elif token.text == "[":
            left = Expression(token, "array", self.arguments("]"))
        elif token.kind in {"number", "string"} or token.text in {"true", "false"}:
            left = Expression(token, "literal")
        elif token.kind == "name" and token.text not in RESERVED:
            left = Expression(token, "name")
            if self.accept("("):
                left = Expression(token, "call", self.arguments(")"))
        else:
            raise ScriptError(token, "式が必要です。")
        while True:
            if self.accept("["):
                index = self.expression()
                self.take("]")
                left = Expression(token, "index", (left, index))
                continue
            operator = self.current
            precedence = PRECEDENCE.get(operator.text, -1)
            if precedence < minimum:
                break
            self.take()
            left = Expression(operator, "binary", (left, self.expression(precedence + 1)))
        return left

    def arguments(self, end: str) -> tuple[Expression, ...]:
        args: list[Expression] = []
        if not self.accept(end):
            while True:
                args.append(self.expression())
                if self.accept(end):
                    break
                self.take(",")
        return tuple(args)

    def parse(self) -> tuple[Statement, ...]:
        statements: list[Statement] = []
        while self.current.text != "<EOF>":
            statements.append(self.statement())
        return tuple(statements)


@dataclass
class Binding:
    dtype: str
    initialized: bool


def copy_bindings(bindings: dict[str, Binding]) -> dict[str, Binding]:
    return {name: Binding(value.dtype, value.initialized) for name, value in bindings.items()}


def literal(expression: Expression) -> Value:
    token = expression.token
    if token.kind == "string":
        try:
            value: object = json.loads(token.text)
        except ValueError as exc:
            raise ScriptError(token, "文字列のエスケープが不正です。") from exc
        if not isinstance(value, str):
            raise ScriptError(token, "文字列が必要です。")
        return value
    if token.text in {"true", "false"}:
        return token.text == "true"
    return float(token.text) if "." in token.text else int(token.text)


class Checker:
    def __init__(self, program: tuple[Statement, ...]) -> None:
        self.functions: dict[str, Statement] = {}
        self.read_types: dict[Token, str] = {}
        for item in program:
            if item.kind == "function":
                if item.name in self.functions or item.name in SCREEN_FUNCTIONS:
                    raise ScriptError(item.token, f"関数が重複しています: {item.name}")
                self.functions[item.name] = item

    def expression(self, node: Expression, scope: dict[str, Binding], expected: str | None = None) -> str:
        token = node.token
        if node.kind == "literal":
            value = literal(node)
            if type(value) is bool:
                return "bool"
            if type(value) is int:
                return "int"
            if type(value) is float:
                return "float"
            return "string"
        if node.kind == "name":
            binding = scope.get(token.text)
            if binding is None or not binding.initialized:
                raise ScriptError(token, f"未宣言または未初期化の変数です: {token.text}")
            return binding.dtype
        if node.kind == "array":
            element = expected[:-2] if expected is not None and expected.endswith("[]") else None
            if not node.args and element is None:
                raise ScriptError(token, "空の配列には代入先などの型指定が必要です。")
            for arg in node.args:
                dtype = self.expression(arg, scope)
                if element is None:
                    element = dtype
                if dtype != element or dtype in {"void"} or dtype.endswith("[]"):
                    raise ScriptError(arg.token, "配列の要素型が一致しません。")
            return f"{element}[]"
        if node.kind == "call":
            if token.text in READ_FUNCTIONS:
                count = 2 if token.text == "table_row_get" else 1
                if len(node.args) != count:
                    raise ScriptError(token, f"{token.text}の引数は{count}個必要です。")
                self.require(node.args[0], scope, "string")
                if token.text == "table_row_get":
                    self.require(node.args[1], scope, "int")
                types = READ_FUNCTIONS[token.text]
                if len(types) == 1:
                    dtype = types[0]
                else:
                    if expected is None or expected not in types:
                        raise ScriptError(token, "spin_getの値はintまたはfloat型で受け取ってください。")
                    dtype = expected
                self.read_types[token] = dtype
                return dtype
            if token.text in SCREEN_FUNCTIONS:
                if token.text != "click" and len(node.args) != 2:
                    raise ScriptError(token, f"{token.text}には対象IDと値が必要です。")
                if token.text == "click" and len(node.args) not in {1, 2}:
                    raise ScriptError(token, "clickにはボタンIDと任意の行のキーが必要です。")
                self.require(node.args[0], scope, "string")
                if token.text in {"spin_set", "spin_add", "spin_sub"}:
                    if self.expression(node.args[1], scope) not in {"int", "float"}:
                        raise ScriptError(node.args[1].token, "スピンボックスの値には数値が必要です。")
                elif len(node.args) == 2:
                    self.require(node.args[1], scope, "string")
                return "void"
            function = self.functions.get(token.text)
            if function is None:
                raise ScriptError(token, f"未定義の関数です: {token.text}")
            if len(node.args) != len(function.parameters):
                raise ScriptError(token, "引数の数が一致しません。")
            for arg, (_, dtype) in zip(node.args, function.parameters):
                self.require(arg, scope, dtype)
            return function.dtype
        if node.kind == "index":
            dtype = self.expression(node.args[0], scope)
            self.require(node.args[1], scope, "int")
            if not dtype.endswith("[]"):
                raise ScriptError(token, "添字は配列にのみ使えます。")
            return dtype[:-2]
        left = self.expression(node.args[0], scope)
        if node.kind == "unary":
            if token.text == "!" and left == "bool":
                return "bool"
            if token.text in {"+", "-"} and left in {"int", "float"}:
                return left
            raise ScriptError(token, "単項演算子と型が一致しません。")
        right = self.expression(node.args[1], scope)
        operator = token.text
        if operator in {"&&", "||"} and left == right == "bool":
            return "bool"
        if operator in {"==", "!="} and left == right and left != "void":
            return "bool"
        if operator in {"<", "<=", ">", ">="} and left == right and left in {"int", "float", "string"}:
            return "bool"
        if operator == "+" and left == right == "string":
            return "string"
        if operator in {"+", "-", "*", "/", "%"} and left == right and left in {"int", "float"}:
            return "float" if operator == "/" else left
        raise ScriptError(token, f"演算子 '{operator}' に対する型が不正です: {left}, {right}")

    def require(self, node: Expression, scope: dict[str, Binding], expected: str) -> None:
        actual = self.expression(node, scope, expected)
        if actual != expected:
            raise ScriptError(node.token, f"型が一致しません: {expected} が必要ですが {actual} です。")

    def block(self, body: tuple[Statement, ...], scope: dict[str, Binding], result: str | None = None,
              loop: bool = False, *, top: bool = False) -> bool:
        returns = False
        for node in body:
            expression = node.expression
            if node.kind == "function":
                if not top:
                    raise ScriptError(node.token, "関数はファイル直下に定義してください。")
                local: dict[str, Binding] = {}
                for name, dtype in node.parameters:
                    if name in local:
                        raise ScriptError(node.token, f"引数名が重複しています: {name}")
                    local[name] = Binding(dtype, True)
                guaranteed = self.block(node.body, local, node.dtype)
                if node.dtype != "void" and not guaranteed:
                    raise ScriptError(node.token, "すべての経路で戻り値を返す必要があります。")
            elif node.kind in {"declare", "assign"}:
                if node.kind == "declare":
                    if node.name in scope:
                        raise ScriptError(node.token, f"変数が重複しています: {node.name}")
                    scope[node.name] = Binding(node.dtype, False)
                binding = scope.get(node.name)
                if binding is None:
                    raise ScriptError(node.token, f"変数の型宣言が必要です: {node.name}")
                if expression is not None:
                    self.require(expression, scope, binding.dtype)
                    binding.initialized = True
            elif node.kind == "if" and expression is not None:
                self.require(expression, scope, "bool")
                yes, no = copy_bindings(scope), copy_bindings(scope)
                yes_returns = self.block(node.body, yes, result, loop)
                no_returns = self.block(node.other, no, result, loop)
                for name, binding in scope.items():
                    binding.initialized = yes[name].initialized and no[name].initialized
                returns = returns or (yes_returns and no_returns)
            elif node.kind == "for" and expression is not None:
                self.require(expression, scope, node.dtype + "[]")
                local = copy_bindings(scope)
                if node.name in local:
                    raise ScriptError(node.token, f"変数が重複しています: {node.name}")
                local[node.name] = Binding(node.dtype, True)
                self.block(node.body, local, result, True)
            elif node.kind == "return":
                if result is None:
                    raise ScriptError(node.token, "returnは関数内でのみ使えます。")
                if expression is None:
                    if result != "void":
                        raise ScriptError(node.token, "戻り値が必要です。")
                else:
                    if result == "void":
                        raise ScriptError(node.token, "void関数は値を返せません。")
                    self.require(expression, scope, result)
                returns = True
            elif node.kind in {"break", "continue"}:
                if not loop:
                    raise ScriptError(node.token, "ループ内でのみ使えます。")
            elif expression is not None:
                if expression.kind != "call":
                    raise ScriptError(node.token, "文として使える式は関数呼び出しのみです。")
                self.expression(expression, scope)
        return returns


@dataclass(frozen=True)
class Step:
    token: Token
    target: str | None = None
    code: str | None = None
    value: int | float | None = None
    column: int | None = None


@dataclass
class Scope:
    values: dict[str, Value] = field(default_factory=dict)
    parent: Scope | None = None

    def owner(self, name: str) -> Scope:
        if name in self.values:
            return self
        if self.parent is not None:
            return self.parent.owner(name)
        raise RuntimeError(f"未定義の変数: {name}")


class Flow(Exception):
    def __init__(self, kind: str, value: Value = None) -> None:
        self.kind = kind
        self.value = value


class Script:
    def __init__(self, source: str) -> None:
        try:
            self.program = Parser(source).parse()
            checker = Checker(self.program)
            checker.block(self.program, {}, top=True)
        except RecursionError as exc:
            raise ScriptError(Token("", 1, 1), "式またはブロックの入れ子が深すぎます。") from exc
        self.functions = checker.functions
        self.read_types = checker.read_types
        self.depth = 0

    def steps(self) -> Generator[Step, ReadValue, None]:
        yield from self.block(self.program, Scope())

    def block(self, body: tuple[Statement, ...], scope: Scope) -> Generator[Step, ReadValue, None]:
        for node in body:
            yield Step(node.token)
            expression = node.expression
            if node.kind == "declare":
                scope.values[node.name] = (yield from self.evaluate(expression, scope)) if expression is not None else None
            elif node.kind == "assign" and expression is not None:
                scope.owner(node.name).values[node.name] = yield from self.evaluate(expression, scope)
            elif node.kind == "if" and expression is not None:
                condition = yield from self.evaluate(expression, scope)
                yield from self.block(node.body if condition else node.other, Scope(parent=scope))
            elif node.kind == "for" and expression is not None:
                values = yield from self.evaluate(expression, scope)
                if not isinstance(values, list):
                    raise ScriptError(node.token, "配列が必要です。")
                for value in values:
                    try:
                        yield from self.block(node.body, Scope({node.name: value}, scope))
                    except Flow as flow:
                        if flow.kind == "break":
                            break
                        if flow.kind != "continue":
                            raise
            elif node.kind in {"break", "continue", "return"}:
                value = (yield from self.evaluate(expression, scope)) if expression is not None else None
                raise Flow(node.kind, value)
            elif node.kind == "expression" and expression is not None:
                yield from self.evaluate(expression, scope)

    def evaluate(self, node: Expression, scope: Scope) -> Generator[Step, ReadValue, Value]:
        yield Step(node.token)
        if node.kind == "literal":
            return literal(node)
        if node.kind == "name":
            return scope.owner(node.token.text).values[node.token.text]
        if node.kind == "array":
            values: list[Value] = []
            for arg in node.args:
                values.append((yield from self.evaluate(arg, scope)))
            return values
        if node.kind == "call":
            args: list[Value] = []
            for arg in node.args:
                args.append((yield from self.evaluate(arg, scope)))
            if node.token.text in SCREEN_FUNCTIONS:
                target = args[0]
                if not isinstance(target, str):
                    raise ScriptError(node.token, "画面操作には文字列が必要です。")
                if node.token.text in READ_FUNCTIONS:
                    column = None
                    if node.token.text == "table_row_get":
                        column = args[1]
                        if isinstance(column, bool) or not isinstance(column, int) or column < 0:
                            raise ScriptError(node.token, "列番号には0以上の整数が必要です。")
                    result = yield Step(node.token, target, column=column)
                    expected = self.read_types[node.token]
                    actual = {str: "string", int: "int", float: "float", bool: "bool"}.get(type(result), "void")
                    if actual != expected:
                        raise ScriptError(node.token, f"型が一致しません: {expected} が必要ですが {actual} です。")
                    return result
                if node.token.text in {"spin_set", "spin_add", "spin_sub"}:
                    value = args[1]
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ScriptError(node.token, "スピンボックスの値には数値が必要です。")
                    yield Step(node.token, target, value=value)
                else:
                    code = args[1] if len(args) == 2 else None
                    if code is not None and not isinstance(code, str):
                        raise ScriptError(node.token, "画面操作には文字列が必要です。")
                    yield Step(node.token, target, code)
                return None
            self.depth += 1
            try:
                if self.depth > 64:
                    raise ScriptError(node.token, "関数の呼び出しが深すぎます（上限64）。")
                function = self.functions[node.token.text]
                local = Scope({name: value for (name, _), value in zip(function.parameters, args)})
                try:
                    yield from self.block(function.body, local)
                except Flow as flow:
                    if flow.kind != "return":
                        raise
                    return flow.value
                return None
            except ScriptError as exc:
                raise ScriptError(node.token, f"関数 {node.token.text} 内: {exc}") from exc
            finally:
                self.depth -= 1
        left = yield from self.evaluate(node.args[0], scope)
        operator = node.token.text
        if node.kind == "index":
            index = yield from self.evaluate(node.args[1], scope)
            if not isinstance(left, list) or type(index) is not int:
                raise ScriptError(node.token, "配列と整数の添字が必要です。")
            if not 0 <= index < len(left):
                raise ScriptError(node.token, "配列の添字が範囲外です。")
            return left[index]
        if node.kind == "unary":
            if operator == "!" and type(left) is bool:
                return not left
            if type(left) not in {int, float} or not isinstance(left, (int, float)):
                raise ScriptError(node.token, "数値が必要です。")
            return -left if operator == "-" else left
        if operator == "&&" and left is False:
            return False
        if operator == "||" and left is True:
            return True
        right = yield from self.evaluate(node.args[1], scope)
        if operator in {"&&", "||"}:
            return right
        if operator == "==":
            return left == right
        if operator == "!=":
            return left != right
        if isinstance(left, str) and isinstance(right, str):
            if operator == "+":
                return left + right
            return self.compare(operator, left, right)
        if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
            raise ScriptError(node.token, "数値が必要です。")
        if operator in {"<", "<=", ">", ">="}:
            return self.compare(operator, left, right)
        if operator in {"/", "%"} and right == 0:
            raise ScriptError(node.token, "ゼロでは除算できません。")
        try:
            if operator == "+":
                value = left + right
            elif operator == "-":
                value = left - right
            elif operator == "*":
                value = left * right
            elif operator == "/":
                value = left / right
            else:
                value = left % right
            if isinstance(value, float) and not math.isfinite(value):
                raise ScriptError(node.token, "演算結果が有限の数値ではありません。")
            return value
        except (OverflowError, ValueError) as exc:
            raise ScriptError(node.token, f"数値演算に失敗しました: {exc}") from exc

    @staticmethod
    def compare(operator: str, left: str | int | float, right: str | int | float) -> bool:
        if isinstance(left, str) and isinstance(right, str):
            a, b = left, right
            return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[operator]
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[operator]
        raise ValueError("比較する型が一致しません。")
