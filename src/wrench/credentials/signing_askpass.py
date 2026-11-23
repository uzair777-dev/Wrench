"""Unix-domain socket askpass bridge for GUI passphrase fallback (VP-18, SEC-4)."""

from __future__ import annotations

import logging
import os
import shutil
import socket
import sys
import tempfile
import threading
from typing import Callable

logger = logging.getLogger(__name__)


class SigningAskpassBridge:
    """Manages an ephemeral Unix-domain socket bridge to prompt GUI for key passphrases."""

    def __init__(self, prompt_callback: Callable[[str], str]) -> None:
        self._prompt_callback = prompt_callback
        self._temp_dir: str | None = None
        self._socket_path: str | None = None
        self._server_sock: socket.socket | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, str]:
        """Start askpass socket listener and return environment variable bindings."""
        # SEC-4: Temporary directory with mode 0o700
        self._temp_dir = tempfile.mkdtemp(prefix="wrench-askpass-")
        os.chmod(self._temp_dir, 0o700)

        self._socket_path = os.path.join(self._temp_dir, "askpass.sock")
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(self._socket_path)
        # SEC-4: Socket file permissions mode 0o600
        os.chmod(self._socket_path, 0o600)
        self._server_sock.listen(1)

        # Create helper executable script inside temp_dir
        helper_path = os.path.join(self._temp_dir, "askpass_client.py")
        client_code = f"""#!{sys.executable}
import sys
import socket

sock_path = {repr(self._socket_path)}
prompt = sys.argv[1] if len(sys.argv) > 1 else ""

try:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(sock_path)
    s.sendall(prompt.encode("utf-8") + b"\\n")
    response = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        response += chunk
    s.close()
    sys.stdout.write(response.decode("utf-8").strip())
    sys.stdout.flush()
except Exception:
    sys.exit(1)
"""
        with open(helper_path, "w", encoding="utf-8") as f:
            f.write(client_code)
        os.chmod(helper_path, 0o700)

        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

        return {
            "GIT_ASKPASS": helper_path,
            "SSH_ASKPASS": helper_path,
            "SSH_ASKPASS_REQUIRE": "force",
        }

    def _listen_loop(self) -> None:
        """Listen for incoming askpass client queries and invoke callback."""
        if self._server_sock is None:
            return
        self._server_sock.settimeout(1.0)
        while self._running:
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    data += chunk
                prompt = data.decode("utf-8", errors="replace").strip()
                passphrase = self._prompt_callback(prompt)
                conn.sendall(passphrase.encode("utf-8") + b"\n")
            except Exception as e:
                logger.debug("Askpass transaction error: %s", e)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def stop(self) -> None:
        """Stop socket listener and clean up temporary files."""
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None

        if self._temp_dir and os.path.exists(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except OSError:
                pass
            self._temp_dir = None
