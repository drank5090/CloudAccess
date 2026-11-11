"""领域模型测试。"""

from cloudaccess.models import (
    MARKER_APP,
    VENDOR_META,
    AccountBinding,
    AuthStatus,
    CloudVendor,
    FirewallRuleInfo,
    ServerInfo,
    ServerKind,
    marker,
    marker_prefix,
)


def test_marker_format():
    assert marker_prefix("ab12cd34") == f"{MARKER_APP}|ab12cd34|"
    assert marker("ab12cd34", "203.0.113.7") == f"{MARKER_APP}|ab12cd34|203.0.113.7"


def test_binding_marker_helpers():
    binding = AccountBinding(
        id="uuid-demo",
        short_id="ab12cd34",
        vendor=CloudVendor.ALIYUN,
        name="演示-阿里云账号",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert binding.marker_prefix() == "CA|ab12cd34|"
    assert binding.marker("198.51.100.23") == "CA|ab12cd34|198.51.100.23"


def test_vendor_meta_display_names_and_colors():
    assert CloudVendor.ALIYUN.display_name == "阿里云"
    assert CloudVendor.TENCENT.display_name == "腾讯云"
    assert CloudVendor.HUAWEI.display_name == "华为云"
    colors = {meta.color for meta in VENDOR_META.values()}
    assert len(colors) == len(VENDOR_META)  # 三个厂商配色互不相同
    for _vendor, meta in VENDOR_META.items():
        assert meta.initial
        assert meta.name_en


def test_str_enum_values():
    assert CloudVendor("aliyun") is CloudVendor.ALIYUN
    assert ServerKind("ecs") is ServerKind.ECS
    assert ServerKind("lighthouse") is ServerKind.LIGHTHOUSE
    assert AuthStatus("authorized") is AuthStatus.AUTHORIZED


def test_server_info_defaults():
    server = ServerInfo(instance_id="i-1", name="演示-服务器", region="cn-demo")
    assert server.kind is ServerKind.ECS
    assert server.status is AuthStatus.UNAUTHORIZED
    assert server.firewall_rules == []
    assert server.public_ip == ""
    assert server.extra == {}


def test_firewall_rule_info_defaults():
    rule = FirewallRuleInfo(
        rule_id="r1", protocol="ALL", port="ALL", source_cidr="203.0.113.7/32"
    )
    assert rule.description == ""
    assert rule.is_created_by_app is False
