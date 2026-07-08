"""Ensure only one GUI process; second launch activates the existing window."""

from __future__ import annotations

import getpass
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_ACTIVATE_MESSAGE = b"activate"


def single_instance_server_name() -> str:
    user = getpass.getuser() or "default"
    suffix = "dev" if not getattr(sys, "frozen", False) else "app"
    return f"VideoSeek_{suffix}_{user}"


def try_activate_existing_instance(server_name: str | None = None) -> bool:
    """Connect to a running instance and ask it to show the main window."""
    name = server_name or single_instance_server_name()
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(500):
        return False
    socket.write(_ACTIVATE_MESSAGE)
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


class SingleInstanceServer:
    """Primary-instance listener: secondary launches send activate over local socket."""

    def __init__(self, server_name: str | None = None, parent=None):
        self._server_name = server_name or single_instance_server_name()
        self._on_activate = None
        self._server = QLocalServer(parent)
        self._server.newConnection.connect(self._on_new_connection)
        self._listen()

    def set_activate_handler(self, handler) -> None:
        self._on_activate = handler

    def _listen(self) -> None:
        QLocalServer.removeServer(self._server_name)
        if self._server.listen(self._server_name):
            return
        QLocalServer.removeServer(self._server_name)
        if not self._server.listen(self._server_name):
            raise RuntimeError(f"Could not start single-instance server: {self._server.errorString()}")

    def _on_new_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda sock=socket: self._handle_socket(sock))
        if socket.bytesAvailable() > 0:
            self._handle_socket(socket)

    def _handle_socket(self, socket: QLocalSocket) -> None:
        if socket.bytesAvailable() > 0 and socket.readAll() == _ACTIVATE_MESSAGE:
            self._dispatch_activate()
        socket.disconnectFromServer()

    def _dispatch_activate(self) -> None:
        handler = self._on_activate
        if handler is None:
            return
        QTimer.singleShot(0, handler)
