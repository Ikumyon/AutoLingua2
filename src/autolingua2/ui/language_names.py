from __future__ import annotations

from autolingua2.services.workspaces import WorkspaceService
from autolingua2.ui.i18n import tr


def workspace_language_name(service: WorkspaceService, code: str) -> str:
    language = service.languages[code]
    if code in service.custom_languages:
        return language.name
    translated = tr("LanguageNames", code)
    return language.name if translated == code else translated
