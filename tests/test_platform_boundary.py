from __future__ import annotations

import ast
from pathlib import Path
import sys
from threading import Event
import unittest

from autolingua2.infrastructure.operations import OperationCancelled, operation_scope
from autolingua2.infrastructure.platform import current_platform
from autolingua2.infrastructure.plugin_rpc import PluginRPC, PluginRPCError

ROOT = Path(__file__).resolve().parents[1]


class NativeProcessTests(unittest.TestCase):
    def rpc(self, script: str) -> PluginRPC:
        return PluginRPC("test", Path(sys.executable), ["-c", script], ROOT)

    def test_rpc_drains_stderr_and_receives_progress_and_result(self) -> None:
        script = (
            "import json,sys; r=json.loads(sys.stdin.buffer.read()); "
            "sys.stderr.write('diagnostic\\n'*20000); sys.stderr.flush(); "
            "print(json.dumps(dict(version=1,id=r['id'],progress='working'))); "
            "print(json.dumps(dict(version=1,id=r['id'],result={'ok':True})))"
        )
        progress: list[str] = []
        with operation_scope(Event(), progress.append):
            result = self.rpc(script).call("register", {}, timeout=5)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(progress, ["working"])

    def test_malformed_and_duplicate_results_are_rejected(self) -> None:
        scripts = [
            "print('not json')",
            "import json,sys; r=json.loads(sys.stdin.buffer.read()); "
            "s=json.dumps(dict(version=1,id=r['id'],result=True)); print(s); print(s)",
            "import sys; sys.exit(3)",
        ]
        for script in scripts:
            with self.subTest(script=script), self.assertRaises(PluginRPCError):
                self.rpc(script).call("register", {}, timeout=5)

    def test_timeout_terminates_native_child(self) -> None:
        with self.assertRaises(PluginRPCError) as raised:
            self.rpc("import time; time.sleep(30)").call("register", {}, timeout=0.15)
        self.assertEqual(raised.exception.code, "timeout")

    def test_cancellation_terminates_child_after_progress(self) -> None:
        cancel = Event()
        script = (
            "import json,sys,time; r=json.loads(sys.stdin.buffer.read()); "
            "print(json.dumps(dict(version=1,id=r['id'],progress='started')),flush=True); "
            "time.sleep(30)"
        )
        with operation_scope(cancel, lambda message: cancel.set()), self.assertRaises(OperationCancelled):
            self.rpc(script).call("register", {}, timeout=5)

    def test_binary_pipes_are_bounded_and_close_is_idempotent(self) -> None:
        process = current_platform.start_plugin(
            Path(sys.executable), ["-c", "import sys; sys.stdout.buffer.write(b'abcdef\\n')"], ROOT,
        )
        try:
            process.stdin.close()
            self.assertEqual(process.stdout.readline(3), b"abc")
            self.assertEqual(process.stdout.readline(10), b"def\n")
            self.assertEqual(process.stdout.readline(10), b"")
        finally:
            process.close()
            process.close()
            process.stdout.close()
            process.stderr.close()

    def test_python_os_boundary_has_no_native_or_qt_implementation(self) -> None:
        root = ROOT / "src/autolingua2"
        for folder in ("infrastructure", "services", "ir", "adapters"):
            for path in (root / folder).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8-sig"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom):
                        modules = [node.module or ""]
                    else:
                        continue
                    self.assertFalse(any(name.startswith(("PySide6", "ctypes", "win32", "subprocess"))
                                         for name in modules), str(path))
                self.assertNotIn("sys.platform", path.read_text(encoding="utf-8-sig"), str(path))

    def test_close_terminates_descendants_and_releases_inherited_pipes(self) -> None:
        script = (
            "import subprocess,sys,time; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print('ready',flush=True); time.sleep(30)"
        )
        process = current_platform.start_plugin(Path(sys.executable), ["-c", script], ROOT)
        try:
            process.stdin.close()
            self.assertEqual(process.stdout.readline(32).strip(), b"ready")
            process.close()
            self.assertEqual(process.stdout.readline(32), b"")
        finally:
            process.close()
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    unittest.main()
