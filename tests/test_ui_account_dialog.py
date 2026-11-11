"""添加云账号对话框测试（run_async 用同步替身，不进线程池）。"""

import pytest
from PySide6.QtWidgets import QDialog, QLineEdit

from cloudaccess.errors import CredentialsInvalidError
from cloudaccess.models import CloudVendor
from cloudaccess.ui import account_dialog as account_dialog_module
from cloudaccess.ui.account_dialog import AccountDialog


def _sync_run_async(fn, on_done, on_fail, owner=None):
    """测试替身：同步执行任务并回调，避免真实线程。"""
    try:
        on_done(fn())
    except Exception as exc:  # noqa: BLE001 — 与 asyncui 的兜底行为一致
        on_fail(str(exc))


@pytest.fixture(autouse=True)
def _sync_async(monkeypatch):
    monkeypatch.setattr(account_dialog_module, "run_async", _sync_run_async)


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[CloudVendor, str, str]] = []

    def validate_credentials(self, vendor, ak, sk):
        self.calls.append((vendor, ak, sk))
        if sk == "demo-sk-bad":
            raise CredentialsInvalidError("演示云", "凭据无效（演示）")
        return "demo-account-uid"


@pytest.fixture
def service() -> FakeService:
    return FakeService()


def test_initial_state(qapp, service):
    dialog = AccountDialog(service=service)
    assert list(dialog._vendor_buttons) == [
        CloudVendor.ALIYUN,
        CloudVendor.TENCENT,
        CloudVendor.HUAWEI,
    ]
    assert dialog.selected_vendor() is CloudVendor.ALIYUN
    assert not dialog._btn_ok.isEnabled()
    assert dialog._sk.echoMode() == QLineEdit.EchoMode.Password  # SK 默认隐藏
    assert dialog.account_identity == ""


def test_ok_requires_both_keys(qapp, service):
    dialog = AccountDialog(service=service)
    dialog._ak.setText("demo-ak-0001")
    assert not dialog._btn_ok.isEnabled()
    dialog._sk.setText("demo-sk-0001")
    assert dialog._btn_ok.isEnabled()
    dialog._sk.clear()
    assert not dialog._btn_ok.isEnabled()


def test_sk_visibility_toggle(qapp, service):
    dialog = AccountDialog(service=service)
    dialog._btn_toggle_sk.setChecked(True)
    assert dialog._sk.echoMode() == QLineEdit.EchoMode.Normal
    assert dialog._btn_toggle_sk.text() == "隐藏"
    dialog._btn_toggle_sk.setChecked(False)
    assert dialog._sk.echoMode() == QLineEdit.EchoMode.Password
    assert dialog._btn_toggle_sk.text() == "显示"


def test_successful_submit(qapp, service):
    dialog = AccountDialog(service=service)
    dialog._vendor_buttons[CloudVendor.TENCENT].setChecked(True)
    dialog._name.setText("演示-腾讯云账号")
    dialog._ak.setText("demo-ak-0002")
    dialog._sk.setText("demo-sk-0002")

    dialog._on_confirm()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.account_identity == "demo-account-uid"
    assert dialog.account_data() == (
        CloudVendor.TENCENT,
        "演示-腾讯云账号",
        "demo-ak-0002",
        "demo-sk-0002",
    )
    assert service.calls == [(CloudVendor.TENCENT, "demo-ak-0002", "demo-sk-0002")]


def test_invalid_credentials_keeps_dialog_open(qapp, service):
    dialog = AccountDialog(service=service)
    dialog._ak.setText("demo-ak-bad")
    dialog._sk.setText("demo-sk-bad")

    dialog._on_confirm()

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not dialog._error.isHidden()
    assert "凭据验证失败" in dialog._error.text()
    assert dialog._btn_ok.isEnabled()  # 恢复可重试


def test_empty_keys_blocked_without_service_call(qapp, service):
    dialog = AccountDialog(service=service)
    dialog._ak.setText("demo-ak-0001")
    dialog._on_confirm()
    assert service.calls == []
    assert "请填写" in dialog._error.text()


def test_custom_vendor_list(qapp, service):
    dialog = AccountDialog(service=service, vendors=[CloudVendor.HUAWEI])
    assert list(dialog._vendor_buttons) == [CloudVendor.HUAWEI]
    assert dialog.selected_vendor() is CloudVendor.HUAWEI
