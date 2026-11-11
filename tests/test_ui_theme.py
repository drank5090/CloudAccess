"""主题与厂商头像绘制测试。"""

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter

from cloudaccess.ui.theme import GLOBAL_QSS, apply_theme, paint_vendor_avatar


def test_global_qss_covers_key_widgets():
    for token in (
        "#TitleBar",
        "#Sidebar",
        "#AccountList",
        "#ServerTable",
        "#VendorCard:checked",
        "#PrimaryButton",
        "#DangerButton",
        "#SoftButton",
    ):
        assert token in GLOBAL_QSS


def test_close_button_hover_rule_wired_to_class_property():
    """回归：关闭按钮靠 class=close 属性命中红色悬停样式。"""
    assert '#TitleButton[class="close"]:hover' in GLOBAL_QSS


def test_apply_theme_sets_stylesheet(qapp):
    apply_theme(qapp)
    assert "ServerTable" in qapp.styleSheet()


def test_paint_vendor_avatar(qapp):
    image = QImage(40, 40, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    paint_vendor_avatar(painter, QRectF(0, 0, 40, 40), "#FF8A00", "A", selected=True)
    painter.end()
    assert image.pixelColor(20, 2).alpha() > 0  # 圆形内部不透明
    assert image.pixelColor(0, 0).alpha() == 0  # 圆形外部保持透明
