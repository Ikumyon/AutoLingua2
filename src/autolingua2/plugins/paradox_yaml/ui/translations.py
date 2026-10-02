"""Translation format and resources are owned solely by the Paradox plugin."""
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTranslator


def tr(context: str, message: str) -> str:
    return QCoreApplication.translate(context, message)


class PluginTranslations:
    def __init__(self) -> None:
        self._translator: QTranslator | None = None

    def close(self) -> None:
        translator = self._translator
        self._translator = None
        if translator is not None:
            QCoreApplication.removeTranslator(translator)
            translator.deleteLater()

    def change_language(self, language: str) -> None:
        self.close()
        folder = Path(__file__).resolve().parents[1] / "translations"
        for code in dict.fromkeys((language, language.split("_")[0])):
            if not code or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in code):
                raise ValueError("Invalid plugin language code")
            path = folder / f"{code}.qm"
            if not path.is_file():
                continue
            translator = QTranslator()
            if not translator.load(str(path)):
                translator.deleteLater()
                raise ValueError(f"Cannot load Paradox translation: {path}")
            if not QCoreApplication.installTranslator(translator):
                translator.deleteLater()
                raise RuntimeError("Cannot install Paradox translation")
            self._translator = translator
            break
