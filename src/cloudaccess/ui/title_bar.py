"""无边框窗口的自定义标题栏。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
)


def _app_icon_pixmap(size: int = 18) -> QPixmap:
    """生成应用小图标（蓝色圆角方块 + 闪电）。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#3B82F6"))
    p.drawRoundedRect(0, 0, size, size, size * 0.28, size * 0.28)
    p.setBrush(QColor("white"))
    w = size
    bolt = [
        (w * 0.56, w * 0.12),
        (w * 0.28, w * 0.55),
        (w * 0.46, w * 0.55),
        (w * 0.42, w * 0.88),
        (w * 0.72, w * 0.42),
        (w * 0.53, w * 0.42),
    ]
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPolygonF

    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in bolt]))
    p.end()
    return pm


class TitleBar(QFrame):
    """拖拽移动 + 最小化/最大化/关闭。"""

    def __init__(self, window: QMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self.setObjectName("TitleBar")
        self.setFixedHeight(44)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 6, 0)
        layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setPixmap(_app_icon_pixmap(20))
        icon_label.setFixedSize(20, 20)
        layout.addWidget(icon_label)

        title = QLabel("CloudAccess · 多云服务器防火墙放通")
        title.setObjectName("TitleLabel")
        layout.addWidget(title)
        layout.addStretch(1)

        self._btn_min = QPushButton("—")
        self._btn_min.setObjectName("TitleButton")
        self._btn_min.setToolTip("最小化")
        self._btn_min.clicked.connect(window.showMinimized)

        self._btn_max = QPushButton("□")
        self._btn_max.setObjectName("TitleButton")
        self._btn_max.setToolTip("最大化 / 还原")
        self._btn_max.clicked.connect(self._toggle_max)

        self._btn_close = QPushButton("✕")
        self._btn_close.setObjectName("TitleButton")
        self._btn_close.setProperty("class", "close")
        self._btn_close.clicked.connect(window.close)

        for b in (self._btn_min, self._btn_max, self._btn_close):
            layout.addWidget(b)

    def _toggle_max(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    # ---------- 拖拽移动 ----------

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self._window.windowHandle().startSystemMove()
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 — Qt 命名
        self._toggle_max()
