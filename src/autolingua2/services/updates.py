"""Both automatic and manual checks use the native update entry point."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class UpdateStatus:
    state: Literal["unavailable"]
    message: str


def check_for_updates() -> UpdateStatus:
    from autolingua2_native import bootstrap
    state, message = bootstrap.update_status()
    return UpdateStatus(state, message)
