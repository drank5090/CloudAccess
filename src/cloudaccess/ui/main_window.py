"""主窗口：左侧云账号侧栏 + 右侧服务器防火墙面板。

界面流程：
1. 侧栏列出全部账号绑定（顶部搜索框 + 加号），点击后加载该账号的服务器；
2. 顶部面板显示当前公网 IP 与服务器数量，提供“一键放行 / 取消全部授权”；
3. 每行服务器按授权状态提供“授权 / 取消授权”行内操作；
4. 所有云 API 调用经 ``run_async`` 放入线程池，结果用信号回主线程。
"""

from __future__ import annotations

from functools import partial

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..errors import CloudAccessError
from ..iputil import get_public_ip
from ..models import VENDOR_META, AccountBinding, AuthStatus, ServerInfo, ServerKind
from ..service import CloudAccessService
from ..storage import AccountStore
from .account_dialog import AccountDialog
from .asyncui import run_async
from .theme import (
    ACCENT_SOFT,
    DANGER,
    INPUT_BG,
    RADIUS,
    SUCCESS,
    TEXT,
    TEXT_2,
    WARN,
    paint_vendor_avatar,
)
from .title_bar import TitleBar

STATUS_TEXT: dict[AuthStatus, str] = {
    AuthStatus.AUTHORIZED: "已授权",
    AuthStatus.UNAUTHORIZED: "未授权",
    AuthStatus.EXPIRED: "授权过期",
    AuthStatus.UNKNOWN: "未知",
}
STATUS_COLOR: dict[AuthStatus, str] = {
    AuthStatus.AUTHORIZED: SUCCESS,
    AuthStatus.UNAUTHORIZED: TEXT_2,
    AuthStatus.EXPIRED: WARN,
    AuthStatus.UNKNOWN: DANGER,
}

COLUMNS = ("服务器名称", "类型", "区域", "公网 IP", "授权状态", "操作")
COL_STATUS = 4
COL_ACTION = 5


class _ProgressBridge(QObject):
    """把工作线程里的进度文本安全地搬运回主线程。"""

    message = Signal(str)


class AccountItemDelegate(QStyledItemDelegate):
    """侧栏账号项：圆角选中背景 + 厂商头像 + 账号名。"""

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(6, 3, -6, -3)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS, RADIUS)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            painter.fillPath(path, QColor(ACCENT_SOFT))
        elif option.state & QStyle.StateFlag.State_MouseOver:
            painter.fillPath(path, QColor(INPUT_BG))

        vendor = index.data(Qt.ItemDataRole.UserRole)
        meta = VENDOR_META.get(vendor)
        avatar_rect = QRectF(rect.left() + 6, rect.center().y() - 14, 28, 28)
        if meta is not None:
            paint_vendor_avatar(painter, avatar_rect, meta.color, meta.initial, selected)

        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text_left = avatar_rect.right() + 10
        text_rect = QRectF(text_left, rect.top(), max(rect.right() - text_left, 0), rect.height())
        font = painter.font()
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        elided = option.fontMetrics.elidedText(
            name, Qt.TextElideMode.ElideRight, int(text_rect.width())
        )
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width() or 200, 46)


class MainWindow(QMainWindow):
    """应用主窗口（无边框）。"""

    def __init__(
        self,
        service: CloudAccessService,
        store: AccountStore,
        parent: QWidget | None = None,
        demo: bool = False,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._store = store
        self._demo = demo
        self._bindings: list[AccountBinding] = []
        self._current_id: str | None = None
        self._servers: list[ServerInfo] = []
        self._current_ip: str | None = None
        self._busy = False
        self._view_token = 0  # 丢弃过期异步结果
        self._progress = _ProgressBridge(self)

        self.setWindowTitle("CloudAccess · 多云服务器防火墙放通")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(980, 640)
        self.resize(1120, 720)

        central = QWidget(self)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(TitleBar(self))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)
        body.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)
        self._stack.addWidget(self._build_placeholder_page())
        self._stack.addWidget(self._build_server_panel())

        self._progress.message.connect(self._on_progress_message)
        self.reload_accounts()

    # ---------- 界面构建 ----------

    def _build_sidebar(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("Sidebar")
        frame.setFixedWidth(236)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(8)

        title = QLabel("云账号")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        # 搜索框 + 添加按钮（需求：列表最上方为搜索框与加号）
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        self._search = QLineEdit(frame)
        self._search.setPlaceholderText("搜索云厂商 / 账号")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_account_filter)
        search_row.addWidget(self._search, 1)

        self._btn_add = QPushButton("+")
        self._btn_add.setObjectName("PrimaryButton")
        self._btn_add.setFixedSize(34, 34)
        self._btn_add.setToolTip("添加云厂商账号")
        self._btn_add.clicked.connect(self._add_account_clicked)
        search_row.addWidget(self._btn_add)
        layout.addLayout(search_row)

        self._account_list = QListWidget(frame)
        self._account_list.setObjectName("AccountList")
        self._account_list.setSpacing(2)
        self._account_list.setMouseTracking(True)
        self._account_list.viewport().setMouseTracking(True)
        self._account_list.setItemDelegate(AccountItemDelegate(self._account_list))
        self._account_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._account_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._account_list.currentRowChanged.connect(self._on_account_selected)
        self._account_list.customContextMenuRequested.connect(self._show_account_menu)
        layout.addWidget(self._account_list, 1)

        self._btn_all = QPushButton("所有服务器一键授权")
        self._btn_all.setObjectName("SoftButton")
        self._btn_all.setToolTip("对全部云账号的所有服务器授权当前公网 IP")
        self._btn_all.clicked.connect(self._authorize_all_clicked)
        layout.addWidget(self._btn_all)
        return frame

    def _apply_account_filter(self, text: str) -> None:
        """按账号名或云厂商名过滤侧栏账号列表。"""
        keyword = text.strip().lower()
        for row in range(self._account_list.count()):
            if row >= len(self._bindings):
                continue
            binding = self._bindings[row]
            visible = (
                not keyword
                or keyword in binding.name.lower()
                or keyword in VENDOR_META[binding.vendor].name_cn.lower()
                or keyword in binding.vendor.value.lower()
            )
            self._account_list.item(row).setHidden(not visible)

    def _build_placeholder_page(self) -> QWidget:
        page = QWidget(self._stack)
        layout = QVBoxLayout(page)
        layout.addStretch(1)
        hint = QLabel(
            "尚未选择云账号\n点击左上角「+」绑定第一个云账号后，\n即可在这里查看并管理服务器防火墙授权。"
        )
        hint.setObjectName("PanelSubtitle")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(1)
        return page

    def _build_server_panel(self) -> QWidget:
        panel = QWidget(self._stack)
        panel.setObjectName("ServerPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        header = QFrame(panel)
        header.setObjectName("PanelHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)
        header_layout.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        self._panel_title = QLabel("请选择云账号")
        self._panel_title.setObjectName("PanelTitle")
        self._panel_subtitle = QLabel("在左侧选择或添加云账号")
        self._panel_subtitle.setObjectName("PanelSubtitle")
        title_box.addWidget(self._panel_title)
        title_box.addWidget(self._panel_subtitle)
        header_layout.addLayout(title_box, 1)

        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.setToolTip("重新检测公网 IP 并刷新服务器列表")
        self._btn_refresh.clicked.connect(self._refresh_clicked)
        header_layout.addWidget(self._btn_refresh)

        self._btn_auth_all = QPushButton("一键放行当前云厂商所有服务器")
        self._btn_auth_all.setObjectName("PrimaryButton")
        self._btn_auth_all.setToolTip("对本云厂商账号的所有服务器授权当前公网 IP（放通所有端口）")
        self._btn_auth_all.clicked.connect(self._authorize_current_clicked)
        header_layout.addWidget(self._btn_auth_all)

        self._btn_revoke_all = QPushButton("取消全部授权")
        self._btn_revoke_all.setObjectName("DangerButton")
        self._btn_revoke_all.setToolTip("删除本系统在本账号所有服务器上创建的授权规则")
        self._btn_revoke_all.clicked.connect(self._revoke_current_clicked)
        header_layout.addWidget(self._btn_revoke_all)

        layout.addWidget(header)

        self._table = QTableWidget(0, len(COLUMNS), panel)
        self._table.setObjectName("ServerTable")
        self._table.setHorizontalHeaderLabels(COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(44)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header_view.setStretchLastSection(False)
        for col, width in ((1, 150), (2, 170), (3, 140), (4, 110), (5, 170)):
            self._table.setColumnWidth(col, width)
        layout.addWidget(self._table, 1)
        return panel

    # ---------- 账号列表 ----------

    def current_binding(self) -> AccountBinding | None:
        """当前选中的账号绑定，未选中时返回 None。"""
        for binding in self._bindings:
            if binding.id == self._current_id:
                return binding
        return None

    def reload_accounts(self) -> None:
        """从存储刷新侧栏（保持当前选择；无选择时自动选中第一个）。"""
        previous_id = self._current_id
        self._bindings = self._store.list()
        self._account_list.blockSignals(True)
        self._account_list.clear()
        for binding in self._bindings:
            item = QListWidgetItem(binding.name)
            item.setData(Qt.ItemDataRole.UserRole, binding.vendor)
            self._account_list.addItem(item)
        self._account_list.blockSignals(False)

        ids = [b.id for b in self._bindings]
        if previous_id in ids:
            row = ids.index(previous_id)
            if self._account_list.currentRow() != row:
                self._account_list.setCurrentRow(row)  # 触发重新加载
            else:
                self._update_header()
        elif ids:
            self._account_list.setCurrentRow(0)  # 触发 _on_account_selected
        else:
            self._current_id = None
            self._stack.setCurrentIndex(0)
            self._servers = []
            self._table.setRowCount(0)
            self._update_header()
        self._update_actions()

    def _on_account_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._bindings):
            return
        self._current_id = self._bindings[row].id
        self._stack.setCurrentIndex(1)
        self._servers = []
        self._table.setRowCount(0)
        self._start_refresh(force_ip=False)

    def _show_account_menu(self, pos) -> None:
        item = self._account_list.itemAt(pos)
        if item is None:
            return
        row = self._account_list.row(item)
        binding = self._bindings[row]
        self._account_list.setCurrentRow(row)
        menu = QMenu(self)
        act_rename = menu.addAction("重命名")
        act_remove = menu.addAction("删除账号")
        chosen = menu.exec(self._account_list.viewport().mapToGlobal(pos))
        if chosen is act_rename:
            self._rename_binding(binding)
        elif chosen is act_remove:
            self._remove_binding(binding)

    def _add_account_clicked(self) -> None:
        dialog = AccountDialog(self, self._service)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        vendor, name, ak, sk = dialog.account_data()
        try:
            self._store.add(vendor, name, ak, sk)
        except Exception as exc:  # noqa: BLE001 — 存储层未知错误兜底
            QMessageBox.warning(self, "添加失败", str(exc))
            return
        self.reload_accounts()

    def _rename_binding(self, binding: AccountBinding) -> None:
        name, ok = QInputDialog.getText(self, "重命名账号", "新的显示名称：", text=binding.name)
        if not ok:
            return
        try:
            self._store.update_name(binding.id, name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "重命名失败", str(exc))
            return
        self.reload_accounts()

    def _remove_binding(self, binding: AccountBinding) -> None:
        answer = QMessageBox.question(
            self,
            "删除账号",
            f"确定删除云账号「{binding.name}」吗？\n其访问密钥将从系统凭据服务中一并删除。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._store.remove(binding.id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "删除失败", str(exc))
            return
        if self._current_id == binding.id:
            self._current_id = None
        self.reload_accounts()

    # ---------- 服务器列表 ----------

    def _start_refresh(self, force_ip: bool) -> None:
        binding = self.current_binding()
        if binding is None:
            return
        self._busy = True
        self._update_actions()
        self._update_header()
        token = self._next_token()
        self._panel_subtitle.setText("正在获取当前公网 IP…")

        def job() -> tuple[str, list[ServerInfo]]:
            if self._demo:
                from ..demo import DEMO_IP

                return DEMO_IP, self._service.list_servers(binding, DEMO_IP)
            ip = get_public_ip(force=force_ip)
            return ip, self._service.list_servers(binding, ip)

        run_async(
            job,
            lambda result: self._on_refresh_done(token, result),
            lambda message: self._on_refresh_fail(token, message),
            owner=self,
        )

    def _on_refresh_done(self, token: int, result: object) -> None:
        if token != self._view_token or not isinstance(result, tuple):
            return
        ip, servers = result
        self._busy = False
        self._current_ip = str(ip)
        self._servers = list(servers)
        self._apply_servers()

    def _on_refresh_fail(self, token: int, message: str) -> None:
        if token != self._view_token:
            return
        self._busy = False
        self._current_ip = None
        self._servers = []
        self._table.setRowCount(0)
        self._update_header()
        self._panel_subtitle.setText(f"加载失败：{message}")
        self._update_actions()
        QMessageBox.warning(self, "加载失败", message)

    def _apply_servers(self) -> None:
        self._table.setRowCount(len(self._servers))
        for row, server in enumerate(self._servers):
            name_item = QTableWidgetItem(server.name or server.instance_id)
            name_item.setData(Qt.ItemDataRole.ToolTipRole, f"{server.name}（{server.instance_id}）")
            self._table.setItem(row, 0, name_item)

            kind_text = "轻量应用服务器" if server.kind is ServerKind.LIGHTHOUSE else "云服务器 ECS"
            self._table.setItem(row, 1, QTableWidgetItem(kind_text))
            region_text = f"{server.region_name} · {server.region}" if server.region_name else server.region
            self._table.setItem(row, 2, QTableWidgetItem(region_text or "—"))
            self._table.setItem(row, 3, QTableWidgetItem(server.public_ip or "—"))

            status_item = QTableWidgetItem(STATUS_TEXT.get(server.status, server.status.value))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item.setForeground(QColor(STATUS_COLOR.get(server.status, TEXT_2)))
            self._table.setItem(row, COL_STATUS, status_item)

            self._table.setCellWidget(row, COL_ACTION, self._build_row_actions(server))
        self._update_header()
        self._update_actions()

    def _build_row_actions(self, server: ServerInfo) -> QWidget:
        box = QWidget(self._table)
        layout = QHBoxLayout(box)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        btn_auth = QPushButton("授权", box)
        btn_auth.setObjectName("SoftButton")
        btn_auth.setToolTip("授权当前公网 IP 访问该服务器所有端口")
        btn_auth.clicked.connect(partial(self._authorize_one, server))
        layout.addWidget(btn_auth)

        btn_revoke = QPushButton("取消授权", box)
        btn_revoke.setObjectName("DangerButton")
        btn_revoke.setToolTip("删除本系统在该服务器上创建的授权规则")
        btn_revoke.clicked.connect(partial(self._revoke_one, server))
        layout.addWidget(btn_revoke)

        btn_auth.setVisible(server.status is not AuthStatus.AUTHORIZED)
        btn_revoke.setVisible(server.status in (AuthStatus.AUTHORIZED, AuthStatus.EXPIRED))
        return box

    # ---------- 单台操作 ----------

    def _authorize_one(self, server: ServerInfo) -> None:
        binding = self.current_binding()
        if binding is None or self._current_ip is None or self._busy:
            return
        self._busy = True
        self._update_actions()
        self._panel_subtitle.setText(f"正在授权「{server.name}」…")
        token = self._view_token
        ip = self._current_ip

        def job() -> ServerInfo:
            self._service.authorize(binding, server, ip)
            return server

        run_async(
            job,
            lambda _server: self._on_row_op_done(token, f"已授权「{server.name}」：当前 IP 可访问所有端口"),
            lambda message: self._on_row_op_fail(token, message),
            owner=self,
        )

    def _revoke_one(self, server: ServerInfo) -> None:
        binding = self.current_binding()
        if binding is None or self._busy:
            return
        self._busy = True
        self._update_actions()
        self._panel_subtitle.setText(f"正在取消「{server.name}」的授权…")
        token = self._view_token

        def job() -> ServerInfo:
            self._service.revoke(binding, server)
            return server

        run_async(
            job,
            lambda _server: self._on_row_op_done(token, f"已取消「{server.name}」的授权"),
            lambda message: self._on_row_op_fail(token, message),
            owner=self,
        )

    def _on_row_op_done(self, token: int, message: str) -> None:
        if token != self._view_token:
            return
        self._busy = False
        self._apply_servers()
        self._panel_subtitle.setText(message)

    def _on_row_op_fail(self, token: int, message: str) -> None:
        if token != self._view_token:
            return
        self._busy = False
        self._update_actions()
        self._panel_subtitle.setText(f"操作失败：{message}")
        QMessageBox.warning(self, "操作失败", message)

    # ---------- 批量操作 ----------

    def _authorize_current_clicked(self) -> None:
        binding = self.current_binding()
        if binding is None or self._current_ip is None or not self._servers or self._busy:
            return
        self._busy = True
        self._update_actions()
        token = self._next_token()
        ip = self._current_ip

        def job() -> dict[str, int]:
            return self._service.authorize_all_for_vendor(
                binding, ip, progress=self._progress.message.emit
            )

        run_async(
            job,
            lambda stats: self._on_bulk_done(token, stats),
            lambda message: self._on_bulk_fail(token, message),
            owner=self,
        )

    def _revoke_current_clicked(self) -> None:
        binding = self.current_binding()
        if binding is None or not self._servers or self._busy:
            return
        self._busy = True
        self._update_actions()
        token = self._next_token()
        servers = list(self._servers)

        def job() -> list[str]:
            fails: list[str] = []
            for server in servers:
                try:
                    self._service.revoke(binding, server)
                except CloudAccessError as exc:
                    fails.append(f"{server.name}：{exc}")
            return fails

        run_async(
            job,
            lambda fails: self._on_revoke_all_done(token, fails),
            lambda message: self._on_bulk_fail(token, message),
            owner=self,
        )

    def _authorize_all_clicked(self) -> None:
        if not self._bindings or self._current_ip is None or self._busy:
            return
        answer = QMessageBox.question(
            self,
            "所有服务器一键授权",
            f"将对 {len(self._bindings)} 个云账号下的全部服务器授权当前公网 IP"
            f"（{self._current_ip}），是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._busy = True
        self._update_actions()
        token = self._next_token()
        bindings = list(self._bindings)
        ip = self._current_ip

        def job() -> dict[str, int]:
            return self._service.authorize_all(bindings, ip, progress=self._progress.message.emit)

        run_async(
            job,
            lambda stats: self._on_bulk_done(token, stats),
            lambda message: self._on_bulk_fail(token, message),
            owner=self,
        )

    def _on_bulk_done(self, token: int, stats: object) -> None:
        if token != self._view_token or not isinstance(stats, dict):
            return
        self._busy = False
        self._apply_servers()
        self._panel_subtitle.setText(
            f"批量操作完成：成功 {stats.get('ok', 0)} 台，失败 {stats.get('fail', 0)} 台，"
            f"共 {stats.get('total', 0)} 台"
        )
        self._update_actions()

    def _on_revoke_all_done(self, token: int, fails: object) -> None:
        if token != self._view_token or not isinstance(fails, list):
            return
        self._busy = False
        self._apply_servers()
        if fails:
            self._panel_subtitle.setText(f"撤销完成，但有 {len(fails)} 台失败，详见提示")
            QMessageBox.warning(self, "撤销全部", "\n".join(str(item) for item in fails))
        else:
            self._panel_subtitle.setText("已撤销本账号全部放行规则")
        self._update_actions()

    def _on_bulk_fail(self, token: int, message: str) -> None:
        if token != self._view_token:
            return
        self._busy = False
        self._update_actions()
        self._panel_subtitle.setText(f"批量操作失败：{message}")
        QMessageBox.warning(self, "批量操作失败", message)

    def _on_progress_message(self, message: str) -> None:
        if self._busy:
            self._panel_subtitle.setText(str(message))

    def _refresh_clicked(self) -> None:
        if self.current_binding() is None or self._busy:
            return
        self._start_refresh(force_ip=True)

    # ---------- 状态展示 ----------

    def _next_token(self) -> int:
        self._view_token += 1
        return self._view_token

    def _update_header(self) -> None:
        binding = self.current_binding()
        if binding is None:
            self._panel_title.setText("请选择云账号")
            self._panel_subtitle.setText("在左侧选择或添加云账号")
            return
        vendor_name = VENDOR_META[binding.vendor].name_cn
        self._panel_title.setText(binding.name)
        if self._current_ip:
            self._panel_subtitle.setText(
                f"{vendor_name} · 当前公网 IP：{self._current_ip} · 服务器 {len(self._servers)} 台"
            )
        else:
            self._panel_subtitle.setText(f"{vendor_name} · 正在检测当前公网 IP…")

    def _update_actions(self) -> None:
        binding = self.current_binding()
        has_servers = bool(self._servers)
        ready = binding is not None and self._current_ip is not None and not self._busy
        self._btn_refresh.setEnabled(binding is not None and not self._busy)
        self._btn_auth_all.setEnabled(ready and has_servers)
        self._btn_revoke_all.setEnabled(binding is not None and has_servers and not self._busy)
        self._btn_all.setEnabled(
            bool(self._bindings) and self._current_ip is not None and not self._busy
        )
        self._btn_add.setEnabled(not self._busy)
