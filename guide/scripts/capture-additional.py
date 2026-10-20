"""Capture the twelve additional guide scenes using CaptureTool's stdio MCP.

Prepare actual application screens interactively; never fabricate AI responses.
Run with the Python interpreter specified by --capture-python (the default).
"""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import os
from pathlib import Path
import sys

from capture_images import CAPTURE_PATHS, store_webp


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_PYTHON = Path(r"C:\Users\ikumy\AppData\Local\Programs\Python\Python314\python.exe")
CAPTURE_SERVER = Path(r"C:\localfile\開発\capture_tool\src\mcp_server.py")
SCENES = {
    "translation-overview": ("高", "翻訳画面の全体図", "ファイル一覧・翻訳一覧・編集欄を表示する。番号の追記はこのスクリプトでは行わない。"),
    "search-filter": ("高", "検索・フィルター", "検索語または状態フィルターを適用し、絞り込み条件と結果を表示する。"),
    "ai-chat": ("高", "AIチャット", "公開可能な質問・参照情報・実際の回答を表示する。"),
    "ai-settings": ("高", "AI接続・モデル設定", "接続先とモデルを表示する。APIキー等の秘密情報は画面に表示しない。"),
    "conditional-tone": ("高", "条件付き口調", "登録した条件と対応する口調が分かる画面を表示する。"),
    "model-comparison": ("中", "複数モデルの翻訳比較", "実際の比較結果と採用する操作を表示する。"),
    "glossary-inheritance": ("中", "用語集の継承", "親の用語集と継承先の関係が分かる設定を表示する。"),
    "source-diff": ("中", "原文更新後の差分", "追加・変更された原文を確認できる画面を表示する。"),
    "thumbnail-edit": ("中", "サムネイル加工", "加工対象と切り抜き・サイズ指定、プレビューを表示する。"),
    "chat-apply": ("中", "AIチャットの変更適用", "実際の変更提案と確認・適用する操作を表示する。"),
    "mcp-settings": ("低", "MCP接続", "公開可能な接続設定と接続状態を表示する。"),
    "update-status": ("低", "更新確認・エラー表示", "更新確認結果または実際のエラーと確認情報を表示する。"),
}
OVERLAYS = ("Codex Computer Use Cursor Overlay", "ChatGPT is using your computer")


def metadata(result):
    texts = [item.text for item in result.content if item.type == "text"]
    if result.isError:
        raise RuntimeError("CaptureTool MCP: " + "\n".join(texts))
    return json.loads(texts[0])


async def ask(message):
    return (await asyncio.to_thread(input, message)).strip()


def foreground(window):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
    user32.SetForegroundWindow.restype = ctypes.c_bool
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    hwnd = int(window["id"], 0)
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError("対象ウィンドウを前面にできませんでした。手動で前面に出して再実行してください。")


def check_targets(targets):
    if any(any(name in w["title"] for name in OVERLAYS) for w in targets["windows"]):
        raise RuntimeError("Computer Useの操作支援表示を終了してから撮影してください。")


def check_bounds(window, desktop):
    b = window["bounds"]
    if (b["x"] < desktop["x"] or b["y"] < desktop["y"] or
            b["x"] + b["width"] > desktop["x"] + desktop["width"] or
            b["y"] + b["height"] > desktop["y"] + desktop["height"]):
        raise RuntimeError("対象ウィンドウが画面外にはみ出しています。位置・サイズを調整してください。")


async def run(args):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    output = args.output_dir.resolve()
    params = StdioServerParameters(
        command=str(args.capture_python.resolve(strict=True)),
        args=[str(args.capture_server.resolve(strict=True)), "--output-dir", str(output)],
    )
    print("配色はデフォルトのまま、公開可能なデータで画面を準備してください。")
    print("Computer Useの操作支援表示を終了し、重なったウィンドウを退けてください。")
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            available = {tool.name for tool in (await session.list_tools()).tools}
            if not {"list_capture_targets", "capture_screen", "get_latest_capture"} <= available:
                raise RuntimeError("必要なCaptureTool MCPツールがありません。")
            for scene in args.only or SCENES:
                priority, title, preparation = SCENES[scene]
                print(f"\n[{priority}] {title} ({scene})\n{preparation}")
                ready = await ask("表示完了後Enter（s: スキップ / q: 終了）: ")
                if ready == "q":
                    return
                if ready == "s":
                    continue
                # List only after the operator has prepared the screen.
                targets = metadata(await session.call_tool("list_capture_targets", {}))
                check_targets(targets)
                windows = targets["windows"]
                for number, window in enumerate(windows, 1):
                    print(f"{number}: {window['title']} | PID={window['process_id']} | ID={window['id']}")
                choice = await ask("タイトル・PIDを確認して番号を入力（s: スキップ / q: 終了）: ")
                if choice == "q":
                    return
                if choice == "s":
                    continue
                if not choice.isdigit() or not 1 <= int(choice) <= len(windows):
                    raise ValueError("一覧にある番号を指定してください。")
                window = windows[int(choice) - 1]
                while True:
                    foreground(window)
                    await asyncio.sleep(1)
                    # Reconfirm the ID, title, PID and bounds after activation.
                    current = metadata(await session.call_tool("list_capture_targets", {}))
                    check_targets(current)
                    actual = next((w for w in current["windows"] if
                                   (w["id"], w["process_id"], w["title"]) ==
                                   (window["id"], window["process_id"], window["title"])), None)
                    if actual is None:
                        raise RuntimeError("対象ウィンドウが変わりました。画面を再選択してください。")
                    check_bounds(actual, current["desktop"])
                    captured = metadata(await session.call_tool("capture_screen", {
                        "target": "window", "target_id": actual["id"],
                        "include_cursor": False, "delay_seconds": 1,
                    }))
                    if (captured["target"]["process_id"] != actual["process_id"] or
                            captured["include_cursor"]):
                        raise RuntimeError("撮影結果の対象またはカーソル設定が一致しません。")
                    while True:
                        path = Path(captured["path"]).resolve()
                        if path.parent != output or path.suffix.lower() != ".png":
                            raise RuntimeError("想定外の保存先が返されました。")
                        destination = output / CAPTURE_PATHS[scene]
                        # Keep the source until review ends: get_latest_capture reads it.
                        if path.exists():
                            store_webp(path, destination, remove_source=False)
                        elif not destination.is_file():
                            raise RuntimeError("撮影画像が見つかりません。")
                        print(f"{scene}: {destination}")
                        os.startfile(str(destination))
                        review = await ask("対象・文字欠け・写り込みを確認（Enter: 採用 / r: 再撮影 / l: 直近画像を再取得 / q: 終了）: ")
                        if review == "l":
                            captured = metadata(await session.call_tool("get_latest_capture", {}))
                            continue
                        if review not in ("", "r", "q"):
                            continue
                        path.unlink(missing_ok=True)
                        break
                    if review == "q":
                        return
                    if review != "r":
                        break
                    await ask("画像ビューアを閉じ、対象画面を整えてEnter: ")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-python", type=Path, default=CAPTURE_PYTHON)
    parser.add_argument("--capture-server", type=Path, default=CAPTURE_SERVER)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "guide/public/images")
    parser.add_argument("--only", choices=SCENES, nargs="+")
    parser.add_argument("--list", action="store_true", help="撮影候補を一覧表示して終了")
    args = parser.parse_args()
    if args.list:
        for scene, (priority, title, preparation) in SCENES.items():
            print(f"[{priority}] {scene}: {title}\n  {preparation}")
        return
    if sys.platform != "win32":
        parser.error("CaptureTool MCP requires Windows")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
