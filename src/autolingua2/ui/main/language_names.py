from __future__ import annotations

from autolingua2.services.projects.workspaces import WorkspaceService
from autolingua2.ui.resources.i18n import tr


def workspace_language_name(service: WorkspaceService, code: str) -> str:
    language = service.languages.get(code)
    if language is None:
        return code
    if code in service.custom_languages:
        return language.name
    translated = tr("LanguageNames", code)
    return language.name if translated == code else translated
