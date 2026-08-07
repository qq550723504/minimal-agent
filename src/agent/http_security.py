import ipaddress
import os
import socket
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Set
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ParsedURL:
    url: str
    scheme: str
    hostname: str
    port: int
    resolved_addresses: tuple[str, ...]


_DNS_PIN_LOCK = threading.RLock()


def _bool_env(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _allowed_hosts_from_env() -> Set[str]:
    return {
        item.strip().lower()
        for item in os.getenv("AGENT_HTTP_ALLOWED_HOSTS", "").split(",")
        if item.strip()
    }


def _address_from_info(info) -> str:
    return info[4][0]


def _is_unsafe_address(address: ipaddress._BaseAddress) -> bool:
    return address.is_loopback or address.is_private or address.is_link_local or address.is_reserved or address.is_unspecified


def validate_http_url(url: str, allowed_hosts: Optional[Set[str]] = None) -> ParsedURL:
    if not isinstance(url, str) or not url.strip():
        raise ValueError("HTTP URL is required")

    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("HTTP URL scheme must be http or https")
    if parsed.username or parsed.password:
        raise ValueError("HTTP URL credentials are not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("HTTP URL host is required")
    hostname = hostname.lower().rstrip(".")
    hosts = allowed_hosts if allowed_hosts is not None else _allowed_hosts_from_env()
    hosts = {host.lower().rstrip(".") for host in hosts}
    if hostname not in hosts:
        raise ValueError(f"HTTP host is not in the allowlist: {hostname}")

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("HTTP URL port is invalid") from exc

    try:
        literal_address = ipaddress.ip_address(hostname)
        addresses = [literal_address]
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"HTTP host could not be resolved: {hostname}") from exc
        addresses = [_address_from_info(info) for info in infos]

    parsed_addresses = [ipaddress.ip_address(address) for address in addresses]
    if not parsed_addresses or (not _bool_env("AGENT_HTTP_ALLOW_PRIVATE") and any(_is_unsafe_address(address) for address in parsed_addresses)):
        raise ValueError(f"HTTP host resolves to an unsafe address: {hostname}")

    return ParsedURL(
        url=parsed.geturl(),
        scheme=scheme,
        hostname=hostname,
        port=port,
        resolved_addresses=tuple(str(address) for address in parsed_addresses),
    )


@contextmanager
def pin_dns_resolution(parsed: ParsedURL):
    """Keep requests on the addresses validated for this hostname and request."""
    original_getaddrinfo = socket.getaddrinfo
    normalized_hostname = parsed.hostname.rstrip(".").lower()

    def pinned_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if not isinstance(host, str) or host.rstrip(".").lower() != normalized_hostname:
            return original_getaddrinfo(host, port, family, type, proto, flags)

        results = []
        for address in parsed.resolved_addresses:
            ip_address = ipaddress.ip_address(address)
            address_family = socket.AF_INET6 if ip_address.version == 6 else socket.AF_INET
            if family not in (0, socket.AF_UNSPEC, address_family):
                continue
            socket_type = type or socket.SOCK_STREAM
            if socket_type != socket.SOCK_STREAM:
                continue
            target_port = port or parsed.port
            sockaddr = (address, target_port, 0, 0) if address_family == socket.AF_INET6 else (address, target_port)
            results.append((address_family, socket_type, proto or socket.IPPROTO_TCP, "", sockaddr))
        if not results:
            raise socket.gaierror(f"no validated address for {host}")
        return results

    with _DNS_PIN_LOCK:
        socket.getaddrinfo = pinned_getaddrinfo
        try:
            yield
        finally:
            socket.getaddrinfo = original_getaddrinfo
