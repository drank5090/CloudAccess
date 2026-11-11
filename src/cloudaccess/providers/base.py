"""云厂商适配器基类。

每个厂商 Provider 负责三件事：
1. 校验 AK/SK 有效性（在线验证）；
2. 列出该账号全部云服务器与轻量应用服务器，附带各自防火墙(安全组)规则；
3. 对指定服务器执行"放通所有端口(仅当前 IP)"与"撤销"。

Provider 不感知“授权状态”语义（那属于服务层），只做厂商 API 的翻译。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..models import CloudVendor, ServerInfo


class CloudProvider(ABC):
    """云厂商适配器接口。"""

    vendor: ClassVar[CloudVendor]

    def __init__(self, ak: str, sk: str) -> None:
        if not ak or not sk:
            raise ValueError("AccessKey / SecretKey 不能为空")
        self._ak = ak
        self._sk = sk

    @abstractmethod
    def validate_credentials(self) -> str:
        """在线校验凭据；成功返回账号标识（用于添加账号对话框展示）。"""

    @abstractmethod
    def list_servers(self) -> list[ServerInfo]:
        """列出全部服务器（含防火墙规则）。单个区域失败不影响整体。"""

    @abstractmethod
    def authorize(self, server: ServerInfo, cidr: str, marker: str) -> None:
        """放通所有端口：在服务器关联的全部防火墙上添加当前 IP 的全端口放行规则。"""

    @abstractmethod
    def revoke(self, server: ServerInfo, marker_prefix: str) -> None:
        """撤销授权：删除由本系统创建、标记前缀匹配的全部规则。"""
