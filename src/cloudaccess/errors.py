"""CloudAccess 异常体系。

所有可预期的错误都应归入该体系，UI 层只处理 ``CloudAccessError`` 与
``Exception`` 两个层级。
"""


class CloudAccessError(Exception):
    """应用内所有可预期错误的基类。"""


class ProviderError(CloudAccessError):
    """云厂商 API 调用失败。"""

    def __init__(self, vendor: str, message: str) -> None:
        self.vendor = vendor
        super().__init__(f"[{vendor}] {message}")


class CredentialsInvalidError(ProviderError):
    """鉴权失败（AK/SK 无效或权限不足）。"""


class AccountNotFoundError(CloudAccessError):
    """指定的账号绑定不存在。"""


class IpDetectionError(CloudAccessError):
    """公网 IP 检测失败。"""


class FirewallOpError(ProviderError):
    """防火墙规则读写失败。"""
