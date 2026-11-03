"""Loopback-only HTTP fixtures, including a controlled CONNECT proxy."""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import select
import socket
from threading import Event, Thread
from types import SimpleNamespace
import os
import urllib.request


def isolate_proxy_environment(monkeypatch):
    for name in os.environ:
        if name.lower().endswith("_proxy") or name in ("REQUEST_METHOD", "SSL_CERT_FILE", "SSL_CERT_DIR"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(urllib.request, "getproxies", urllib.request.getproxies_environment)


@contextmanager
def http_server(respond=None, *, tls=None, tunnel_target=None):
    requests, connections_closed = [], []
    stopping = Event()
    closed = Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_GET(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            requests.append(SimpleNamespace(method=self.command, path=self.path, body=body,
                                            headers=self.headers, peer=self.client_address))
            status, headers, content = respond(self) if respond else (200, {}, b"origin")
            try:
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Timeout/early-close tests deliberately close the peer.

        do_POST = do_GET

        def do_CONNECT(self):
            requests.append(SimpleNamespace(method="CONNECT", path=self.path, peer=self.client_address))
            if tunnel_target is None or self.path != f"{tunnel_target[0]}:{tunnel_target[1]}":
                self.send_error(403)
                return
            with socket.create_connection(tunnel_target, timeout=2) as remote:
                self.send_response(200)
                self.end_headers()
                while not stopping.is_set():
                    readable, _, _ = select.select([self.connection, remote], [], [], .1)
                    for source in readable:
                        try:
                            data = source.recv(65536)
                            if not data:
                                return
                            (remote if source is self.connection else self.connection).sendall(data)
                        except (OSError, ConnectionError):
                            return

        def finish(self):
            try:
                super().finish()
            finally:
                connections_closed.append(self.client_address)
                closed.set()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f"{'https' if tls else 'http'}://127.0.0.1:{server.server_port}",
                              port=server.server_port, requests=requests, connections_closed=connections_closed,
                              closed=closed)
    finally:
        stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
