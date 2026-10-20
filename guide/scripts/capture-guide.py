"""Open real application windows, then photograph them through CaptureTool MCP.

This script does not use Computer Use, inject mouse input, or alter image pixels.
Each stage runs with disposable application settings, never the user's settings.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from capture_scenes import ADDITIONAL_SCENES
from capture_images import CAPTURE_PATHS, store_webp


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "guide/public/images"
SCENES = CAPTURE_PATHS
OVERLAYS = ("Codex Computer Use Cursor Overlay", "ChatGPT is using your computer")


def stage(scene: str) -> int:
    # Set these before importing application modules, which retain DATA_DIR values.
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "build/native")]
    with tempfile.TemporaryDirectory(prefix="autolingua-guide-capture-") as directory:
        os.environ["AUTOLINGUA_SETTINGS_PATH"] = str(Path(directory) / "settings.json")
        for key in list(os.environ):
            if key.startswith("AUTOLINGUA_") and key != "AUTOLINGUA_SETTINGS_PATH":
                del os.environ[key]
        from autolingua2.infrastructure import filesystem

        filesystem.DATA_DIR = Path(directory)
        filesystem.LIBRARY_DIR = Path(directory) / "library"

        from PySide6.QtCore import QEvent, QObject, QTimer, Qt
        from PySide6.QtWidgets import QApplication, QTabWidget
        from autolingua2.extensions import ExtensionEntrance
        from autolingua2.services.settings.settings_store import load_theme_settings
        from autolingua2.ui.main.main_window import MainWindowController
        from autolingua2.ui.dialogs.settings import SettingsDialogController

        app = QApplication([sys.argv[0]])
        app.setApplicationName("Autolingua Desktop")
        app.setOrganizationName("AutoLinguaGuideCapture")
        app.setQuitOnLastWindowClosed(False)
        entrance = ExtensionEntrance()
        entrance.load_all(ROOT, ui_language="ja")
        if entrance.errors:
            raise RuntimeError("Application extensions failed: " + "; ".join(entrance.errors))
        entrance.localization.apply_language(app, "ja")
        theme, icons = load_theme_settings()
        entrance.themes.apply_theme(theme, app)
        entrance.icons.set_current_iconset(icons)
        app.setWindowIcon(entrance.icons.load_icon(ROOT / "assets/images/app.ico"))
        controller = MainWindowController(entrance)
        controller.source_watch_timer.stop()
        settings = None
        staged_objects = []

        # Actual controllers populate .ui files; no replacement UI is constructed.
        if scene in ADDITIONAL_SCENES:
            from capture_scenes import prepare
            target, settings, staged_objects = prepare(scene, controller, entrance, ROOT)
        elif scene == "project-start":
            target = controller.window
            language = controller.combo_source_language.findData("en")
            if language < 0:
                raise RuntimeError("English source language was not found")
            controller.combo_source_language.setCurrentIndex(language)
            target.resize(1280, 800)
        elif scene == "source-watch":
            settings = SettingsDialogController(entrance)
            if not settings.select_category("source_watch"):
                raise RuntimeError("Source watch settings category was not found")
            target = settings.dialog
            target.resize(1000, 740)
        else:
            target = controller.automation_dialog.dialog
            tabs = target.findChild(QTabWidget, "automationTabs")
            if tabs is None:
                raise RuntimeError("Automation tabs were not found")
            tabs.setCurrentIndex(1 if scene == "automation-triggers" else 0)
            target.resize(1000, 760)

        screen = target.screen().availableGeometry()
        target.resize(min(target.width(), screen.width() - 32),
                      min(target.height(), screen.height() - 64))
        target.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        target.show()
        frame = target.frameGeometry()
        target.move(screen.x() + (screen.width() - frame.width()) // 2,
                    screen.y() + (screen.height() - frame.height()) // 2)
        target.raise_()
        target.activateWindow()
        stopped = threading.Event()

        def listen() -> None:
            sys.stdin.readline()
            stopped.set()

        threading.Thread(target=listen, daemon=True).start()
        poll = QTimer()
        poll.timeout.connect(lambda: app.quit() if stopped.is_set() else None)
        poll.start(100)

        def ready() -> None:
            if not target.isVisible() or not screen.contains(target.frameGeometry()):
                print(json.dumps({"error": "Capture target is hidden or outside the screen"}), flush=True)
                app.exit(1)
                return
            print(json.dumps({"ready": scene, "window_id": str(int(target.winId())),
                              "process_id": os.getpid(), "title": target.windowTitle()}, ensure_ascii=True), flush=True)

        QTimer.singleShot(3500, ready)
        try:
            return app.exec()
        finally:
            controller.dock_ai_settings.visibilityChanged.disconnect(controller._on_dock_ai_visibility_changed)
            # Remove the host filter before Qt tears down its table widgets.
            for watched in [controller.window, *controller.window.findChildren(QObject)]:
                watched.removeEventFilter(controller)
            controller.source_watch_timer.stop()
            controller.automation_triggers.shutdown()
            controller.automation_dialog.shutdown()
            controller.chat_dock.close()
            controller.mcp_server.close()
            controller.mcp_client.close()
            if settings is not None:
                settings.mcp_page.tester.close()
                settings.watch_page.timer.stop()
                settings.dialog.deleteLater()
            entrance.close()
            controller.window.deleteLater()
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def json_result(result):
    if result.isError:
        raise RuntimeError("MCP error: " + "; ".join(
            item.text for item in result.content if item.type == "text"))
    return json.loads(next(item.text for item in result.content if item.type == "text"))


async def photograph(args) -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    server = Path(args.capture_server).resolve(strict=True)
    app_python = Path(args.app_python).resolve(strict=True)
    params = StdioServerParameters(command=sys.executable,
        args=["-u", str(server), "--output-dir", str(OUTPUT)])
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            if not {"list_capture_targets", "capture_screen"} <= {tool.name for tool in tools.tools}:
                raise RuntimeError("Required CaptureTool MCP tools are not available")
            for scene in args.only or SCENES:
                process = await asyncio.create_subprocess_exec(
                    str(app_python), "-u", str(Path(__file__).resolve()), "--stage", scene,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    # Keep diagnostics visible and avoid filling an unread stderr pipe.
                    stderr=None, cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    async with asyncio.timeout(60):
                        while True:
                            line = await process.stdout.readline()
                            if not line:
                                raise RuntimeError(f"{scene}: capture window exited before ready")
                            try:
                                prepared = json.loads(line)
                            except (ValueError, UnicodeDecodeError):
                                continue
                            if isinstance(prepared, dict) and prepared.get("error"):
                                raise RuntimeError(f"{scene}: {prepared['error']}")
                            if isinstance(prepared, dict) and prepared.get("ready") == scene:
                                break
                    targets = json_result(await session.call_tool("list_capture_targets", {}))
                    if any(any(overlay in window["title"] for overlay in OVERLAYS)
                           for window in targets["windows"]):
                        raise RuntimeError("Computer Use overlay is still visible; end Computer Use before capture")
                    window = next((window for window in targets["windows"]
                                   if window["id"] == prepared["window_id"] and
                                   window["process_id"] == prepared["process_id"] and
                                   window["title"] == prepared["title"]), None)
                    if window is None:
                        raise RuntimeError(f"{scene}: the prepared window was not returned by MCP")
                    bounds, desktop = window["bounds"], targets["desktop"]
                    if (bounds["x"] < desktop["x"] or bounds["y"] < desktop["y"] or
                        bounds["x"] + bounds["width"] > desktop["x"] + desktop["width"] or
                        bounds["y"] + bounds["height"] > desktop["y"] + desktop["height"]):
                        raise RuntimeError(f"{scene}: the window would be clipped")
                    metadata = json_result(await session.call_tool("capture_screen", {
                        "target": "window", "target_id": window["id"],
                        "include_cursor": False, "delay_seconds": 1,
                    }))
                    if metadata["target"]["process_id"] != prepared["process_id"] or metadata["include_cursor"]:
                        raise RuntimeError("MCP returned an unexpected capture target")
                    saved = Path(metadata["path"]).resolve(strict=True)
                    if saved.parent != OUTPUT.resolve() or saved.suffix != ".png":
                        raise RuntimeError("MCP returned an unexpected output path")
                    destination = OUTPUT / SCENES[scene]
                    store_webp(saved, destination)
                    print(json.dumps({"scene": scene, "path": str(destination),
                                      "width": metadata["width"], "height": metadata["height"]},
                                     ensure_ascii=True), flush=True)
                finally:
                    if process.returncode is None:
                        try:
                            process.stdin.write(b"quit\n")
                            await process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError):
                            pass
                        try:
                            await asyncio.wait_for(process.wait(), 10)
                        except TimeoutError:
                            process.terminate()
                            await process.wait()
                    if process.returncode:
                        raise RuntimeError(f"{scene}: capture window exited with code {process.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-server", help="CaptureTool src/mcp_server.py")
    parser.add_argument("--app-python", default=str(ROOT / ".venv/Scripts/python.exe"))
    parser.add_argument("--only", choices=SCENES, nargs="+")
    parser.add_argument("--stage", choices=SCENES, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("CaptureTool MCP requires Windows")
    if args.stage:
        return stage(args.stage)
    if not args.capture_server:
        parser.error("--capture-server is required")
    asyncio.run(photograph(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
