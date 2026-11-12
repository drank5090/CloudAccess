"""阿里云 Provider 回归测试：DescribeRegions 响应解包（伪造响应体，不联网）。

回归背景：SDK 中 body.regions 是包装对象，真正列表在 body.regions.region；
直接对其 len()/迭代会抛 "object of type 'DescribeRegionsResponseBodyRegions'
has no len()"，导致添加阿里云账号时凭据验证失败。
"""

from __future__ import annotations

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
