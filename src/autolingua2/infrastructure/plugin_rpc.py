from __future__ import annotations

import json
import logging
from pathlib import Path
from queue import Queue, Empty, Full
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from .operations import check_cancelled, report_progress
from .platform import current_platform
from .platform.base import PlatformDriver

logger = logging.getLogger(__name__)
MAX_LINE = 64 * 1024 * 1024


class PluginRPCError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class PluginRPC:
    def __init__(self, plugin_id: str, executable: Path, args: list[str], cwd: Path,
                 platform: PlatformDriver = current_platform):
        self.plugin_id = plugin_id
        self.executable, self.args, self.cwd = executable, args, cwd
        self.platform = platform

    def call(self, method: str, params: dict, timeout: float | None = None):
        check_cancelled()
        request_id = uuid4().hex
        request = json.dumps(dict(version=1, id=request_id, method=method, params=params),
                             ensure_ascii=False).encode("utf-8") + b"\n"
        if len(request) > MAX_LINE:
            raise PluginRPCError("size", "プラグインへの要求が大きすぎます。")
        deadline = monotonic() + (timeout if timeout is not None else (30 if method in {"register", "output_name"} else 600))
        process = self.platform.start_plugin(self.executable, self.args, self.cwd)
        stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
        queue: Queue = Queue(maxsize=32)
        stopping = Event()

        def deliver(value):
            while not stopping.is_set():
                try:
                    queue.put(value, timeout=0.05)
                    return
                except Full:
                    continue

        def read_stdout():
            try:
                while not stopping.is_set():
                    line = stdout.readline(MAX_LINE + 1)
                    if not line:
                        break
                    if len(line) > MAX_LINE or not line.endswith(b"\n"):
                        raise PluginRPCError("protocol", "応答行が不正または大きすぎます。")
                    deliver(json.loads(line.decode("utf-8")))
            except Exception:
                deliver(PluginRPCError("protocol", "プラグインのJSON応答が不正です。"))
            finally:
                deliver(None)

        def read_stderr():
            # Keep draining even when the plugin is very verbose; bounded chunks.
            while not stopping.is_set():
                chunk = stderr.readline(8192)
                if not chunk:
                    break
                logger.info("plugin=%s operation=%s stderr=%s", self.plugin_id, method,
                            chunk.decode("utf-8", errors="replace").rstrip())

        def write_stdin():
            try:
                stdin.write(request)
                stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                stdin.close()

        threads = [Thread(target=f, daemon=True) for f in (read_stdout, read_stderr, write_stdin)]
        for thread in threads:
            thread.start()
        final = None
        eof = False
        try:
            while True:
                check_cancelled()
                if monotonic() >= deadline:
                    raise PluginRPCError("timeout", f"{self.plugin_id}: {method} がタイムアウトしました。")
                try:
                    message = queue.get(timeout=0.05)
                except Empty:
                    message = ...
                if isinstance(message, Exception):
                    raise message
                if message is None:
                    eof = True
                elif message is not ...:
                    if not isinstance(message, dict) or message.get("version") != 1 or message.get("id") != request_id:
                        raise PluginRPCError("protocol", "応答のバージョンまたはIDが一致しません。")
                    if final is not None:
                        raise PluginRPCError("protocol", "最終応答後に追加の応答が届きました。")
                    if "progress" in message and not ({"result", "error"} & message.keys()):
                        if not isinstance(message["progress"], str):
                            raise PluginRPCError("protocol", "進捗通知が不正です。")
                        report_progress(message["progress"][:500])
                    elif ("result" in message) != ("error" in message):
                        final = message
                    else:
                        raise PluginRPCError("protocol", "最終応答が不正です。")
                code = process.poll()
                if eof and code is not None:
                    if code != 0:
                        raise PluginRPCError("exit", f"{self.plugin_id}: 異常終了 ({code})")
                    if final is None:
                        raise PluginRPCError("protocol", "最終応答がありません。")
                    if "error" in final:
                        error = final["error"]
                        if not isinstance(error, dict) or not all(isinstance(error.get(k), str) for k in ("code", "message", "traceback")):
                            raise PluginRPCError("protocol", "エラー応答が不正です。")
                        # Retain stack locations, not source code or embedded payloads.
                        stack = "\n".join(line for line in error["traceback"].splitlines()
                                          if line.lstrip().startswith('File "'))
                        logger.error("plugin=%s operation=%s remote traceback:\n%s", self.plugin_id, method, stack)
                        raise PluginRPCError("remote", f"{self.plugin_id}: {error['code']}: {error['message']}")
                    return final["result"]
        except Exception:
            logger.exception("plugin=%s operation=%s failed", self.plugin_id, method)
            raise
        finally:
            stopping.set()
            try:
                process.close()
            finally:
                for thread in threads:
                    thread.join(timeout=2)
                for stream in (stdin, stdout, stderr):
                    if not stream.closed:
                        stream.close()
