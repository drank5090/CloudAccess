"""公网 IP 检测测试（全部离线，不发真实请求）。"""

import socket

import pytest

from cloudaccess import iputil
from cloudaccess.errors import IpDetectionError

DEMO_IP = "203.0.113.7"  # TEST-NET-3 文档地址，非真实出口


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text

    def raise_for_status(self) -> None:
        return None


def _reset_cache(monkeypatch):
    monkeypatch.setattr(iputil, "_cached_ip", "")
    monkeypatch.setattr(iputil, "_cached_at", 0.0)


def test_is_public_ipv4():
    assert iputil._is_public_ipv4(DEMO_IP)
    assert iputil._is_public_ipv4("8.8.8.8")
    assert not iputil._is_public_ipv4("10.0.0.1")
    assert not iputil._is_public_ipv4("172.16.0.1")
    assert not iputil._is_public_ipv4("172.31.255.255")
    assert iputil._is_public_ipv4("172.32.0.1")
    assert not iputil._is_public_ipv4("192.168.1.1")
    assert not iputil._is_public_ipv4("127.0.0.1")
    assert not iputil._is_public_ipv4("not-an-ip")
    assert not iputil._is_public_ipv4("300.1.1.1")
    assert not iputil._is_public_ipv4("::1")


def test_assert_endpoint_safe_whitelist():
    assert iputil._assert_endpoint_safe("https://api.ipify.org") == "api.ipify.org"
    with pytest.raises(IpDetectionError):
        iputil._assert_endpoint_safe("http://api.ipify.org")  # 非 HTTPS
    with pytest.raises(IpDetectionError):
        iputil._assert_endpoint_safe("https://evil.example.com")  # 不在白名单


def test_assert_endpoint_safe_blocks_private_resolution(monkeypatch):
    infos = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    monkeypatch.setattr(iputil.socket, "getaddrinfo", lambda *args, **kwargs: infos)
    with pytest.raises(IpDetectionError):
        iputil._assert_endpoint_safe("https://api.ipify.org")


def test_assert_endpoint_safe_dns_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise OSError("dns down")

    monkeypatch.setattr(iputil.socket, "getaddrinfo", _boom)
    with pytest.raises(IpDetectionError):
        iputil._assert_endpoint_safe("https://api.ipify.org")


def test_get_public_ip_success_and_cache(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(iputil.requests, "get", lambda url, **kwargs: _FakeResponse(f"{DEMO_IP}\n"))
    assert iputil.get_public_ip(force=True) == DEMO_IP
    # 短时间内命中缓存：换一个不同的“响应”也不应生效
    monkeypatch.setattr(iputil.requests, "get", lambda url, **kwargs: _FakeResponse("198.51.100.9"))
    assert iputil.get_public_ip() == DEMO_IP


def test_get_public_ip_rejects_private_answer(monkeypatch):
    _reset_cache(monkeypatch)
    monkeypatch.setattr(iputil.requests, "get", lambda url, **kwargs: _FakeResponse("10.0.0.1"))
    with pytest.raises(IpDetectionError):
        iputil.get_public_ip(force=True)


def test_get_public_ip_all_endpoints_fail(monkeypatch):
    _reset_cache(monkeypatch)

    def _boom(url, **kwargs):
        raise iputil.requests.RequestException("network down")

    monkeypatch.setattr(iputil.requests, "get", _boom)
    with pytest.raises(IpDetectionError):
        iputil.get_public_ip(force=True)
