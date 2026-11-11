"""领域模型：账号绑定、云服务器、防火墙规则与授权状态。"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class CloudVendor(enum.StrEnum):
    """支持的云厂商。"""

    ALIYUN = "aliyun"
    TENCENT = "tencent"
    HUAWEI = "huawei"

    @property
    def display_name(self) -> str:
        return VENDOR_META[self].name_cn


@dataclass(frozen=True)
class VendorMeta:
    """厂商展示元信息。"""

    name_cn: str
    name_en: str
    color: str  # 侧栏头像/标识底色
    initial: str  # 头像中的字母


VENDOR_META: dict[CloudVendor, VendorMeta] = {
    CloudVendor.ALIYUN: VendorMeta("阿里云", "Alibaba Cloud", "#FF8A00", "A"),
    CloudVendor.TENCENT: VendorMeta("腾讯云", "Tencent Cloud", "#2D7DFF", "T"),
    CloudVendor.HUAWEI: VendorMeta("华为云", "Huawei Cloud", "#E1244B", "H"),
}


class ServerKind(enum.StrEnum):
    """服务器产品类型。"""

    ECS = "ecs"  # 云服务器
    LIGHTHOUSE = "lighthouse"  # 轻量应用服务器


class AuthStatus(enum.StrEnum):
    """针对“当前 IP”的授权状态。"""

    AUTHORIZED = "authorized"  # 检测到正确的防火墙记录
    UNAUTHORIZED = "unauthorized"  # 未检测到相关防火墙记录
    EXPIRED = "expired"  # 检测到本系统创建、但不属于当前 IP 的记录
    UNKNOWN = "unknown"  # 防火墙信息读取失败等


@dataclass
class FirewallRuleInfo:
    """规范化后的防火墙（安全组/防火墙）规则。"""

    rule_id: str
    protocol: str
    port: str  # 规范化展示，如 -1/-1、ALL、1/65535
    source_cidr: str
    description: str = ""
    is_created_by_app: bool = False  # 是否带本系统标记


@dataclass
class ServerInfo:
    """一台云服务器/轻量应用服务器的规范化信息。"""

    instance_id: str
    name: str
    region: str
    region_name: str = ""
    public_ip: str = ""
    kind: ServerKind = ServerKind.ECS
    status: AuthStatus = AuthStatus.UNAUTHORIZED
    firewall_rules: list[FirewallRuleInfo] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class AccountBinding:
    """一条已绑定的云厂商账号（AK/SK 存放于系统凭据服务）。"""

    id: str  # UUID，同时作为防火墙规则标记的短 ID 来源
    short_id: str  # 防火墙标记使用（厂商描述字段有长度限制）
    vendor: CloudVendor
    name: str  # 用户自定义显示名
    created_at: str  # ISO8601
    region_hint: str = ""  # 可选：默认区域提示（暂保留）

    def marker_prefix(self) -> str:
        """该账号创建的防火墙规则标记前缀。"""
        return marker_prefix(self.short_id)

    def marker(self, ip: str) -> str:
        """针对某 IP 创建规则时的完整标记。"""
        return marker(self.short_id, ip)


MARKER_APP = "CA"


def marker_prefix(short_id: str) -> str:
    return f"{MARKER_APP}|{short_id}|"


def marker(short_id: str, ip: str) -> str:
    return f"{MARKER_APP}|{short_id}|{ip}"
