"""测试公共设施：离屏 Qt 环境、内存凭据仓库与异步等待工具。"""

from __future__ import annotations

import os

import pytest

from cloudaccess.storage import AccountStore, SecretStore


@pytest.fixture(scope="session")
def qapp():
    """全局 QApplication（离屏平台，测试中不会弹出真实窗口）。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class MemorySecretStore(SecretStore):
    """内存凭据仓库：替代系统 keyring，测试绝不触碰真实凭据。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set_secret(self, key: str, value: str) -> None:
        self.data[key] = value

    def get_secret(self, key: str) -> str | None:
        return self.data.get(key)

    def delete_secret(self, key: str) -> None:
        self.data.pop(key, None)


@pytest.fixture
def secrets() -> MemorySecretStore:
    return MemorySecretStore()


@pytest.fixture
def store(tmp_path, secrets) -> AccountStore:
    """使用内存凭据仓库 + 临时数据目录的账号存储。"""
    return AccountStore(secrets=secrets, data_dir=str(tmp_path / "data"))


@pytest.fixture
def pump(qapp):
    """等待线程池任务完成并派发排队信号（供 run_async 测试使用）。"""
    from PySide6.QtCore import QThreadPool

    def _pump() -> None:
        pool = QThreadPool.globalInstance()
        for _ in range(3):
            pool.waitForDone(10000)
            qapp.processEvents()

    return _pump
