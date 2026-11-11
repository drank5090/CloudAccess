"""生成 README 截图：主窗口 + 添加账号对话框（演示数据，离线）。"""

from __future__ import annotations

import os
import sys

# 有桌面时用真实平台获得完整字体；CI 无头环境自动 offscreen
if os.environ.get("CLOUDACCESS_HEADLESS") == "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from cloudaccess.demo import FakeService, FakeStore
from cloudaccess.ui.account_dialog import AccountDialog
from cloudaccess.ui.main_window import MainWindow
from cloudaccess.ui.theme import apply_theme

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "images")


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app)

    store = FakeStore()
    service = FakeService(store)
    window = MainWindow(service=service, store=store, demo=True)
    window.show()

    dialog = AccountDialog(window)

    def grab_main() -> None:
        window.grab().save(os.path.join(OUT_DIR, "screenshot-main.png"))
        dialog.show()

        def grab_dialog() -> None:
            dialog.grab().save(os.path.join(OUT_DIR, "screenshot-add-account.png"))
            app.quit()

        QTimer.singleShot(300, grab_dialog)

    QTimer.singleShot(400, grab_main)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
