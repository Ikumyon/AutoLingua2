from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Issue:
    message: str
    kind: str = "syntax"
