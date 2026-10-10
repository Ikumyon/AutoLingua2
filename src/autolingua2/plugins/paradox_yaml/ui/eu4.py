"""Game palettes and EU4 display syntax, owned exclusively by the Paradox plugin."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from autolingua2.plugins.api import GameTextPresentation, NewlineCodec, PluginContext
from autolingua2.plugins.contracts import GameProfile
from .translations import tr

GAME_ID = "eu4"
PAGE_ID = "paradox_yaml_colors"
DEFAULT_COLORS = {
    "W": "#ffffff", "B": "#0000ff", "G": "#00ff00", "R": "#ff3232",
    "b": "#000000", "g": "#b0b0b0", "Y": "#ffbd00", "M": "#23ceff",
    "T": "#00ffef", "O": "#ffa000", "l": "#9ac14b", "J": "#00a86b",
    "P": "#702963", "V": "#fab6ff",
}
BADGES = (
    (re.compile(r"\[[^\]]+\]"), "#f43f5e"),
    (re.compile(r"\$[^$\s]+\$"), "#38bdf8"),
    (re.compile(r"£[^£\s]+£"), "#fbbf24"),
    (re.compile(r"§[a-zA-Z0-9!]"), "#e2e8f0"),
)


def expand_newlines(text: str) -> str:
    return text.replace(r"\n", "\n")


def collapse_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", r"\n")


def presentation(game_id: str) -> GameTextPresentation | None:
    if game_id != GAME_ID:
        return None
    return GameTextPresentation(
        newline_codec=NewlineCodec(expand_newlines, collapse_newlines),
        highlight_tags=True, apply_colors=True, settings_page_id=PAGE_ID,
        settings_label=tr("ParadoxPlugin", "EU4の配色設定…"),
    )


class ParadoxPalette:
    """Game-specific cached palettes; rendering performs no file I/O."""

    def __init__(self, context: PluginContext, games: Sequence[GameProfile]) -> None:
        self.context = context
        self.games = tuple(games)
        settings = context.settings.load()
        saved_games = settings.get("games")
        self._colors: dict[str, dict[str, str]] = {}
        for profile in self.games:
            game = saved_games.get(profile.id) if isinstance(saved_games, dict) else None
            saved = game.get("color_tags") if isinstance(game, dict) else None
            self._colors[profile.id] = (
                self._validate(saved) if isinstance(saved, dict) else self.default_colors(profile.id)
            )

    @staticmethod
    def default_colors(game_id: str) -> dict[str, str]:
        return dict(DEFAULT_COLORS) if game_id == GAME_ID else {}

    def colors_for_game(self, game_id: str) -> Mapping[str, str]:
        return self._colors[game_id]

    @staticmethod
    def _validate(value: dict[object, object]) -> dict[str, str]:
        return {key: color.lower() for key, color in value.items()
                if isinstance(key, str) and re.fullmatch(r"[a-zA-Z0-9]", key)
                and isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color)}

    def save(self, colors_by_game: dict[str, dict[str, str]]) -> None:
        if not colors_by_game:
            return
        if not colors_by_game.keys() <= self._colors.keys():
            raise ValueError("Unknown Paradox game palette")
        settings = self.context.settings.load()
        saved_games = settings.get("games")
        games = dict(saved_games) if isinstance(saved_games, dict) else {}
        for game_id, colors in colors_by_game.items():
            saved_game = games.get(game_id)
            game = dict(saved_game) if isinstance(saved_game, dict) else {}
            game["color_tags"] = dict(colors)
            games[game_id] = game
        settings["games"] = games
        self.context.settings.save(settings)
        self._colors.update({game_id: dict(colors) for game_id, colors in colors_by_game.items()})
        self.context.notify_display_changed()

    def create_highlighter(
        self, game_id: str, document: QTextDocument,
        highlight_tags: Callable[[], bool], apply_colors: Callable[[], bool],
    ) -> QSyntaxHighlighter | None:
        if game_id != GAME_ID:
            return None
        return Eu4Highlighter(document, self, highlight_tags, apply_colors)


class Eu4Highlighter(QSyntaxHighlighter):
    """EU4 closes one color scope with §! (confirmed by the project owner).

    Block state interns the entire stack so edits propagate across blank lines.
    Qt formatting offsets are UTF-16 units, unlike Python regex offsets.
    """

    def __init__(self, document: QTextDocument, palette: ParadoxPalette,
                 highlight_tags: Callable[[], bool], apply_colors: Callable[[], bool]) -> None:
        super().__init__(document)
        self._palette = palette
        self._highlight_tags = highlight_tags
        self._apply_colors = apply_colors
        self._states: list[tuple[str, ...]] = [()]
        self._state_ids: dict[tuple[str, ...], int] = {(): 0}

    def highlightBlock(self, text: str) -> None:
        colors = self._palette.colors_for_game(GAME_ID)
        offsets = [0]
        for char in text:
            offsets.append(offsets[-1] + (2 if ord(char) > 0xFFFF else 1))

        def paint(start: int, end: int, color: str, badge: bool = False) -> None:
            if start >= end:
                return
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if badge:
                background = QColor(color)
                background.setAlpha(55)
                fmt.setBackground(background)
                fmt.setFontWeight(QFont.Weight.Medium)
            self.setFormat(offsets[start], offsets[end] - offsets[start], fmt)

        previous = self.previousBlockState()
        stack = list(self._states[previous]) if 0 <= previous < len(self._states) else []
        start = 0
        for match in re.finditer(r"§([a-zA-Z0-9!])", text):
            if stack and self._apply_colors():
                paint(start, match.start(), colors[stack[-1]])
            code = match.group(1)
            if code == "!":
                if stack:
                    stack.pop()
            elif code in colors:
                stack.append(code)
            start = match.end()
        if stack and self._apply_colors():
            paint(start, len(text), colors[stack[-1]])
        state = tuple(stack)
        state_id = self._state_ids.get(state)
        if state_id is None:
            state_id = len(self._states)
            self._states.append(state)
            self._state_ids[state] = state_id
        self.setCurrentBlockState(state_id)
        if self._highlight_tags():
            for pattern, color in BADGES:
                for match in pattern.finditer(text):
                    paint(match.start(), match.end(), color, True)
