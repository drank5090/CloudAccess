"""服务层：编排“列出服务器 → 判定授权状态 → 授权/撤销”完整链路。

状态语义（针对当前公网出口 IP）：
- AUTHORIZED  ：存在本系统创建、且源地址 = 当前 IP 的规则；
- UNAUTHORIZED：不存在本系统创建的任何规则；
- EXPIRED     ：存在本系统创建、但源地址 ≠ 当前 IP 的规则（出口 IP 已变化）。
"""

from __future__ import annotations

import concurrent.futures as cf
from collections.abc import Callable

from .errors import CloudAccessError
from .iputil import get_public_ip
from .models import (
    AccountBinding,
    AuthStatus,
    CloudVendor,
    FirewallRuleInfo,
    ServerInfo,
    marker,
    marker_prefix,
)
from .providers import create_provider
from .storage import AccountStore

_MAX_WORKERS = 8


def evaluate_status(rules: list[FirewallRuleInfo], binding: AccountBinding, current_ip: str) -> AuthStatus:
    """根据规则集、账号标记与当前 IP 判定授权状态。"""
    ours = [
        r for r in rules
        if r.is_created_by_app and r.description.startswith(marker_prefix(binding.short_id))
    ]
    if not ours:
        return AuthStatus.UNAUTHORIZED
    if any(r.source_cidr == f"{current_ip}/32" for r in ours):
        return AuthStatus.AUTHORIZED
    return AuthStatus.EXPIRED


class CloudAccessService:
    """面向 UI 的完整业务服务。"""

    def __init__(self, store: AccountStore) -> None:
        self._store = store

    def _provider(self, binding: AccountBinding):
        return create_provider(binding.vendor, self._store.get_ak(binding), self._store.get_sk(binding))

    # ---------- 查询 ----------

    def list_servers(self, binding: AccountBinding, current_ip: str | None = None) -> list[ServerInfo]:
        """列出某账号绑定的全部服务器并判定授权状态。"""
        provider = self._provider(binding)
        servers = provider.list_servers()
        if not servers:
            return []
        provider.attach_firewall_rules(servers)
        ip = current_ip or get_public_ip()
        for s in servers:
            s.status = evaluate_status(s.firewall_rules, binding, ip)
        return servers

    def validate_credentials(self, vendor: CloudVendor, ak: str, sk: str) -> str:
        """添加账号时的在线验证，返回账号标识描述。"""
        return create_provider(vendor, ak, sk).validate_credentials()

    # ---------- 授权 / 撤销 ----------

    def authorize(self, binding: AccountBinding, server: ServerInfo, current_ip: str) -> None:
        """对单台服务器放通所有端口（仅当前 IP），并清理该账号旧 IP 的过期规则。"""
        provider = self._provider(binding)
        cidr = f"{current_ip}/32"
        # 先清理本账号在该服务器上的旧规则（含旧 IP 的过期规则），再创建当前 IP 规则
        provider.revoke(server, marker_prefix(binding.short_id))
        provider.authorize(server, cidr, marker(binding.short_id, current_ip))
        server.firewall_rules = []
        provider.attach_firewall_rules([server])
        server.status = evaluate_status(server.firewall_rules, binding, current_ip)

    def revoke(self, binding: AccountBinding, server: ServerInfo) -> None:
        """撤销单台服务器的授权（删除本系统创建的全部规则）。"""
        provider = self._provider(binding)
        provider.revoke(server, marker_prefix(binding.short_id))
        server.firewall_rules = []
        provider.attach_firewall_rules([server])
        server.status = evaluate_status(server.firewall_rules, binding, get_public_ip())

    def authorize_all(
        self,
        bindings: list[AccountBinding],
        current_ip: str,
        progress: Callable[[str], None] | None = None,
    ) -> dict[str, int]:
        """对一批账号绑定的全部服务器执行授权（“所有服务器一键授权”）。"""
        return self._bulk(bindings, current_ip, progress, authorize=True)

    def authorize_all_for_vendor(
        self, binding: AccountBinding, current_ip: str, progress: Callable[[str], None] | None = None
    ) -> dict[str, int]:
        """对单个云厂商账号的全部服务器执行授权。"""
        return self._bulk([binding], current_ip, progress, authorize=True)

    # ---------- 内部 ----------

    def _bulk(
        self,
        bindings: list[AccountBinding],
        current_ip: str,
        progress: Callable[[str], None] | None,
        authorize: bool,
    ) -> dict[str, int]:
        stats = {"total": 0, "ok": 0, "fail": 0}
        servers_by_binding: list[tuple[AccountBinding, list[ServerInfo]]] = []
        for b in bindings:
            provider = self._provider(b)
            servers = provider.list_servers()
            if not servers:
                continue
            provider.attach_firewall_rules(servers)
            servers_by_binding.append((b, servers))
            stats["total"] += len(servers)
        if progress and stats["total"]:
            progress(f"共 {stats['total']} 台服务器待处理")

        def work(item: tuple[AccountBinding, ServerInfo]) -> None:
            b, s = item
            try:
                self.authorize(b, s, current_ip)
                stats["ok"] += 1
            except CloudAccessError as exc:
                stats["fail"] += 1
                if progress:
                    progress(f"失败：{b.name} / {s.name}: {exc}")

        items = [(b, s) for b, servers in servers_by_binding for s in servers]
        with cf.ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            list(pool.map(work, items))
        if progress:
            progress(f"完成：成功 {stats['ok']} 台，失败 {stats['fail']} 台")
        return stats
