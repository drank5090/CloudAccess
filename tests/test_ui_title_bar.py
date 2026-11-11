"""自定义标题栏测试。"""

from PySide6.QtWidgets import QMainWindow

from cloudaccess.ui.title_bar import TitleBar, _app_icon_pixmap


def test_title_bar_buttons(qapp):
    window = QMainWindow()
    bar = TitleBar(window)
    assert bar._btn_min.toolTip() == "最小化"
    assert bar._btn_max.toolTip() == "最大化 / 还原"
    assert bar._btn_close.property("class") == "close"
    assert bar.minimumHeight() == 44
    assert bar.maximumHeight() == 44
    window.close()


def test_app_icon_pixmap(qapp):
    assert not _app_icon_pixmap(18).isNull()
