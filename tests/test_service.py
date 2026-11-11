"""服务层编排测试：用 FakeProvider 替代云厂商 SDK，全程离线。"""

import pytest

from cloudaccess import service as service_module
from cloudaccess.errors import CredentialsInvalidError, FirewallOpError
from cloudaccess.models import (
    AccountBinding,
    AuthStatus,
    CloudVendor,
    FirewallRuleInfo,
    ServerInfo,
    marker,
    marker_prefix,
)
from cloudaccess.providers.base import CloudProvider
from cloudaccess.service import CloudAccessService, evaluate_status

DEMO_IP = "203.0.113.7"  # TEST-NET-3 文档地址


def _rule(description: str, cidr: str, *, app: bool = True, rule_id: str = "r0") -> FirewallRuleInfo:
    return FirewallRuleInfo(
        rule_id=rule_id,
        protocol="ALL",
        port="ALL",
        source_cidr=cidr,
        description=description,
        is_created_by_app=app,
    )


class FakeProvider(CloudProvider):
    """演示适配器：用内存字典模拟防火墙规则。"""

    vendor = CloudVendor.ALIYUN

    def __init__(self, ak: str, sk: str) -> None:
        super().__init__(ak, sk)
        self.rules: dict[str, list[FirewallRuleInfo]] = {}
        self.authorize_calls: list[tuple[str, str, str]] = []
        self.revoke_calls: list[tuple[str, str]] = []
        self.fail_on_authorize: set[str] = set()
        self.fail_validate = False

    def validate_credentials(self) -> str:
        if self.fail_validate:
            raise CredentialsInvalidError("演示云", "凭据无效（演示）")
        return "demo-account-uid"

    def list_servers(self) -> list[ServerInfo]:
        return [
            ServerInfo(instance_id=iid, name=f"演示-{iid}", region="cn-demo", public_ip="198.51.100.10")
            for iid in sorted(self.rules)
        ]

    def authorize(self, server: ServerInfo, cidr: str, marker_text: str) -> None:
        if server.instance_id in self.fail_on_authorize:
            raise FirewallOpError("演示云", "写入防火墙规则失败（演示）")
        self.authorize_calls.append((server.instance_id, cidr, marker_text))
        self.rules.setdefault(server.instance_id, []).append(
            FirewallRuleInfo(
                rule_id=f"r-{len(self.authorize_calls)}",
                protocol="ALL",
                port="ALL",
                source_cidr=cidr,
                description=marker_text,
                is_created_by_app=True,
            )
        )

    def revoke(self, server: ServerInfo, prefix: str) -> None:
        self.revoke_calls.append((server.instance_id, prefix))
        self.rules[server.instance_id] = [
            rule
            for rule in self.rules.get(server.instance_id, [])
            if not rule.description.startswith(prefix)
        ]

    def attach_firewall_rules(self, servers: list[ServerInfo]) -> None:
        for server in servers:
            server.firewall_rules = list(self.rules.get(server.instance_id, []))


class FakeProviderFactory:
    """按 (ak, sk) 复用实例，替代 ``create_provider``。"""

    def __init__(self) -> None:
        self.by_key: dict[tuple[str, str], FakeProvider] = {}

    def __call__(self, vendor: CloudVendor, ak: str, sk: str) -> FakeProvider:
        return self.provider_for(ak, sk)

    def provider_for(self, ak: str, sk: str) -> FakeProvider:
        return self.by_key.setdefault((ak, sk), FakeProvider(ak, sk))


@pytest.fixture
def factory(monkeypatch) -> FakeProviderFactory:
    impl = FakeProviderFactory()
    monkeypatch.setattr(service_module, "create_provider", impl)
    return impl


@pytest.fixture
def service(store) -> CloudAccessService:
    return CloudAccessService(store)


def _binding(short_id: str = "ab12cd34") -> AccountBinding:
    return AccountBinding(
        id="uuid-demo", short_id=short_id, vendor=CloudVendor.ALIYUN, name="演示", created_at=""
    )


def _server(iid: str = "i-demo-0001", name: str = "演示-服务器") -> ServerInfo:
    return ServerInfo(instance_id=iid, name=name, region="cn-demo", public_ip="198.51.100.10")


class TestEvaluateStatus:
    def test_authorized_when_current_ip_rule_exists(self):
        binding = _binding()
        rules = [_rule(marker(binding.short_id, DEMO_IP), f"{DEMO_IP}/32")]
        assert evaluate_status(rules, binding, DEMO_IP) is AuthStatus.AUTHORIZED

    def test_unauthorized_without_our_rules(self):
        binding = _binding()
        assert evaluate_status([], binding, DEMO_IP) is AuthStatus.UNAUTHORIZED
        foreign = _rule(marker("ffffffff", DEMO_IP), f"{DEMO_IP}/32")  # 其他账号创建
        assert evaluate_status([foreign], binding, DEMO_IP) is AuthStatus.UNAUTHORIZED

    def test_unauthorized_when_rule_not_marked_as_app(self):
        binding = _binding()
        rule = _rule(marker(binding.short_id, DEMO_IP), f"{DEMO_IP}/32", app=False)
        assert evaluate_status([rule], binding, DEMO_IP) is AuthStatus.UNAUTHORIZED

    def test_expired_when_only_old_ip_rules(self):
        binding = _binding()
        old_ip = "198.51.100.1"
        rules = [_rule(marker(binding.short_id, old_ip), f"{old_ip}/32")]
        assert evaluate_status(rules, binding, DEMO_IP) is AuthStatus.EXPIRED


class TestListServers:
    def test_assigns_status_using_store_credentials(self, service, store, factory, monkeypatch):
        monkeypatch.setattr(service_module, "get_public_ip", lambda force=False: DEMO_IP)
        binding = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
        provider = factory.provider_for("demo-ak-0001", "demo-sk-0001")
        provider.rules["i-demo-0001"] = [_rule(marker(binding.short_id, DEMO_IP), f"{DEMO_IP}/32")]
        provider.rules["i-demo-0002"] = [_rule("用户手动规则", "0.0.0.0/0", app=False)]

        servers = service.list_servers(binding)

        by_id = {s.instance_id: s for s in servers}
        assert by_id["i-demo-0001"].status is AuthStatus.AUTHORIZED
        assert by_id["i-demo-0002"].status is AuthStatus.UNAUTHORIZED
        # 凭据确实取自存储层
        assert set(factory.by_key) == {("demo-ak-0001", "demo-sk-0001")}

    def test_empty_account_returns_empty(self, service, store, factory):
        binding = store.add(CloudVendor.ALIYUN, "演示-空账号", "demo-ak-0001", "demo-sk-0001")
        assert service.list_servers(binding) == []


class TestAuthorizeRevoke:
    def test_authorize_replaces_old_ip_rules(self, service, store, factory):
        binding = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
        provider = factory.provider_for("demo-ak-0001", "demo-sk-0001")
        old_ip = "198.51.100.1"
        provider.rules["i-demo-0001"] = [
            _rule(marker(binding.short_id, old_ip), f"{old_ip}/32"),
            _rule("用户手动规则", "0.0.0.0/0", app=False),
        ]

        server = _server()
        service.authorize(binding, server, DEMO_IP)

        descs = [r.description for r in provider.rules["i-demo-0001"]]
        cids = [r.source_cidr for r in provider.rules["i-demo-0001"]]
        assert marker(binding.short_id, DEMO_IP) in descs
        assert f"{DEMO_IP}/32" in cids
        assert marker(binding.short_id, old_ip) not in descs  # 旧 IP 规则已清理
        assert "用户手动规则" in descs  # 非本系统的规则不受影响
        assert server.status is AuthStatus.AUTHORIZED
        assert provider.revoke_calls == [("i-demo-0001", marker_prefix(binding.short_id))]

    def test_revoke_keeps_manual_rules(self, service, store, factory):
        binding = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
        provider = factory.provider_for("demo-ak-0001", "demo-sk-0001")
        provider.rules["i-demo-0001"] = [
            _rule(marker(binding.short_id, DEMO_IP), f"{DEMO_IP}/32"),
            _rule("用户手动规则", "0.0.0.0/0", app=False),
        ]

        server = _server()
        service.revoke(binding, server)

        descs = [r.description for r in provider.rules["i-demo-0001"]]
        assert descs == ["用户手动规则"]
        assert server.status is AuthStatus.UNAUTHORIZED


class TestValidateAndBulk:
    def test_validate_credentials_passthrough(self, service, factory):
        result = service.validate_credentials(CloudVendor.ALIYUN, "demo-ak-0001", "demo-sk-0001")
        assert result == "demo-account-uid"

    def test_validate_invalid_credentials(self, service, factory):
        provider = factory.provider_for("demo-ak-bad", "demo-sk-bad")
        provider.fail_validate = True
        with pytest.raises(CredentialsInvalidError):
            service.validate_credentials(CloudVendor.ALIYUN, "demo-ak-bad", "demo-sk-bad")

    def test_authorize_all_reports_progress(self, service, store, factory):
        b1 = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
        b2 = store.add(CloudVendor.TENCENT, "演示-腾讯云账号", "demo-ak-0002", "demo-sk-0002")
        for ak, sk, iid in (
            ("demo-ak-0001", "demo-sk-0001", "i-demo-0001"),
            ("demo-ak-0002", "demo-sk-0002", "i-demo-0002"),
        ):
            factory.provider_for(ak, sk).rules[iid] = [_rule("占位规则", "0.0.0.0/0", app=False)]
        messages: list[str] = []

        stats = service.authorize_all([b1, b2], DEMO_IP, progress=messages.append)

        assert stats == {"total": 2, "ok": 2, "fail": 0}
        assert any("共 2 台服务器待处理" in m for m in messages)
        assert any("成功 2 台" in m for m in messages)
        p1 = factory.provider_for("demo-ak-0001", "demo-sk-0001")
        assert p1.authorize_calls == [("i-demo-0001", f"{DEMO_IP}/32", marker(b1.short_id, DEMO_IP))]

    def test_authorize_all_counts_failures(self, service, store, factory):
        binding = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
        provider = factory.provider_for("demo-ak-0001", "demo-sk-0001")
        provider.rules["i-demo-0001"] = [_rule("占位", "0.0.0.0/0", app=False)]
        provider.rules["i-demo-0002"] = [_rule("占位", "0.0.0.0/0", app=False)]
        provider.fail_on_authorize = {"i-demo-0002"}
        messages: list[str] = []

        stats = service.authorize_all_for_vendor(binding, DEMO_IP, progress=messages.append)

        assert stats == {"total": 2, "ok": 1, "fail": 1}
        assert any("失败" in m for m in messages)
