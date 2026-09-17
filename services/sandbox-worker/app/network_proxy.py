"""Source for the per-run, domain-allowlisted sandbox egress proxy."""

from __future__ import annotations

import textwrap


def proxy_script() -> str:
    """Return a dependency-free HTTP CONNECT proxy for a trusted sidecar container."""
    return textwrap.dedent(
        r'''
        import ipaddress
        import json
        import os
        import select
        import socket
        import socketserver
        from urllib.parse import urlsplit

        ALLOWED = frozenset(json.loads(os.environ["CUTI_ALLOWED_DOMAINS"]))
        MAX_HEADER = 64 * 1024
        MAX_BYTES = int(os.environ.get("CUTI_PROXY_MAX_BYTES", str(16 * 1024 * 1024)))
        CONNECT_TIMEOUT = float(os.environ.get("CUTI_PROXY_CONNECT_TIMEOUT", "15"))
        IDLE_TIMEOUT = float(os.environ.get("CUTI_PROXY_IDLE_TIMEOUT", "120"))


        def allowed_target(host, port):
            normalized = host.strip().lower().rstrip(".")
            if normalized not in ALLOWED or port not in (80, 443):
                raise PermissionError("destination is not allowlisted")
            candidates = []
            for family, socktype, proto, _, address in socket.getaddrinfo(
                normalized, port, type=socket.SOCK_STREAM
            ):
                ip = ipaddress.ip_address(address[0])
                if not ip.is_global:
                    continue
                candidates.append((family, socktype, proto, address))
            if not candidates:
                raise PermissionError("destination did not resolve to a public address")
            return normalized, candidates


        def connect_public(host, port):
            _, candidates = allowed_target(host, port)
            last_error = None
            for family, socktype, proto, address in candidates:
                upstream = socket.socket(family, socktype, proto)
                upstream.settimeout(CONNECT_TIMEOUT)
                try:
                    upstream.connect(address)
                    upstream.settimeout(None)
                    return upstream
                except OSError as exc:
                    last_error = exc
                    upstream.close()
            raise OSError(f"unable to connect to allowlisted destination: {last_error}")


        def relay(left, right):
            total = 0
            sockets = [left, right]
            while sockets:
                readable, _, _ = select.select(sockets, [], [], IDLE_TIMEOUT)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(64 * 1024)
                    if not data:
                        return
                    total += len(data)
                    if total > MAX_BYTES:
                        raise OSError("proxy byte limit exceeded")
                    destination = right if source is left else left
                    destination.sendall(data)


        class Handler(socketserver.StreamRequestHandler):
            timeout = IDLE_TIMEOUT

            def handle(self):
                request_line = self.rfile.readline(MAX_HEADER + 1)
                if not request_line or len(request_line) > MAX_HEADER:
                    return
                try:
                    method, target, version = request_line.decode("latin-1").strip().split(" ", 2)
                    headers = []
                    header_bytes = len(request_line)
                    while True:
                        line = self.rfile.readline(MAX_HEADER + 1)
                        header_bytes += len(line)
                        if header_bytes > MAX_HEADER:
                            raise ValueError("headers too large")
                        if line in (b"\r\n", b"\n", b""):
                            break
                        headers.append(line)
                    if method.upper() == "CONNECT":
                        self.handle_connect(target)
                    else:
                        self.handle_http(method, target, version, headers)
                except Exception:
                    try:
                        self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                    except OSError:
                        pass

            def handle_connect(self, target):
                if target.count(":") != 1:
                    raise ValueError("invalid CONNECT target")
                host, raw_port = target.rsplit(":", 1)
                port = int(raw_port)
                upstream = connect_public(host, port)
                try:
                    self.wfile.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    self.wfile.flush()
                    relay(self.connection, upstream)
                finally:
                    upstream.close()

            def handle_http(self, method, target, version, headers):
                parsed = urlsplit(target)
                if parsed.scheme != "http" or not parsed.hostname or parsed.username:
                    raise ValueError("only absolute HTTP proxy requests are supported")
                port = parsed.port or 80
                upstream = connect_public(parsed.hostname, port)
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                content_length = 0
                forwarded = []
                saw_host = False
                for line in headers:
                    name, _, value = line.partition(b":")
                    lower = name.strip().lower()
                    if lower in {b"proxy-authorization", b"proxy-connection", b"connection"}:
                        continue
                    if lower == b"host":
                        saw_host = True
                    if lower == b"content-length":
                        content_length = int(value.strip())
                    forwarded.append(line)
                if content_length < 0 or content_length > MAX_BYTES:
                    raise ValueError("request body too large")
                if not saw_host:
                    forwarded.append(f"Host: {parsed.netloc}\r\n".encode("latin-1"))
                forwarded.append(b"Connection: close\r\n")
                upstream.sendall(f"{method} {path} {version}\r\n".encode("latin-1"))
                for line in forwarded:
                    upstream.sendall(line)
                upstream.sendall(b"\r\n")
                remaining = content_length
                while remaining:
                    chunk = self.rfile.read(min(64 * 1024, remaining))
                    if not chunk:
                        raise OSError("truncated request body")
                    upstream.sendall(chunk)
                    remaining -= len(chunk)
                try:
                    relay(self.connection, upstream)
                finally:
                    upstream.close()


        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True


        Server(("0.0.0.0", 8080), Handler).serve_forever()
        '''
    ).strip()

