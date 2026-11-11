"""账号绑定的本地持久化。

设计约定（安全）：
- 元数据（账号名/厂商/时间）存放于应用数据目录的 JSON 文件；
- AccessKeyId 与 AccessKeySecret 一律存放于系统凭据服务（Windows 凭据管理器 /
  macOS Keychain / Linux Secret Service），绝不落盘为明文文件。
- 本模块不引入密钥字面量；测试通过注入内存 keyring 后端完成。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import keyring
import platformdirs

from .errors import AccountNotFoundError
from .models import AccountBinding, CloudVendor

SERVICE_NAME = "CloudAccess"
_FILENAME = "accounts.json"
_FILENAME_TMP = "accounts.json.tmp"
_ALLOWED_FILES = frozenset({_FILENAME, _FILENAME_TMP})


class SecretStore:
    """对 keyring 的薄封装，便于测试替换。"""

    def set_secret(self, key: str, value: str) -> None:
        keyring.set_password(SERVICE_NAME, key, value)

    def get_secret(self, key: str) -> str | None:
        return keyring.get_password(SERVICE_NAME, key)

    def delete_secret(self, key: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class AccountStore:
    """账号绑定集合：列表、增删改与凭据读写。"""

    def __init__(self, secrets: SecretStore | None = None, data_dir: str | None = None) -> None:
        self._secrets = secrets or SecretStore()
        dir_raw = data_dir or platformdirs.user_data_dir("CloudAccess", appauthor=False)
        self._dir: Path = Path(dir_raw).resolve()
        self._bindings: list[AccountBinding] = []
        self._load()

    # ---------- 路径安全 ----------

    def _member_path(self, name: str) -> Path:
        """受控路径构造：文件名白名单 + resolve + 目录包含校验。

        任何对数据目录内文件的访问都必须经由本方法，保证路径永远
        落在校验过的数据目录内部，杜绝 ``../`` 之类的穿越。
        """
        if name not in _ALLOWED_FILES:
            raise ValueError(f"不允许的文件名：{name!r}")
        base = self._dir.resolve()
        full = (base / name).resolve()
        if not full.is_relative_to(base):
            raise ValueError(f"路径越界：{name!r}")
        return full

    # ---------- 持久化 ----------

    @property
    def path(self) -> Path:
        return self._member_path(_FILENAME)

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._bindings = []
            return
        except (OSError, json.JSONDecodeError):
            # 损坏的元数据文件不应导致启动失败；凭据仍在凭据服务中不受影响
            self._bindings = []
            return
        self._bindings = [
            AccountBinding(
                id=item["id"],
                short_id=item["short_id"],
                vendor=CloudVendor(item["vendor"]),
                name=item["name"],
                created_at=item.get("created_at", ""),
                region_hint=item.get("region_hint", ""),
            )
            for item in raw
        ]

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        tmp = self._member_path(_FILENAME_TMP)
        tmp.write_text(
            json.dumps([asdict(b) for b in self._bindings], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # ---------- 绑定管理 ----------

    def list(self) -> list[AccountBinding]:
        """返回全部绑定（新添加的在前）。"""
        return list(reversed(self._bindings))

    def get(self, binding_id: str) -> AccountBinding:
        for b in self._bindings:
            if b.id == binding_id:
                return b
        raise AccountNotFoundError(binding_id)

    def add(self, vendor: CloudVendor, name: str, ak: str, sk: str, region_hint: str = "") -> AccountBinding:
        """新增绑定并写入凭据服务。"""
        binding = AccountBinding(
            id=str(uuid.uuid4()),
            short_id=uuid.uuid4().hex[:8],
            vendor=vendor,
            name=name.strip() or vendor.display_name,
            created_at=_now_iso(),
            region_hint=region_hint,
        )
        self._secrets.set_secret(self._ak_key(binding), ak.strip())
        self._secrets.set_secret(self._sk_key(binding), sk.strip())
        self._bindings.append(binding)
        self._save()
        return binding

    def update_name(self, binding_id: str, name: str) -> None:
        b = self.get(binding_id)
        b.name = name.strip() or b.name
        self._save()

    def remove(self, binding_id: str) -> None:
        b = self.get(binding_id)
        self._secrets.delete_secret(self._ak_key(b))
        self._secrets.delete_secret(self._sk_key(b))
        self._bindings.remove(b)
        self._save()

    # ---------- 凭据读写 ----------

    @staticmethod
    def _ak_key(b: AccountBinding) -> str:
        return f"{b.id}:ak"

    @staticmethod
    def _sk_key(b: AccountBinding) -> str:
        return f"{b.id}:sk"

    def get_ak(self, binding: AccountBinding) -> str:
        return self._secrets.get_secret(self._ak_key(binding)) or ""

    def get_sk(self, binding: AccountBinding) -> str:
        return self._secrets.get_secret(self._sk_key(binding)) or ""
