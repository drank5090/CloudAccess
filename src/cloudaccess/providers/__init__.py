"""Provider 注册表：厂商 → 适配器实现。"""

from __future__ import annotations

from ..models import CloudVendor
from .aliyun import AliyunProvider
from .base import CloudProvider
from .huawei import HuaweiProvider
from .tencent import TencentProvider

PROVIDERS: dict[CloudVendor, type[CloudProvider]] = {
    AliyunProvider.vendor: AliyunProvider,
    TencentProvider.vendor: TencentProvider,
    HuaweiProvider.vendor: HuaweiProvider,
}


def create_provider(vendor: CloudVendor, ak: str, sk: str) -> CloudProvider:
    """按厂商构造适配器实例。"""
    try:
        return PROVIDERS[vendor](ak, sk)
    except KeyError as exc:
        raise ValueError(f"不支持的云厂商：{vendor}") from exc
