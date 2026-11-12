"""阿里云 Provider 回归测试：DescribeRegions 响应解包（伪造响应体，不联网）。

回归背景：SDK 中 body.regions 是包装对象，真正列表在 body.regions.region；
直接对其 len()/迭代会抛 "object of type 'DescribeRegionsResponseBodyRegions'
has no len()"，导致添加阿里云账号时凭据验证失败。
"""

from __future__ import annotations

from alibabacloud_ecs20140526 import models as ecs_models

from cloudaccess.providers.aliyun import AliyunProvider, _region_ids


class _Region:
    def __init__(self, region_id: str) -> None:
        self.region_id = region_id


class _Regions:
    """模拟 DescribeRegionsResponseBodyRegions 包装对象。"""

    def __init__(self, region: list[_Region]) -> None:
        self.region = region


class _Body:
    def __init__(self, regions: _Regions | None) -> None:
        self.regions = regions


class _Resp:
    def __init__(self, body: _Body) -> None:
        self.body = body


class _FakeEcsClient:
    def __init__(self, resp: _Resp) -> None:
        self._resp = resp

    def describe_regions(self, _req):  # noqa: ANN001 — 测试替身
        return self._resp


def test_region_ids_unwraps_sdk_wrapper():
    body = _Body(_Regions([_Region("cn-hangzhou"), _Region("cn-beijing")]))
    assert _region_ids(body) == ["cn-hangzhou", "cn-beijing"]


def test_region_ids_handles_missing_and_empty():
    assert _region_ids(_Body(None)) == []
    assert _region_ids(_Body(_Regions([]))) == []
    assert _region_ids(_Body(_Regions([_Region("")]))) == []  # 空 ID 被过滤


def test_validate_credentials_and_list_regions(monkeypatch):
    provider = AliyunProvider("demo-ak-0001", "demo-sk-0001")
    resp = _Resp(_Body(_Regions([_Region("cn-hangzhou"), _Region("ap-southeast-1")])))
    monkeypatch.setattr(provider, "_ecs_client", lambda _region: _FakeEcsClient(resp))

    assert provider.validate_credentials() == "阿里云 · 2 个可用区域"
    assert provider._list_regions() == ["cn-hangzhou", "ap-southeast-1"]


# ---------- _ecs_to_server：repeated 字段包装解包（回归：public_ip_address 不可迭代） ----------


def _ecs_instance(public_ips: list[str] | None, sg_ids: list[str] | None, eip: str | None):
    """用真实 SDK 模型类构造 DescribeInstances 列表项。"""
    return ecs_models.DescribeInstancesResponseBodyInstancesInstance(
        instance_id="i-bp1demo",
        instance_name="demo-web",
        public_ip_address=ecs_models.DescribeInstancesResponseBodyInstancesInstancePublicIpAddress(
            ip_address=public_ips
        ),
        security_group_ids=ecs_models.DescribeInstancesResponseBodyInstancesInstanceSecurityGroupIds(
            security_group_id=sg_ids
        ),
        eip_address=ecs_models.DescribeInstancesResponseBodyInstancesInstanceEipAddress(
            ip_address=eip
        ),
    )


def test_ecs_to_server_unwraps_public_ip_and_security_groups():
    provider = AliyunProvider("demo-ak-0001", "demo-sk-0001")
    server = provider._ecs_to_server("cn-hangzhou", _ecs_instance(["1.2.3.4"], ["sg-a", "sg-b"], None))
    assert server.public_ip == "1.2.3.4"
    assert server.extra["security_group_ids"] == "sg-a,sg-b"


def test_ecs_to_server_falls_back_to_eip():
    provider = AliyunProvider("demo-ak-0001", "demo-sk-0001")
    server = provider._ecs_to_server("cn-hangzhou", _ecs_instance(None, ["sg-a"], "5.6.7.8"))
    assert server.public_ip == "5.6.7.8"


def test_ecs_to_server_handles_all_empty():
    provider = AliyunProvider("demo-ak-0001", "demo-sk-0001")
    server = provider._ecs_to_server("cn-hangzhou", _ecs_instance(None, None, None))
    assert server.public_ip == ""
    assert server.extra["security_group_ids"] == ""
    assert server.name == "demo-web"
