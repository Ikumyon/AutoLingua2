from __future__ import annotations

import logging
import os
import sys


def main() -> int:
    from .infrastructure import bootstrap
    from .infrastructure.logging import configure_logging, connect_console_logging, install_exception_hooks
    from .infrastructure.platform import current_platform

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
        from .adapters.registry import get_all_adapters
        from .services.settings_store import load_ui_language, load_theme_settings
        from .ui.i18n import install_ui_translator
        from .ui.main_window import MainWindowController
        from .ui.theme import ThemeManager

        startup.phase("plugins", "プラグインを読み込んでいます…")
        from concurrent.futures import ThreadPoolExecutor, wait
        with ThreadPoolExecutor(max_workers=1) as pool:
            discovery = pool.submit(get_all_adapters)
            while not wait([discovery], timeout=0.1).done:
                startup.check()
            discovery.result()
        startup.check()
        startup.phase("settings", "設定・翻訳・テーマを適用しています…")
        app = QApplication(sys.argv)
        app.setApplicationName("AUTOlingua")
        app.setOrganizationName("AUTOlingua")
        install_ui_translator(app, load_ui_language())
        theme, _ = load_theme_settings()
        ThemeManager().apply_theme(theme, app)
        startup.phase("window", "メイン画面を構築しています…")
        window = MainWindowController(platform_driver=current_platform)
        window.show()
        is_ready = False

        def ready() -> None:
            nonlocal is_ready
            try:
                startup.ready()
                is_ready = True
            except Exception:
                logging.getLogger(__name__).exception("Ready handshake failed")
                app.exit(1)

        def control_tick() -> None:
            try:
                startup.check()
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
            QMessageBox.critical(None, "AUTOlingua2 起動エラー", str(exc))
        return 1
    finally:
        bootstrap.close()
