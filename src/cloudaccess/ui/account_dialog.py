"""添加云账号对话框：选择厂商 → 填写 AK/SK → 在线验证。

安全约束：
- SecretKey 输入框默认密码回显，仅在用户主动点击“显示”时临时明文；
- SK 不写入日志、不进入窗口标题等任何可读文本；
- 凭据仅在用户确认后由主窗口写入系统凭据服务，本对话框不落盘。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import VENDOR_META, CloudVendor
from .asyncui import run_async
from .theme import ACCENT, DANGER, paint_vendor_avatar


def vendor_avatar_pixmap(color: str, initial: str, size: int = 30) -> QPixmap:
    """渲染圆形厂商头像位图。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_vendor_avatar(painter, QRectF(0, 0, size, size), color, initial)
    finally:
        painter.end()
    return pixmap


class AccountDialog(QDialog):
    """添加云账号对话框。

    用法::

        dialog = AccountDialog(parent, service)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            vendor, name, ak, sk = dialog.account_data()
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        service: Any = None,
        vendors: list[CloudVendor] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._vendors = list(vendors) if vendors is not None else list(CloudVendor)
        self.account_identity = ""  # 验证成功后由云厂商返回的账号标识
        self._accepted_data: tuple[CloudVendor, str, str, str] = (
            self._vendors[0] if self._vendors else CloudVendor.ALIYUN,
            "",
            "",
            "",
        )
        self._vendor_buttons: dict[CloudVendor, QPushButton] = {}

        self.setObjectName("Dialog")
        self.setWindowTitle("添加云账号")
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel("添加云账号")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        intro = QLabel("填写云厂商访问密钥（AccessKey），用于读取服务器列表与防火墙规则。")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        cards_row = QHBoxLayout()
        cards_row.setSpacing(10)
        self._vendor_group = QButtonGroup(self)
        self._vendor_group.setExclusive(True)
        for vendor in self._vendors:
            cards_row.addWidget(self._build_vendor_card(vendor))
        cards_row.addStretch(1)
        layout.addLayout(cards_row)

        self._name = QLineEdit()
        self._name.setPlaceholderText("例如：公司主账号（可留空，留空时使用厂商名）")
        layout.addWidget(self._field_block("备注名称", self._name))

        self._ak = QLineEdit()
        self._ak.setPlaceholderText("AccessKeyId")
        layout.addWidget(self._field_block("AccessKeyId", self._ak))

        self._sk = QLineEdit()
        self._sk.setPlaceholderText("AccessKeySecret")
        self._sk.setEchoMode(QLineEdit.EchoMode.Password)
        sk_row = QHBoxLayout()
        sk_row.setContentsMargins(0, 0, 0, 0)
        sk_row.addWidget(self._sk, 1)
        self._btn_toggle_sk = QPushButton("显示")
        self._btn_toggle_sk.setCheckable(True)
        self._btn_toggle_sk.setToolTip("默认隐藏密钥，仅在需要核对时临时显示")
        self._btn_toggle_sk.toggled.connect(self._on_toggle_sk)
        sk_row.addWidget(self._btn_toggle_sk)
        layout.addWidget(self._field_block("AccessKeySecret", sk_row))

        secret_hint = QLabel("密钥仅保存在系统凭据服务（Windows 凭据管理器 / macOS 钥匙串），不会明文落盘。")
        secret_hint.setObjectName("HintLabel")
        secret_hint.setWordWrap(True)
        layout.addWidget(secret_hint)

        self._error = QLabel("")
        self._error.setObjectName("HintLabel")
        self._error.setStyleSheet(f"color: {DANGER}; background: transparent;")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_cancel)
        self._btn_ok = QPushButton("验证并添加")
        self._btn_ok.setObjectName("PrimaryButton")
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self._on_confirm)
        buttons.addWidget(self._btn_ok)
        layout.addLayout(buttons)

        self._ak.textChanged.connect(self._update_ok_enabled)
        self._sk.textChanged.connect(self._update_ok_enabled)
        if self._vendors:
            self._vendor_buttons[self._vendors[0]].setChecked(True)
        self._update_card_styles()

    # ---------- 构建 ----------

    def _build_vendor_card(self, vendor: CloudVendor) -> QPushButton:
        meta = VENDOR_META[vendor]
        card = QPushButton(self)
        card.setObjectName("VendorCard")
        card.setCheckable(True)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setFixedSize(140, 64)
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 10, 8)
        row.setSpacing(9)

        avatar = QLabel(card)
        avatar.setPixmap(vendor_avatar_pixmap(meta.color, meta.initial, 30))
        avatar.setFixedSize(30, 30)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(avatar)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)
        name = QLabel(meta.name_cn, card)
        name.setObjectName("VendorName")
        name_en = QLabel(meta.name_en, card)
        name_en.setObjectName("HintLabel")
        text_col.addWidget(name)
        text_col.addWidget(name_en)
        row.addLayout(text_col, 1)

        self._vendor_group.addButton(card)
        card.toggled.connect(lambda _checked, _v=vendor: self._update_card_styles())
        self._vendor_buttons[vendor] = card
        return card

    def _field_block(self, label_text: str, content: QWidget | QHBoxLayout) -> QWidget:
        block = QWidget(self)
        inner = QVBoxLayout(block)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(4)
        label = QLabel(label_text)
        label.setObjectName("FormLabel")
        inner.addWidget(label)
        if isinstance(content, QHBoxLayout):
            inner.addLayout(content)
        else:
            inner.addWidget(content)
        return block

    # ---------- 交互 ----------

    def selected_vendor(self) -> CloudVendor:
        """当前选中的云厂商。"""
        for vendor, card in self._vendor_buttons.items():
            if card.isChecked():
                return vendor
        return self._accepted_data[0]

    def account_data(self) -> tuple[CloudVendor, str, str, str]:
        """返回 (厂商, 备注名, AccessKeyId, AccessKeySecret)，仅在 accept 后有意义。"""
        return self._accepted_data

    def _update_card_styles(self) -> None:
        for card in self._vendor_buttons.values():
            name = card.findChild(QLabel, "VendorName")
            if name is not None:
                name.setStyleSheet(f"color: {ACCENT};" if card.isChecked() else "")

    def _on_toggle_sk(self, visible: bool) -> None:
        self._sk.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self._btn_toggle_sk.setText("隐藏" if visible else "显示")

    def _update_ok_enabled(self) -> None:
        self._btn_ok.setEnabled(bool(self._ak.text().strip()) and bool(self._sk.text().strip()))

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(bool(message))

    def _set_running(self, running: bool) -> None:
        self._btn_ok.setText("验证中…" if running else "验证并添加")
        self._btn_ok.setEnabled(
            not running and bool(self._ak.text().strip()) and bool(self._sk.text().strip())
        )
        for widget in (self._name, self._ak, self._sk, *self._vendor_buttons.values()):
            widget.setEnabled(not running)

    # ---------- 提交与在线验证 ----------

    def _on_confirm(self) -> None:
        vendor = self.selected_vendor()
        ak = self._ak.text().strip()
        sk = self._sk.text()
        if not ak or not sk:
            self._show_error("请填写完整的 AccessKeyId 与 AccessKeySecret。")
            return
        self._show_error("")
        if self._service is None:
            self._finish(vendor, ak, sk, identity="")
            return
        self._set_running(True)
        run_async(
            lambda: self._service.validate_credentials(vendor, ak, sk),
            self._on_validated,
            self._on_validate_failed,
            owner=self,
        )

    def _on_validated(self, identity: object) -> None:
        self._finish(
            self.selected_vendor(),
            self._ak.text().strip(),
            self._sk.text(),
            identity=str(identity or ""),
        )

    def _on_validate_failed(self, message: str) -> None:
        self._set_running(False)
        self._show_error(f"凭据验证失败：{message}")

    def _finish(self, vendor: CloudVendor, ak: str, sk: str, identity: str) -> None:
        self._accepted_data = (vendor, self._name.text().strip(), ak, sk)
        self.account_identity = identity
        self.accept()
