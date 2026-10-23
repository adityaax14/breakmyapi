"""The SSRF guard: every request our server sends to a user's address goes through here.

The danger: a name like "api.attacker.com" can point to ANY IP address, including ones inside
our own network, e.g. 127.0.0.1 (this machine), 10.x / 192.168.x (other private machines), or
169.254.169.254 (the cloud "metadata" service that hands out secret keys). Checking the NAME
is not enough; we must check the IP address it really points to.

So, before each request:
  1. resolve the name to its IP addresses (DNS lookup)
  2. refuse if ANY of them is private or internal
  3. connect to exactly that checked IP ("pinning"), so the name cannot switch to another IP
     between our check and our request (a trick called DNS rebinding)
"""

import ipaddress
import socket
from contextlib import contextmanager
from urllib.parse import urlsplit

import httpx


class BlockedAddress(Exception):
    """The address is not one we are willing to send a request to."""


def is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Is this a normal internet address (not private, loopback, link-local, reserved, ...)?"""
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # "::ffff:127.0.0.1" is 127.0.0.1 in disguise: judge the real one
    # is_global is False for every special range: 127.x, 10.x, 172.16-31.x, 192.168.x, 169.254.x,
    # 100.64.x, 0.0.0.0, ::1, fc00::/7, fe80::/10 and more. Python keeps that list up to date for us.
    return ip.is_global and not ip.is_multicast


def resolve_public(host: str, port: int) -> str:
    """Look up `host` and return one of its IP addresses, but only if ALL of them are public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise BlockedAddress(f"Could not find the address of {host}") from e

    ips = set()
    for info in infos:
        try:
            ips.add(ipaddress.ip_address(info[4][0]))  # info[4] is (ip, port, ...)
        except ValueError as e:  # something odd, like an IPv6 address with a "%eth0" suffix
            raise BlockedAddress(f"{host} has an address we cannot check") from e

    # ALL, not just the first: a name can have several addresses, and an attacker can mix
    # one public address with one private one, hoping we check only the public one.
    for ip in ips:
        if not is_public(ip):
            raise BlockedAddress(f"{host} points to a private or internal address ({ip})")
    return str(min(ips, key=str))


def pin(url: str) -> tuple[str, str, str]:
    """Check the URL's address and rewrite the URL to use the checked IP directly.

    Returns (pinned_url, host_header, tls_name). For example, with api.example.com -> 93.184.215.14:
        "https://api.example.com:443/x"
     -> ("https://93.184.215.14:443/x", "api.example.com:443", "api.example.com")
    The Host header and tls_name still say the real name, so the server (and its HTTPS
    certificate) behave exactly as if we had used the name.
    """
    parts = urlsplit(url)
    if parts.hostname is None:
        raise BlockedAddress("The URL has no host")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    ip = resolve_public(parts.hostname, port)
    ip_in_url = f"[{ip}]" if ":" in ip else ip  # IPv6 addresses need [brackets] inside a URL
    pinned_url = parts._replace(netloc=f"{ip_in_url}:{port}").geturl()
    return pinned_url, parts.netloc, parts.hostname


@contextmanager
def guarded_stream(method: str, url: str, *, timeout: float, headers: dict | None = None):
    """Like httpx.stream(...), but only to public addresses, pinned to the checked IP, and never
    following redirects (a redirect would go to a new address that we have not checked).

    Use it with `with`:   with guarded_stream("GET", url, timeout=5) as response: ...
    """
    pinned_url, host_header, tls_name = pin(url)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        request = client.build_request(
            method,
            pinned_url,
            headers={**(headers or {}), "Host": host_header},
            extensions={"sni_hostname": tls_name},  # HTTPS: ask for, and check, the real name's certificate
        )
        response = client.send(request, stream=True)
        try:
            yield response
        finally:
            response.close()
