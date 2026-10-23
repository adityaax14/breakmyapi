"""Tests for the SSRF guard.

`fake_dns` replaces the real DNS lookup with a dictionary {name: [ip, ...]}, so we can make
any name point anywhere, exactly what an attacker can do with a domain they own.
"""

import ipaddress
import socket

import pytest
from fastapi.testclient import TestClient

import breakmyapi.api.main as main
from breakmyapi.netguard import BlockedAddress, is_public, pin, resolve_public
from breakmyapi.ownership import fetch_proof


@pytest.fixture
def fake_dns(monkeypatch):
    records = {}

    def getaddrinfo(host, port, *args, **kwargs):
        if host not in records:
            raise socket.gaierror("name not found")
        # Same shape as the real answer: (family, type, proto, canonname, (ip, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in records[host]]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return records


@pytest.mark.parametrize(
    ("ip", "public"),
    [
        ("8.8.8.8", True),              # Google's DNS: a normal internet address
        ("93.184.215.14", True),
        ("2606:4700::1111", True),      # a normal IPv6 internet address
        ("127.0.0.1", False),           # this machine itself
        ("10.0.0.5", False),            # private network
        ("172.16.0.1", False),          # private network
        ("192.168.1.1", False),         # home/office router range
        ("169.254.169.254", False),     # cloud metadata service (secret keys!)
        ("100.64.0.1", False),          # carrier-internal range
        ("0.0.0.0", False),             # "any address"
        ("::1", False),                 # IPv6 "this machine"
        ("fc00::1", False),             # IPv6 private
        ("::ffff:127.0.0.1", False),    # 127.0.0.1 disguised as IPv6
        ("224.0.0.1", False),           # multicast
    ],
)
def test_is_public(ip, public):
    assert is_public(ipaddress.ip_address(ip)) is public


def test_a_name_pointing_to_a_public_address_is_allowed(fake_dns):
    fake_dns["api.example.com"] = ["93.184.215.14"]
    assert resolve_public("api.example.com", 443) == "93.184.215.14"


def test_a_name_pointing_inside_our_network_is_blocked(fake_dns):
    fake_dns["sneaky.attacker.com"] = ["169.254.169.254"]
    with pytest.raises(BlockedAddress, match="private or internal"):
        resolve_public("sneaky.attacker.com", 80)


def test_one_private_address_among_public_ones_is_still_blocked(fake_dns):
    fake_dns["mixed.attacker.com"] = ["93.184.215.14", "10.0.0.5"]
    with pytest.raises(BlockedAddress):
        resolve_public("mixed.attacker.com", 80)


def test_an_unknown_name_is_blocked(fake_dns):
    with pytest.raises(BlockedAddress, match="Could not find"):
        resolve_public("does-not-exist.example", 80)


def test_pin_uses_the_checked_ip_but_keeps_the_real_name(fake_dns):
    fake_dns["api.example.com"] = ["93.184.215.14"]
    pinned_url, host_header, tls_name = pin("https://api.example.com:443/.well-known/x.txt")
    assert pinned_url == "https://93.184.215.14:443/.well-known/x.txt"
    assert host_header == "api.example.com:443"
    assert tls_name == "api.example.com"


def test_pin_puts_ipv6_in_brackets(fake_dns, monkeypatch):
    monkeypatch.setattr("breakmyapi.netguard.resolve_public", lambda host, port: "2606:4700::1111")
    pinned_url, _, _ = pin("http://v6.example.com/x")
    assert pinned_url == "http://[2606:4700::1111]:80/x"


def test_fetch_proof_refuses_internal_addresses_before_sending_anything():
    # No fake DNS needed: an IP written directly in the URL is checked as-is.
    with pytest.raises(BlockedAddress):
        fetch_proof("http://127.0.0.1:8001/.well-known/breakmyapi-verify.txt")
    with pytest.raises(BlockedAddress):
        fetch_proof("http://169.254.169.254/latest/meta-data/")


def test_verify_explains_a_blocked_address(db, monkeypatch):
    def blocked(url):
        raise BlockedAddress("internal.attacker.com points to a private or internal address (10.0.0.5)")

    monkeypatch.setattr(main, "fetch_proof", blocked)
    client = TestClient(main.app)
    claim = client.post("/targets", json={"target_url": "https://internal.attacker.com"}).json()

    response = client.post(f"/targets/{claim['id']}/verify")
    assert response.status_code == 400
    assert response.json()["detail"].startswith("Refused:")
