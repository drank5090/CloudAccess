"""演示模式数据源（离线、无凭据）：用于截图生成与 UI 冒烟。

FakeStore / FakeService 与 AccountStore / CloudAccessService 同接口（鸭子类型），
所有数据为内存态、明显假的占位（demo-ak-0001 等），不触碰系统凭据服务与网络。
"""

from __future__ import annotations

from .models import (
    AccountBinding,
    CloudVendor,
    FirewallRuleInfo,
    ServerInfo,
    ServerKind,
    marker,
)
from .service import evaluate_status

DEMO_IP = "203.0.113.7"  # TEST-NET-3 文档专用地址，非真实出口


def _binding(vendor: CloudVendor, name: str, short_id: str) -> AccountBinding:
    return AccountBinding(
        id=f"demo-{short_id}",
        short_id=short_id,
        vendor=vendor,
        name=name,
        created_at="2026-11-12T00:00:00+00:00",
    )


class FakeStore:
    """内存版账号存储。"""

    def __init__(self) -> None:
        self._bindings = [
            _binding(CloudVendor.ALIYUN, "演示-阿里云主账号", "aa11bb22"),
            _binding(CloudVendor.TENCENT, "演示-腾讯云生产", "cc33dd44"),
            _binding(CloudVendor.HUAWEI, "演示-华为云测试", "ee55ff66"),
        ]

    def list(self) -> list[AccountBinding]:
        return list(self._bindings)

    def get(self, binding_id: str) -> AccountBinding:
        return next(b for b in self._bindings if b.id == binding_id)

    def add(self, vendor: CloudVendor, name: str, ak: str, sk: str, region_hint: str = "") -> AccountBinding:
        b = _binding(vendor, name or vendor.display_name, f"{len(self._bindings)}0aa11bb")
        self._bindings.append(b)
        return b

    def update_name(self, binding_id: str, name: str) -> None:
        self.get(binding_id).name = name

    def remove(self, binding_id: str) -> None:
        self._bindings = [b for b in self._bindings if b.id != binding_id]

    def get_ak(self, binding: AccountBinding) -> str:
        return "demo-ak-0001"

    def get_sk(self, binding: AccountBinding) -> str:
        return "demo-sk-0001"


def _rule(binding: AccountBinding, ip: str) -> FirewallRuleInfo:
    return FirewallRuleInfo(
        rule_id="demo-rule",
        protocol="ALL",
        port="-1/-1",
        source_cidr=f"{ip}/32",
        description=marker(binding.short_id, ip),
        is_created_by_app=True,
    )


class FakeService:
    """内存版业务服务：预置三类授权状态，授权/撤销直接改内存规则。"""

    def __init__(self, store: FakeStore) -> None:
        self._store = store
        self._servers: dict[str, list[ServerInfo]] = {}
        for i, b in enumerate(store.list()):
            kind = ServerKind.LIGHTHOUSE if i == 1 else ServerKind.ECS
            servers = [
                self._make_server(b, f"{b.vendor.value}-web-{n:02d}", kind, state)
                for n, state in enumerate(
                    ("authorized", "unauthorized", "expired"), start=1
                )
            ]
            self._servers[b.id] = servers

    @staticmethod
    def _make_server(
        binding: AccountBinding, name: str, kind: ServerKind, state: str
    ) -> ServerInfo:
        s = ServerInfo(
            instance_id=f"demo-inst-{name}",
            name=name,
            region="cn-hangzhou" if binding.vendor is CloudVendor.ALIYUN else ("ap-guangzhou" if binding.vendor is CloudVendor.TENCENT else "cn-north-4"),
            public_ip="198.51.100.10",
            kind=kind,
        )
        if state == "authorized":
            s.firewall_rules.append(_rule(binding, DEMO_IP))
        elif state == "expired":
            s.firewall_rules.append(_rule(binding, "198.51.100.99"))
        s.status = evaluate_status(s.firewall_rules, binding, DEMO_IP)
        return s

    def list_servers(self, binding: AccountBinding, current_ip: str | None = None) -> list[ServerInfo]:
        out = self._servers.get(binding.id, [])
        ip = current_ip or DEMO_IP
        for s in out:
            s.status = evaluate_status(s.firewall_rules, binding, ip)
        return list(out)

    def validate_credentials(self, vendor: CloudVendor, ak: str, sk: str) -> str:
        return f"{vendor.display_name} · 演示模式校验通过"

    def _apply(self, binding: AccountBinding, server: ServerInfo, ip: str) -> None:
        server.firewall_rules = [
            r for r in server.firewall_rules
            if not (r.is_created_by_app and r.description.startswith(f"CA|{binding.short_id}|"))
        ]
        server.firewall_rules.append(_rule(binding, ip))
        server.status = evaluate_status(server.firewall_rules, binding, ip)

    def authorize(self, binding: AccountBinding, server: ServerInfo, current_ip: str) -> None:
        self._apply(binding, server, current_ip)

    def revoke(self, binding: AccountBinding, server: ServerInfo) -> None:
        server.firewall_rules = [
            r for r in server.firewall_rules
            if not (r.is_created_by_app and r.description.startswith(f"CA|{binding.short_id}|"))
        ]
        server.status = evaluate_status(server.firewall_rules, binding, DEMO_IP)

    def authorize_all(self, bindings: list[AccountBinding], current_ip: str, progress=None) -> dict[str, int]:
        total = ok = 0
        for b in bindings:
            for s in self.list_servers(b, current_ip):
                total += 1
                self._apply(b, s, current_ip)
                ok += 1
        return {"total": total, "ok": ok, "fail": 0}

    def authorize_all_for_vendor(self, binding: AccountBinding, current_ip: str, progress=None) -> dict[str, int]:
        return self.authorize_all([binding], current_ip, progress)
