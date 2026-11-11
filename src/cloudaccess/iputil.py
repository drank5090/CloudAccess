"""公网出口 IP 检测。

依次尝试多个公开探测端点，取第一个成功结果；结果带短时缓存。
安全约束（防 SSRF）：
- 仅允许 HTTPS + 源码中硬编码的域名白名单；
- 请求前解析域名并阻断解析到私网/环回/链路本地地址的结果（防 DNS rebinding）；
- 禁止跟随重定向。
"""

from __future__ import annotations

import ipaddress
import socket
import time
from urllib.parse import urlparse

import requests

from .errors import IpDetectionError

_ENDPOINTS = (
    "https://api.ipify.org",
    "https://ifconfig.me/ip",
    "https://icanhazip.com",
    "https://api.ip.sb/ip",
)
_ALLOWED_HOSTS = frozenset(urlparse(u).hostname for u in _ENDPOINTS)
_TIMEOUT = 6.0
_CACHE_TTL = 60.0


def _assert_endpoint_safe(url: str) -> str:
    """校验探测端点：HTTPS、域名白名单、解析结果不为内网地址。"""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        raise IpDetectionError(f"探测端点不在白名单内：{url}")
    try:
        infos = socket.getaddrinfo(parsed.hostname, 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise IpDetectionError(f"域名解析失败：{parsed.hostname}（{exc}）") from exc
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
            or addr.is_unspecified
        ):
            raise IpDetectionError(f"探测端点解析到受限地址，已阻断：{parsed.hostname} -> {addr}")
    return parsed.hostname  # type: ignore[return-value]


def _is_public_ipv4(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if any(n < 0 or n > 255 for n in nums):
        return False
    first = nums[0]
    if first in (10, 127) or (first == 172 and 16 <= nums[1] <= 31) or (first == 192 and nums[1] == 168):
        return False  # 私有地址，探测端点不应返回，防御性排除
    return True


def get_public_ip(force: bool = False) -> str:
    """获取当前出口公网 IPv4，失败抛出 IpDetectionError。"""
    global _cached_ip, _cached_at
    if not force and _cached_ip and time.monotonic() - _cached_at < _CACHE_TTL:
        return _cached_ip

    last_error: Exception | None = None
    for url in _ENDPOINTS:
        try:
            _assert_endpoint_safe(url)
            resp = requests.get(
                url,
                timeout=_TIMEOUT,
                headers={"User-Agent": "CloudAccess/0.1"},
                allow_redirects=False,
            )
            resp.raise_for_status()
            ip = resp.text.strip()
            if _is_public_ipv4(ip):
                _cached_ip = ip
                _cached_at = time.monotonic()
                return ip
        except requests.RequestException as exc:  # noqa: PERF203 — 逐端点重试
            last_error = exc
    raise IpDetectionError(f"公网 IP 检测失败：所有探测端点均不可达（{last_error}）")
