"""Authenticated local MCP Streamable HTTP on the model's Qt event loop."""
from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import json
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from autolingua2.ir.validation import record, text
from autolingua2.services.operations.application_operations import ApplicationOperations
from autolingua2.services.operations.operation_contract import McpSettings
from autolingua2.services.operations.operation_tools import OPERATION_INSTRUCTIONS

PROTOCOL_VERSION = "2025-06-18"
MAX_BODY = 8 * 1024 * 1024


def chunked_body(data: bytes) -> bytes | None:
    position = 0
    chunks: list[bytes] = []
    total = 0
    while True:
        end = data.find(b"\r\n", position)
        if end < 0:
            return None
        size = int(data[position:end].split(b";", 1)[0], 16)
        if size < 0 or total + size > MAX_BODY:
            raise ValueError("Invalid chunk length")
        position = end + 2
        if size == 0:
            if data[position:position + 2] == b"\r\n" or b"\r\n\r\n" in data[position:]:
                return b"".join(chunks)
            return None
        if len(data) < position + size + 2:
            return None
        if data[position + size:position + size + 2] != b"\r\n":
            raise ValueError("Invalid HTTP chunk")
        chunks.append(data[position:position + size])
        total += size
        position += size + 2


@dataclass(slots=True)
class HttpConnection:
    socket: QTcpSocket
    timer: QTimer
    buffer: bytearray = field(default_factory=bytearray)
    streaming: bool = False
    session: str = ""
    handled: bool = False


class McpServer(QObject):
    status_changed = Signal(str)

    def __init__(self, operations: ApplicationOperations, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.operations = operations
        self.settings = McpSettings()
        self.server = QTcpServer(self)
        self.server.newConnection.connect(self._connected)
        self._connections: dict[QTcpSocket, HttpConnection] = {}
        self._sessions: dict[str, bool] = {}
        operations.job_changed.connect(self._job_changed)
        self.error = ""

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.serverPort()}/mcp" if self.server.isListening() else ""

    def configure(self, settings: McpSettings) -> None:
        self.close()
        self.settings = settings
        self.error = ""
        if settings.enabled:
            if not settings.token:
                self.error = "MCP接続トークンを設定してください。"
            elif not self.server.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), settings.port):
                self.error = self.server.errorString()
        self.status_changed.emit(self.error or self.endpoint)

    def close(self) -> None:
        self.server.close()
        for connection in tuple(self._connections.values()):
            connection.socket.abort()
        self._sessions.clear()

    def _connected(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            if len(self._connections) >= 128:
                socket.abort()
                socket.deleteLater()
                continue
            timer = QTimer(socket)
            timer.setSingleShot(True)
            timer.timeout.connect(socket.abort)
            timer.start(30000)
            connection = HttpConnection(socket, timer)
            self._connections[socket] = connection
            socket.readyRead.connect(lambda connection=connection: self._read(connection))
            socket.disconnected.connect(lambda socket=socket: self._disconnected(socket))

    def _disconnected(self, socket: QTcpSocket) -> None:
        self._connections.pop(socket, None)
        socket.deleteLater()

    def _send(self, connection: HttpConnection, status: int, body: bytes = b"", *,
              session: str = "", streaming: bool = False) -> None:
        reasons = {200: "OK", 202: "Accepted", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                   404: "Not Found", 405: "Method Not Allowed", 406: "Not Acceptable", 413: "Content Too Large"}
        headers = [f"HTTP/1.1 {status} {reasons.get(status, 'Error')}",
                   "Content-Type: " + ("text/event-stream" if streaming else "application/json"),
                   "Cache-Control: no-store", "X-Content-Type-Options: nosniff"]
        if session:
            headers.append("Mcp-Session-Id: " + session)
        if status == 405:
            headers.append("Allow: POST, GET, DELETE")
        if streaming:
            headers.extend(["Connection: keep-alive", "Transfer-Encoding: chunked"])
        else:
            headers.extend([f"Content-Length: {len(body)}", "Connection: close"])
        connection.handled = True
        connection.socket.write(("\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body)
        if streaming:
            connection.streaming = True
            connection.timer.stop()
        else:
            connection.socket.disconnectFromHost()

    @staticmethod
    def _chunk(connection: HttpConnection, payload: bytes) -> None:
        connection.socket.write(f"{len(payload):x}\r\n".encode("ascii") + payload + b"\r\n")

    def _read(self, connection: HttpConnection) -> None:
        if connection.handled:
            return
        connection.buffer.extend(bytes(connection.socket.readAll().data()))
        if len(connection.buffer) > MAX_BODY + 16384:
            self._send(connection, 413)
            return
        marker = connection.buffer.find(b"\r\n\r\n")
        if marker < 0:
            if len(connection.buffer) > 16384:
                self._send(connection, 413)
            return
        try:
            if marker > 16384:
                raise ValueError("HTTP headers too large")
            lines = bytes(connection.buffer[:marker]).decode("ascii").split("\r\n")
            method, path, version = lines[0].split(" ")
            headers: dict[str, str] = {}
            for line in lines[1:]:
                key, value = line.split(":", 1)
                key = key.lower()
                if key in headers:
                    raise ValueError("Duplicate HTTP header")
                headers[key] = value.strip()
            if version != "HTTP/1.1" or path != "/mcp":
                self._send(connection, 404)
                return
            port = self.server.serverPort()
            if headers.get("host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
                self._send(connection, 403)
                return
            origin = headers.get("origin")
            if origin and origin not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                self._send(connection, 403)
                return
            if not hmac.compare_digest(headers.get("authorization", "").encode("utf-8"),
                                       ("Bearer " + self.settings.token).encode("utf-8")):
                self._send(connection, 401)
                return
            session = headers.get("mcp-session-id", "")
            connection.session = session
            if method != "POST":
                if session not in self._sessions:
                    self._send(connection, 404)
                elif method == "GET" and "text/event-stream" in headers.get("accept", ""):
                    self._send(connection, 200, streaming=True)
                    self._chunk(connection, b": connected\n\n")
                elif method == "DELETE":
                    self._sessions.pop(session)
                    for stream in tuple(self._connections.values()):
                        if stream.streaming and stream.session == session:
                            stream.socket.abort()
                    self._send(connection, 200)
                else:
                    self._send(connection, 405)
                return
            if headers.get("content-type", "").split(";")[0] != "application/json":
                self._send(connection, 400)
                return
            if not all(value in headers.get("accept", "") for value in ("application/json", "text/event-stream")):
                self._send(connection, 406)
                return
            if headers.get("transfer-encoding"):
                if headers["transfer-encoding"].lower() != "chunked" or "content-length" in headers:
                    raise ValueError("Invalid transfer encoding")
                body = chunked_body(bytes(connection.buffer[marker + 4:]))
                if body is None:
                    return
            else:
                size = int(headers.get("content-length", "0"))
                if not 0 < size <= MAX_BODY:
                    self._send(connection, 413)
                    return
                if len(connection.buffer) - marker - 4 < size:
                    return
                body = bytes(connection.buffer[marker + 4:marker + 4 + size])
            message = record(json.loads(body))
            if message.get("jsonrpc") != "2.0":
                raise ValueError("Invalid JSON-RPC version")
            name = text(message.get("method"), nonempty=True)
            if name != "initialize":
                if session not in self._sessions:
                    self._send(connection, 404)
                    return
                if headers.get("mcp-protocol-version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
                    self._send(connection, 400)
                    return
                if name != "notifications/initialized" and not self._sessions[session]:
                    self._send(connection, 400)
                    return
            if "id" not in message:
                if name == "notifications/initialized":
                    self._sessions[session] = True
                self._send(connection, 202)
                return
            request_id = message["id"]
            if not isinstance(request_id, (str, int)) or isinstance(request_id, bool):
                raise ValueError("Invalid request ID")
            params = record(message.get("params", {}))
            try:
                if name == "initialize":
                    if len(self._sessions) >= 128:
                        raise ValueError("Too many MCP sessions")
                    session = uuid4().hex
                    self._sessions[session] = False
                    result = {"protocolVersion": PROTOCOL_VERSION,
                              "instructions": OPERATION_INSTRUCTIONS,
                              "capabilities": {"tools": {}, "resources": {}, "prompts": {}, "logging": {}},
                              "serverInfo": {"name": "Autolingua Desktop", "version": "0.1.0"}}
                else:
                    result = self._dispatch(name, params)
                response = {"jsonrpc": "2.0", "id": request_id, "result": result}
            except (ValueError, RuntimeError, OSError) as exc:
                response = {"jsonrpc": "2.0", "id": request_id,
                            "error": {"code": -32602, "message": str(exc)}}
            self._send(connection, 200, json.dumps(response, ensure_ascii=False).encode("utf-8"), session=session)
        except (ValueError, UnicodeError, KeyError):
            self._send(connection, 400)

    def _dispatch(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "ping":
            return {}
        if method == "logging/setLevel":
            return {}
        if method == "tools/list":
            return {"tools": self.operations.tools(self.settings.permissions)}
        if method == "tools/call":
            try:
                value = self.operations.execute(text(params.get("name")), record(params.get("arguments", {})),
                                                permissions=self.settings.permissions)
                return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                        "structuredContent": value, "isError": False}
            except (ValueError, RuntimeError, OSError) as exc:
                return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        if "read" not in self.settings.permissions:
            raise ValueError("参照権限がありません。")
        if method == "resources/list":
            return {"resources": self.operations.resources()}
        if method == "resources/templates/list":
            return {"resourceTemplates": self.operations.resource_templates()}
        if method == "resources/read":
            return self.operations.read_resource(text(params.get("uri")))
        if method == "prompts/list":
            return {"prompts": self.operations.prompts()}
        if method == "prompts/get":
            return self.operations.get_prompt(text(params.get("name")))
        raise ValueError("Unsupported MCP method")

    def _job_changed(self, value: object) -> None:
        if not isinstance(value, dict):
            return
        payload = json.dumps({"jsonrpc": "2.0", "method": "notifications/message",
            "params": {"level": "info", "logger": "autolingua.jobs", "data": value}}, ensure_ascii=False)
        for connection in tuple(self._connections.values()):
            if connection.streaming and "read" in self.settings.permissions:
                self._chunk(connection, ("event: message\ndata: " + payload + "\n\n").encode("utf-8"))
