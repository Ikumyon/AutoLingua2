"""Nonblocking, read-only external MCP connections using QtNetwork/QProcess."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QByteArray, QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from autolingua2.ir.validation import record, text
from autolingua2.services.mcp_server import MAX_BODY, PROTOCOL_VERSION
from autolingua2.services.operation_contract import ExternalMcpConnection

Success = Callable[[dict[str, Any]], None]
Failure = Callable[[str], None]
READ_METHODS = {"resources/list", "resources/templates/list", "resources/read"}


@dataclass(slots=True)
class ClientConnection:
    settings: ExternalMcpConnection
    status: str = "disconnected"
    error: str = ""
    session: str = ""
    protocol: str = PROTOCOL_VERSION
    capabilities: dict[str, Any] = field(default_factory=dict)
    process: QProcess | None = None
    buffer: bytearray = field(default_factory=bytearray)
    queued: list[tuple[str, dict[str, Any], Success, Failure, str]] = field(default_factory=list)


@dataclass(slots=True)
class PendingRequest:
    connection_id: str
    success: Success
    failure: Failure
    job_id: str
    timer: QTimer
    reply: QNetworkReply | None = None


class McpClient(QObject):
    status_changed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.connections: dict[str, ClientConnection] = {}
        self._pending: dict[str, PendingRequest] = {}

    def configure(self, connections: list[ExternalMcpConnection]) -> None:
        self.close()
        self.connections = {item.id: ClientConnection(item) for item in connections}

    def inventory(self) -> list[dict[str, Any]]:
        return [{"id": item.settings.id, "name": item.settings.name,
                 "transport": item.settings.transport, "status": item.status,
                 "error": item.error, "capabilities": item.capabilities} for item in self.connections.values()]

    def request(self, connection_id: str, method: str, params: dict[str, Any],
                success: Success, failure: Failure) -> None:
        if method not in READ_METHODS:
            raise ValueError("外部MCPでは資料の読み取り操作だけを許可しています。")
        connection = self.connections.get(connection_id)
        if connection is None:
            raise ValueError("登録済みの外部MCP接続を指定してください。")
        arguments = dict(params)
        job_id = text(arguments.pop("_job_id", ""))
        if connection.status == "ready":
            self._request_ready(connection, method, arguments, success, failure, job_id)
        else:
            connection.queued.append((method, arguments, success, failure, job_id))
            if connection.status != "connecting":
                self._connect(connection)

    def check(self, connection_id: str, success: Success, failure: Failure) -> None:
        self.request(connection_id, "resources/list", {}, success, failure)

    def _connect(self, connection: ClientConnection) -> None:
        connection.status, connection.error = "connecting", ""
        self.status_changed.emit(connection.settings.id, connection.status)
        settings = connection.settings
        if settings.transport == "stdio":
            process = QProcess(self)
            connection.process = process
            process.setProgram(settings.address)
            process.setArguments(settings.arguments)
            process.started.connect(lambda: self._initialize(connection))
            process.readyReadStandardOutput.connect(lambda: self._stdio_read(connection))
            process.readyReadStandardError.connect(lambda: process.readAllStandardError())
            process.errorOccurred.connect(lambda error: self._fail_connection(connection, process.errorString()))
            process.finished.connect(lambda code, status: self._fail_connection(connection, f"MCPプロセスが終了しました ({code})"))
            process.start()
        else:
            url = QUrl(settings.address)
            if not url.isValid() or url.scheme() not in {"http", "https"} or not url.host() or url.userInfo():
                self._fail_connection(connection, "HTTP(S)のMCP接続URLを指定してください。")
                return
            self._initialize(connection)

    def _initialize(self, connection: ClientConnection) -> None:
        def initialized(value: dict[str, Any]) -> None:
            protocol = text(value.get("protocolVersion"))
            if protocol not in {"2025-03-26", "2025-06-18", "2025-11-25"}:
                self._fail_connection(connection, "外部MCPのプロトコルバージョンに対応していません。")
                return
            connection.protocol = protocol
            connection.capabilities = record(value.get("capabilities", {}))
            def ready() -> None:
                connection.status = "ready"
                self.status_changed.emit(connection.settings.id, connection.status)
                queued, connection.queued = connection.queued, []
                for method, params, success, failure, job_id in queued:
                    self._request_ready(connection, method, params, success, failure, job_id)
            self._notification(connection, "notifications/initialized", {}, ready)
        self._send(connection, "initialize", {"protocolVersion": PROTOCOL_VERSION,
            "capabilities": {}, "clientInfo": {"name": "Autolingua Desktop", "version": "0.1.0"}},
            initialized, lambda error: self._fail_connection(connection, error))

    def _request_ready(self, connection: ClientConnection, method: str, params: dict[str, Any],
                       success: Success, failure: Failure, job_id: str) -> None:
        if "resources" not in connection.capabilities:
            failure("この外部MCPは資料の読み取りに対応していません。")
            return
        self._send(connection, method, params, success, failure, job_id)

    def _send(self, connection: ClientConnection, method: str, params: dict[str, Any],
              success: Success, failure: Failure, job_id: str = "") -> None:
        request_id = uuid4().hex
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._fail_request(request_id, "外部MCPの応答がタイムアウトしました。"))
        self._pending[request_id] = PendingRequest(connection.settings.id, success, failure, job_id, timer)
        timer.start(30000)
        self._write(connection, {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, request_id)

    def _notification(self, connection: ClientConnection, method: str, params: dict[str, Any],
                      accepted: Callable[[], None] | None = None) -> None:
        self._write(connection, {"jsonrpc": "2.0", "method": method, "params": params}, accepted=accepted)

    def _write(self, connection: ClientConnection, message: dict[str, Any], request_id: str = "",
               *, accepted: Callable[[], None] | None = None) -> None:
        payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
        if len(payload) > MAX_BODY:
            if request_id:
                self._fail_request(request_id, "MCPリクエストが大きすぎます。")
            return
        if connection.settings.transport == "stdio":
            process = connection.process
            if process is None or process.state() != QProcess.ProcessState.Running:
                self._fail_connection(connection, "MCPプロセスが起動していません。")
                return
            process.write(payload + b"\n")
            if accepted is not None:
                accepted()
            return
        request = QNetworkRequest(QUrl(connection.settings.address))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json")
        request.setRawHeader(b"Accept", b"application/json, text/event-stream")
        request.setRawHeader(b"MCP-Protocol-Version", connection.protocol.encode("ascii"))
        if connection.settings.token:
            request.setRawHeader(b"Authorization", ("Bearer " + connection.settings.token).encode("utf-8"))
        if connection.session:
            request.setRawHeader(b"Mcp-Session-Id", connection.session.encode("ascii"))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setTransferTimeout(30000)
        reply = self.manager.post(request, QByteArray(payload))
        pending = self._pending.get(request_id)
        if pending is not None:
            pending.reply = reply
        buffer = bytearray()

        def read() -> None:
            buffer.extend(bytes(reply.readAll().data()))
            if len(buffer) > MAX_BODY:
                self._fail_request(request_id, "外部MCPの応答が大きすぎます。")
                reply.abort()
                return
            session = bytes(reply.rawHeader("Mcp-Session-Id").data()).decode("ascii", errors="replace")
            if any(not 0x21 <= ord(character) <= 0x7e for character in session):
                self._fail_connection(connection, "外部MCPのセッションIDが不正です。")
                reply.abort()
                return
            if session:
                connection.session = session
            if "text/event-stream" in str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader)):
                normalized = bytes(buffer).replace(b"\r\n", b"\n")
                while b"\n\n" in normalized:
                    frame, normalized = normalized.split(b"\n\n", 1)
                    data = b"\n".join(line[5:].lstrip(b" ") for line in frame.split(b"\n") if line.startswith(b"data:"))
                    if data:
                        self._message(connection, data)
                buffer.clear()
                buffer.extend(normalized)
                if request_id and request_id not in self._pending:
                    reply.abort()

        def finished() -> None:
            try:
                read()
                if reply.error() != QNetworkReply.NetworkError.NoError:
                    if request_id in self._pending:
                        self._fail_request(request_id, reply.errorString())
                    elif accepted is not None:
                        self._fail_connection(connection, reply.errorString())
                    return
                status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
                if not isinstance(status, int) or not 200 <= status < 300:
                    self._fail_request(request_id, f"外部MCP HTTPエラー: {status}")
                    if accepted is not None:
                        self._fail_connection(connection, f"外部MCP HTTPエラー: {status}")
                    return
                if accepted is not None:
                    accepted()
                if buffer and "text/event-stream" not in str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader)):
                    self._message(connection, bytes(buffer))
                if request_id in self._pending:
                    self._fail_request(request_id, "外部MCPの応答にリクエスト結果がありません。")
            except (ValueError, UnicodeError) as exc:
                self._fail_request(request_id, str(exc))
            finally:
                reply.deleteLater()
        reply.readyRead.connect(read)
        reply.finished.connect(finished)

    def _stdio_read(self, connection: ClientConnection) -> None:
        process = connection.process
        if process is None:
            return
        connection.buffer.extend(bytes(process.readAllStandardOutput().data()))
        if len(connection.buffer) > MAX_BODY:
            self._fail_connection(connection, "外部MCPの応答が大きすぎます。")
            return
        while b"\n" in connection.buffer:
            line, remaining = connection.buffer.split(b"\n", 1)
            connection.buffer = bytearray(remaining)
            if line.strip():
                self._message(connection, bytes(line))

    def _message(self, connection: ClientConnection, payload: bytes) -> None:
        try:
            message = record(json.loads(payload))
            if message.get("jsonrpc") != "2.0":
                raise ValueError("JSON-RPCの応答形式が不正です。")
            request_id = str(message.get("id", ""))
            if "method" in message:
                if "id" in message:
                    # Sampling/elicitation are not enabled by this read-only client.
                    self._write(connection, {"jsonrpc": "2.0", "id": message["id"],
                        "error": {"code": -32601, "message": "Client requests are not supported"}})
                return
            pending = self._pending.get(request_id)
            if pending is None or pending.connection_id != connection.settings.id:
                return
            if "error" in message:
                self._fail_request(request_id, text(record(message["error"]).get("message", "MCP error")))
                return
            result = record(message.get("result"))
            self._pending.pop(request_id)
            pending.timer.stop()
            pending.timer.deleteLater()
            pending.success(result)
        except (ValueError, UnicodeError) as exc:
            self._fail_connection(connection, f"外部MCPの応答を解析できません: {exc}")

    def _fail_request(self, request_id: str, error: str) -> None:
        pending = self._pending.pop(request_id, None)
        if pending is None:
            return
        pending.timer.stop()
        pending.timer.deleteLater()
        if pending.reply is not None and pending.reply.isRunning():
            pending.reply.abort()
        pending.failure(error)

    def _fail_connection(self, connection: ClientConnection, error: str) -> None:
        connection.status, connection.error = "failed", error
        self.status_changed.emit(connection.settings.id, error)
        queued, connection.queued = connection.queued, []
        for _, _, _, failure, _ in queued:
            failure(error)
        for request_id, pending in tuple(self._pending.items()):
            if pending.connection_id == connection.settings.id:
                self._fail_request(request_id, error)

    def cancel_job(self, job_id: str) -> None:
        for connection in self.connections.values():
            connection.queued = [item for item in connection.queued if item[4] != job_id]
        for request_id, pending in tuple(self._pending.items()):
            if pending.job_id == job_id:
                connection = self.connections[pending.connection_id]
                self._notification(connection, "notifications/cancelled", {"requestId": request_id, "reason": "User cancelled"})
                self._fail_request(request_id, "中止しました。")

    def close(self) -> None:
        for connection in self.connections.values():
            self._fail_connection(connection, "MCP接続を終了しました。")
            if connection.process is not None:
                connection.process.finished.connect(connection.process.deleteLater)
                connection.process.kill()
