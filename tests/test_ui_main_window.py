"""主窗口测试：FakeService + 内存存储，全程离线、离屏。

说明：为避免离屏环境下模态对话框阻塞测试，所有可能弹出的
QMessageBox / QInputDialog 均被 monkeypatch 替换。
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from cloudaccess.errors import IpDetectionError, ProviderError
from cloudaccess.models import AuthStatus, CloudVendor, ServerInfo, ServerKind
from cloudaccess.storage import AccountStore
from cloudaccess.ui import main_window as main_window_module
from cloudaccess.ui.main_window import MainWindow
from cloudaccess.ui.theme import SUCCESS, TEXT_2, WARN

DEMO_IP = "203.0.113.7"  # TEST-NET-3 文档地址


class FakeService:
    """演示服务：状态语义与真实 service 一致，但不访问网络与云 API。"""

    def __init__(self) -> None:
        self.servers_by_binding: dict[str, list[ServerInfo]] = {}
        self.authorize_calls: list[tuple[str, str, str]] = []
        self.revoke_calls: list[tuple[str, str]] = []
        self.fail_instance: str | None = None

    def list_servers(self, binding, current_ip=None):
        return list(self.servers_by_binding.get(binding.id, []))

    def validate_credentials(self, vendor, ak, sk):
        return "demo-account-uid"

    def authorize(self, binding, server, current_ip):
        if self.fail_instance and server.instance_id == self.fail_instance:
            raise ProviderError("演示云", "写入防火墙规则失败（演示）")
        self.authorize_calls.append((binding.id, server.instance_id, current_ip))
        server.status = AuthStatus.AUTHORIZED

    def revoke(self, binding, server):
        self.revoke_calls.append((binding.id, server.instance_id))
        server.status = AuthStatus.UNAUTHORIZED

    def authorize_all(self, bindings, current_ip, progress=None):
        total = ok = fail = 0
        for binding in bindings:
            for server in self.list_servers(binding, current_ip):
                total += 1
                try:
                    self.authorize(binding, server, current_ip)
                except ProviderError as exc:
                    fail += 1
                    if progress:
                        progress(f"失败：{server.name}（{exc}）")
                else:
                    ok += 1
        if progress:
            progress(f"完成：成功 {ok} 台，失败 {fail} 台")
        return {"total": total, "ok": ok, "fail": fail}

    def authorize_all_for_vendor(self, binding, current_ip, progress=None):
        return self.authorize_all([binding], current_ip, progress)


@pytest.fixture
def ctx(qapp, monkeypatch, tmp_path, secrets):
    """构造已注入演示数据通道的窗口：返回 (window, store, service)。"""
    monkeypatch.setattr(main_window_module, "get_public_ip", lambda force=False: DEMO_IP)
    store = AccountStore(secrets=secrets, data_dir=str(tmp_path / "data"))
    service = FakeService()
    window = MainWindow(service=service, store=store)
    yield window, store, service
    window.close()


def _prepare(window, store, service, pump):
    """注入两个演示账号（阿里云 3 台 + 腾讯云 1 台）并刷新界面。"""
    b_t = store.add(CloudVendor.TENCENT, "演示-腾讯云账号", "demo-ak-0002", "demo-sk-0002")
    b_a = store.add(CloudVendor.ALIYUN, "演示-阿里云账号", "demo-ak-0001", "demo-sk-0001")
    service.servers_by_binding[b_t.id] = [
        ServerInfo(
            instance_id="i-demo-9001",
            name="演示-腾讯-ECS",
            region="ap-demo",
            public_ip="198.51.100.20",
        ),
    ]
    service.servers_by_binding[b_a.id] = [
        ServerInfo(
            instance_id="i-demo-0001",
            name="演示-ECS-01",
            region="cn-demo",
            region_name="演示区域",
            public_ip="198.51.100.10",
        ),
        ServerInfo(
            instance_id="i-demo-0002",
            name="演示-轻量-01",
            region="cn-demo",
            kind=ServerKind.LIGHTHOUSE,
            status=AuthStatus.EXPIRED,
        ),
        ServerInfo(
            instance_id="i-demo-0003",
            name="演示-ECS-02",
            region="cn-demo",
            public_ip="198.51.100.11",
            status=AuthStatus.AUTHORIZED,
        ),
    ]
    window.reload_accounts()
    pump()
    return b_a, b_t


def _cell_button(window, row: int, text: str) -> QPushButton:
    box = window._table.cellWidget(row, 5)
    buttons = [b for b in box.findChildren(QPushButton) if b.text() == text]
    assert buttons, f"第 {row} 行找不到按钮「{text}」"
    return buttons[0]


# ---------- 基础结构与账号列表 ----------


def test_frameless_and_placeholder(ctx):
    window, _store, _service = ctx
    assert bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
    assert window._stack.currentIndex() == 0  # 无账号 → 占位页
    assert window._account_list.count() == 0


def test_first_account_selected_and_loaded(ctx, pump):
    window, _store, _service = ctx
    b_a, _b_t = _prepare(window, _store, _service, pump)
    assert window._account_list.count() == 2
    assert window._stack.currentIndex() == 1
    assert window.current_binding() is b_a  # 新添加的在前
    assert window._panel_title.text() == "演示-阿里云账号"
    assert DEMO_IP in window._panel_subtitle.text()
    assert window._table.rowCount() == 3
    assert window._table.item(0, 0).text() == "演示-ECS-01"
    assert window._table.item(0, 1).text() == "云服务器 ECS"
    assert window._table.item(1, 1).text() == "轻量应用服务器"
    assert window._table.item(1, 3).text() == "—"  # 无公网 IP
    assert window._table.item(0, 2).text() == "演示区域 · cn-demo"


def test_switch_account_reloads_servers(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    window._account_list.setCurrentRow(1)  # 腾讯账号
    pump()
    assert window._panel_title.text() == "演示-腾讯云账号"
    assert window._table.rowCount() == 1
    assert window._table.item(0, 0).text() == "演示-腾讯-ECS"


def test_demo_accounts_use_placeholder_keys(ctx):
    window, store, service = ctx
    for binding in store.list():
        assert binding.name.startswith("演示-")
        assert store.get_ak(binding).startswith("demo-ak-")
        assert store.get_sk(binding).startswith("demo-sk-")


# ---------- 状态与行内操作 ----------


def test_status_column_mapping(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    assert window._table.item(0, 4).text() == "未授权"
    assert window._table.item(1, 4).text() == "授权过期"
    assert window._table.item(2, 4).text() == "已授权"
    assert window._table.item(0, 4).foreground().color().name().lower() == TEXT_2.lower()
    assert window._table.item(1, 4).foreground().color().name().lower() == WARN.lower()
    assert window._table.item(2, 4).foreground().color().name().lower() == SUCCESS.lower()


def test_row_action_buttons_match_status(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    # 未授权：只有「授权」
    assert not _cell_button(window, 0, "授权").isHidden()
    assert _cell_button(window, 0, "取消授权").isHidden()
    # 授权过期：两个都有
    assert not _cell_button(window, 1, "授权").isHidden()
    assert not _cell_button(window, 1, "取消授权").isHidden()
    # 已授权：只有「取消授权」
    assert _cell_button(window, 2, "授权").isHidden()
    assert not _cell_button(window, 2, "取消授权").isHidden()


def test_authorize_row(ctx, pump):
    window, store, service = ctx
    b_a, _b_t = _prepare(window, store, service, pump)
    _cell_button(window, 0, "授权").click()
    pump()
    assert service.authorize_calls == [(b_a.id, "i-demo-0001", DEMO_IP)]
    assert window._table.item(0, 4).text() == "已授权"
    assert "演示-ECS-01" in window._panel_subtitle.text()


def test_authorize_row_failure_shows_warning(ctx, pump, monkeypatch):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    warnings: list[str] = []
    monkeypatch.setattr(
        main_window_module.QMessageBox, "warning", lambda *a, **k: warnings.append(str(a))
    )
    service.fail_instance = "i-demo-0001"
    _cell_button(window, 0, "授权").click()
    pump()
    assert warnings
    assert window._table.item(0, 4).text() == "未授权"  # 状态保持原样
    assert "操作失败" in window._panel_subtitle.text()


def test_revoke_row(ctx, pump):
    window, store, service = ctx
    b_a, _b_t = _prepare(window, store, service, pump)
    _cell_button(window, 2, "取消授权").click()  # 第 3 行初始为已授权
    pump()
    assert service.revoke_calls == [(b_a.id, "i-demo-0003")]
    assert window._table.item(2, 4).text() == "未授权"


# ---------- 批量操作 ----------


def test_authorize_current_account(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    window._btn_auth_all.click()
    pump()
    instances = {iid for _bid, iid, _ip in service.authorize_calls}
    assert instances == {"i-demo-0001", "i-demo-0002", "i-demo-0003"}
    assert all(ip == DEMO_IP for _b, _i, ip in service.authorize_calls)
    assert "批量操作完成" in window._panel_subtitle.text()
    assert window._table.item(0, 4).text() == "已授权"


def test_authorize_current_account_counts_failures(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    service.fail_instance = "i-demo-0002"
    window._btn_auth_all.click()
    pump()
    assert "失败 1 台" in window._panel_subtitle.text()
    assert window._table.item(1, 4).text() == "授权过期"  # 失败的服务器保持原状态


def test_revoke_current_account(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    window._btn_revoke_all.click()
    pump()
    assert len(service.revoke_calls) == 3
    assert window._table.item(0, 4).text() == "未授权"


def test_authorize_all_accounts_with_confirm(ctx, pump, monkeypatch):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *a, **k: main_window_module.QMessageBox.StandardButton.Yes,
    )
    window._btn_all.click()
    pump()
    assert len(service.authorize_calls) == 4  # 阿里云 3 台 + 腾讯云 1 台
    assert "批量操作完成" in window._panel_subtitle.text()


def test_authorize_all_accounts_cancelled(ctx, pump, monkeypatch):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *a, **k: main_window_module.QMessageBox.StandardButton.No,
    )
    window._btn_all.click()
    pump()
    assert service.authorize_calls == []


# ---------- 刷新与异常 ----------


def test_refresh_failure_shows_error_and_disables_actions(ctx, pump, monkeypatch):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    warnings: list[str] = []

    def _raise(force=False):
        raise IpDetectionError("演示：所有探测端点均不可达")

    monkeypatch.setattr(main_window_module.QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    monkeypatch.setattr(main_window_module, "get_public_ip", _raise)
    window._btn_refresh.click()
    pump()
    assert warnings
    assert "加载失败" in window._panel_subtitle.text()
    assert not window._btn_auth_all.isEnabled()
    assert not window._btn_revoke_all.isEnabled()


def test_stale_refresh_result_ignored(ctx, pump):
    window, store, service = ctx
    _prepare(window, store, service, pump)
    window._on_refresh_done(0, ("198.51.100.99", []))  # token=0 一定过期
    assert window._table.rowCount() == 3  # 现有内容未被覆盖


# ---------- 账号管理 ----------


def test_rename_account(ctx, pump, monkeypatch):
    window, store, service = ctx
    b_a, _b_t = _prepare(window, store, service, pump)
    monkeypatch.setattr(
        main_window_module.QInputDialog, "getText", lambda *a, **k: ("演示-改名", True)
    )
    window._rename_binding(b_a)
    assert store.get(b_a.id).name == "演示-改名"
    texts = [window._account_list.item(i).text() for i in range(window._account_list.count())]
    assert "演示-改名" in texts


def test_rename_cancelled_keeps_name(ctx, pump, monkeypatch):
    window, store, service = ctx
    b_a, _b_t = _prepare(window, store, service, pump)
    monkeypatch.setattr(
        main_window_module.QInputDialog, "getText", lambda *a, **k: ("演示-不该生效", False)
    )
    window._rename_binding(b_a)
    assert store.get(b_a.id).name == "演示-阿里云账号"


def test_remove_account(ctx, pump, monkeypatch):
    window, store, service = ctx
    b_a, b_t = _prepare(window, store, service, pump)
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "question",
        lambda *a, **k: main_window_module.QMessageBox.StandardButton.Yes,
    )
    window._remove_binding(b_a)
    assert [b.id for b in store.list()] == [b_t.id]
    assert window._account_list.count() == 1
    pump()  # 删除后自动选中剩余账号并异步加载
    assert window.current_binding() is b_t
    assert window._panel_title.text() == "演示-腾讯云账号"
    assert window._table.rowCount() == 1
