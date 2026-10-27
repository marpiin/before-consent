"""Anti-SSRF guard: a local forward proxy that every browser connection goes through.

Playwright's page.route() is not called for the hops of a redirect, so a public page could
redirect a subresource to 169.254.169.254 and the route handler would never see it. The proxy
sees every connection the browser opens (navigations, redirects, subresources, websockets),
resolves the host itself, checks every address with ipaddress and connects to the address it
checked. Hosts it refuses are remembered so the visit log can mark those requests as blocked.
"""

import ipaddress
import select
import socket
import socketserver
import threading
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

Resolver = Callable[[str], list[str]]

ALLOWED_SCHEMES = ("http", "https")
MAX_HEAD_BYTES = 64 * 1024
CONNECT_TIMEOUT = 10.0
IDLE_TIMEOUT = 60.0


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str
    address: str | None = None


def system_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def address_verdict(address: str, allow_local: bool = False) -> Verdict:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_global and not ip.is_multicast:
        return Verdict(True, "public address", str(ip))
    # ipaddress counts 169.254.0.0/16 as private; the metadata endpoint must stay closed.
    if allow_local and (ip.is_loopback or ip.is_private) and not ip.is_link_local:
        return Verdict(True, "local address allowed by --allow-local", str(ip))
    return Verdict(False, f"non-public address {ip}")


def host_verdict(
    host: str, resolve: Resolver = system_resolve, allow_local: bool = False
) -> Verdict:
    host = host.strip("[]")
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = resolve(host)
        except OSError as error:
            return Verdict(False, f"DNS lookup failed: {error}")
    if not addresses:
        return Verdict(False, "DNS lookup returned no addresses")
    verdicts = [address_verdict(address, allow_local) for address in addresses]
    # One private answer is enough to refuse: we cannot know which one the browser would use.
    refused = [v for v in verdicts if not v.allowed]
    return refused[0] if refused else verdicts[0]


def url_verdict(url: str, resolve: Resolver = system_resolve, allow_local: bool = False) -> Verdict:
    parts = urlsplit(url)
    if parts.scheme not in ALLOWED_SCHEMES:
        return Verdict(False, f"scheme {parts.scheme!r} is not http or https")
    if not parts.hostname:
        return Verdict(False, "URL has no host")
    return host_verdict(parts.hostname, resolve, allow_local)


class GuardProxy(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, resolve: Resolver = system_resolve, allow_local: bool = False) -> None:
        super().__init__(("127.0.0.1", 0), _ProxyConnection)
        self.resolve = resolve
        self.allow_local = allow_local
        self._blocked: dict[str, str] = {}
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "GuardProxy":
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()

    def record_blocked(self, host: str, reason: str) -> None:
        with self._lock:
            self._blocked[host.lower().strip("[]")] = reason

    def take_blocked(self) -> dict[str, str]:
        with self._lock:
            blocked, self._blocked = self._blocked, {}
        return blocked


class _ProxyConnection(socketserver.BaseRequestHandler):
    server: GuardProxy

    def handle(self) -> None:
        client: socket.socket = self.request
        client.settimeout(IDLE_TIMEOUT)
        try:
            head, rest = _read_head(client)
        except (OSError, ValueError):
            return
        request_line, _, header_block = head.partition(b"\r\n")
        try:
            method, target, version = request_line.decode("latin-1").split(" ", 2)
        except ValueError:
            _reply(client, 400, "Bad Request")
            return

        if method == "CONNECT":
            host, _, port_text = target.rpartition(":")
            outgoing = b""
        else:
            parts = urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                _reply(client, 400, "Bad Request")
                return
            host, port_text = parts.hostname, str(parts.port or 80)
            outgoing = _origin_form(method, parts, version, header_block) + rest

        if not port_text.isdigit():
            _reply(client, 400, "Bad Request")
            return
        verdict = host_verdict(host, self.server.resolve, self.server.allow_local)
        if not verdict.allowed or verdict.address is None:
            self.server.record_blocked(host, verdict.reason)
            _reply(client, 403, "Forbidden")
            return
        try:
            upstream = socket.create_connection(
                (verdict.address, int(port_text)), timeout=CONNECT_TIMEOUT
            )
        except OSError:
            _reply(client, 502, "Bad Gateway")
            return
        with upstream:
            if method == "CONNECT":
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
            else:
                upstream.sendall(outgoing)
            _pipe(client, upstream)


def _read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ValueError("connection closed before the request head ended")
        data += chunk
        if len(data) > MAX_HEAD_BYTES:
            raise ValueError("request head too large")
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _origin_form(method: str, parts, version: str, header_block: bytes) -> bytes:
    # Plain http through a proxy arrives in absolute form. We forward it in origin form and
    # force Connection: close so the browser can never reuse this tunnel for another host.
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    kept = [
        line
        for line in header_block.split(b"\r\n")
        if line and not line.lower().startswith((b"proxy-", b"connection:", b"keep-alive:"))
    ]
    lines = [f"{method} {path} {version}".encode("latin-1"), *kept, b"Connection: close"]
    return b"\r\n".join(lines) + b"\r\n\r\n"


def _reply(sock: socket.socket, status: int, text: str) -> None:
    try:
        sock.sendall(
            f"HTTP/1.1 {status} {text}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
        )
    except OSError:
        return


def _pipe(a: socket.socket, b: socket.socket) -> None:
    sockets = [a, b]
    while True:
        readable, _, errored = select.select(sockets, [], sockets, IDLE_TIMEOUT)
        if errored or not readable:
            return
        for source in readable:
            target = b if source is a else a
            try:
                chunk = source.recv(65536)
                if not chunk:
                    return
                target.sendall(chunk)
            except OSError:
                return
