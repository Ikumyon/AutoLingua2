from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .extensions import ExtensionEntrance


def main() -> int:
    from .infrastructure import bootstrap
    from .infrastructure.logging import configure_logging, connect_console_logging, install_exception_hooks
    from .infrastructure.platform import current_platform

    entrance: ExtensionEntrance | None = None
    internal_launch = "AUTOLINGUA_BOOT_TOKEN" in os.environ
    try:
        if not bootstrap.enter():
            return 0
        startup = bootstrap.session()
        startup.phase("diagnostics", "診断を準備しています…")
        configure_logging()
        install_exception_hooks()
        debug_error = ""
        if "--debug" in sys.argv:
            result = current_platform.allocate_debug_console()
            if result.state == "unavailable":
                debug_error = result.error or "デバッグコンソールを利用できません。"
            else:
                connect_console_logging()

        startup.phase("modules", "モジュールを読み込んでいます…")
        from PySide6.QtWidgets import QApplication, QMessageBox
        from PySide6.QtCore import QTimer
        from .extensions import ExtensionEntrance
        from .services.settings_store import load_ui_language, load_theme_settings
        from .ui.main_window import MainWindowController

        startup.check()
        current_platform.configure_desktop_integration("autolingua.desktop.app")
        app = QApplication(sys.argv)
        app.setApplicationName("Autolingua Desktop")
        app.setOrganizationName("AutoLingua")
        app.setDesktopFileName("autolingua-desktop")
        from PySide6.QtGui import QIcon
        from .infrastructure.filesystem import ASSETS_DIR, PROJECT_ROOT
        app_icon_path = ASSETS_DIR / "images" / "app.ico"
        if app_icon_path.exists():
            app.setWindowIcon(QIcon(str(app_icon_path)))
        entrance = ExtensionEntrance()
        startup.phase("plugins", "拡張を読み込んでいます…")
        ui_language = load_ui_language()
        entrance.load_all(PROJECT_ROOT, startup.check, ui_language=ui_language)
        startup.check()
        startup.phase("settings", "設定・翻訳・テーマを適用しています…")
        entrance.localization.apply_language(app, ui_language)
        theme, icons = load_theme_settings()
        entrance.themes.apply_theme(theme, app)
        entrance.icons.set_current_iconset(icons)
        startup.check()
        startup.phase("window", "メイン画面を構築しています…")
        window = MainWindowController(entrance, platform_driver=current_platform)
        window.show()
        is_ready = False
        notification_project: str | None = None
        for index, argument in enumerate(sys.argv[1:], start=1):
            if argument == "--source-update" and index + 1 < len(sys.argv):
                notification_project = sys.argv[index + 1]
                break

        def ready() -> None:
            nonlocal is_ready
            try:
                startup.ready()
                is_ready = True
                if notification_project is not None:
                    window.request_source_update(notification_project)
            except Exception:
                logging.getLogger(__name__).exception("Ready handshake failed")
                app.exit(1)

        def control_tick() -> None:
            try:
                startup.check()
                project = startup.take_source_update()
                if project is not None:
                    window.request_source_update(project)
                window.process_source_update_request()
                if startup.take_activation():
                    if window.window.isMinimized():
                        window.window.showNormal()
                    window.window.raise_()
                    window.window.activateWindow()
            except Exception:
                logging.getLogger(__name__).exception("Control endpoint failed")
                control_timer.stop()
                if not is_ready:
                    app.exit(1)

        control_timer = QTimer(app)
        control_timer.setInterval(100)
        control_timer.timeout.connect(control_tick)
        control_timer.start()
        QTimer.singleShot(0, ready)
        if debug_error:
            logging.getLogger(__name__).error("Debug console unavailable")
            QTimer.singleShot(0, lambda: QMessageBox.warning(
                window.window, "デバッグコンソール", debug_error + "\nログフォルダから診断を確認できます。"))
        return app.exec()
    except Exception as exc:
        if not internal_launch:
            configure_logging()
        logging.getLogger(__name__).exception("Application startup failed")
        try:
            bootstrap.session().failed(f"{type(exc).__name__}: {exc}"[:2000])
        except Exception:
            logging.getLogger(__name__).error("Startup failure could not be sent to launcher")
        if not internal_launch:
            from PySide6.QtWidgets import QApplication, QMessageBox
            error_app = QApplication.instance()
            if error_app is None:
                error_app = QApplication(sys.argv)
            QMessageBox.critical(None, "Autolingua Desktop 起動エラー", str(exc))
        return 1
    finally:
        if entrance is not None:
            entrance.close()
        bootstrap.close()
