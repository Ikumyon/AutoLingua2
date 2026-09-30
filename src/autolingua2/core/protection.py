from __future__ import annotations

import re


PROTECTED_RE = re.compile(
    r"\$[^$\r\n]+\$|\[[^\]\r\n]+\]|£[^£\s]+£|§(?:!|[A-Za-z0-9])|\\n"
)
PLACEHOLDER_RE = re.compile(r"__AL_TOKEN_\d{3}__")
SENTENCE_BREAK_RE = re.compile(r"(?<=[.!?。！？])([ \t]+)")


def protect_text(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []

    def replace(match: re.Match[str]) -> str:
        marker = f"__AL_TOKEN_{len(tokens):03d}__"
        tokens.append(match.group())
        return marker

    return PROTECTED_RE.sub(replace, text), tokens


def restore_text(text: str, tokens: list[str]) -> str:
    expected = [f"__AL_TOKEN_{index:03d}__" for index in range(len(tokens))]
    if PLACEHOLDER_RE.findall(text) != expected:
        raise ValueError("保護したParadox構文が変更されました")
    for marker, token in zip(expected, tokens):
        text = text.replace(marker, token, 1)
    return text


def sentence_parts(text: str) -> list[str]:
    """Return alternating translatable spans and whitespace separators."""
    parts = SENTENCE_BREAK_RE.split(text)
    return parts if parts else [text]
