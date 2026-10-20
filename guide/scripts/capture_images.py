"""Store CaptureTool PNG captures as pixel-identical lossless WebP images."""
from pathlib import Path

from PIL import Image


CAPTURE_PATHS = {
    "project-start": "first-translation/project-start.webp",
    "source-watch": "projects/source-watch.webp",
    "script-editor": "automation/script-editor.webp",
    "automation-triggers": "automation/triggers.webp",
    "translation-overview": "translation/overview.webp",
    "search-filter": "translation/search-filter.webp",
    "ai-chat": "ai-chat/conversation.webp",
    "ai-settings": "settings/ai-models.webp",
    "conditional-tone": "glossary-tone/conditional-tone.webp",
    "model-comparison": "translation/model-comparison.webp",
    "glossary-inheritance": "glossary-tone/glossary-inheritance.webp",
    "source-diff": "projects/source-diff.webp",
    "thumbnail-edit": "projects/thumbnail-edit.webp",
    "chat-apply": "ai-chat/apply-changes.webp",
    "mcp-settings": "automation/mcp-settings.webp",
    "update-status": "support/update-error.webp",
}


def store_webp(source: Path, destination: Path, *, remove_source: bool = True) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        pixels = original.convert("RGBA")
        pixels.save(destination, format="WEBP", lossless=True, exact=True, method=6)
        with Image.open(destination) as saved:
            if saved.size != pixels.size or saved.convert("RGBA").tobytes() != pixels.tobytes():
                raise RuntimeError(f"WebP pixel verification failed: {destination}")
    if remove_source:
        source.unlink()
    return destination
