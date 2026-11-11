"""应用入口：装配存储、服务与主窗口；支持演示与截图模式。"""

from __future__ import annotations

import argparse
import os

from PySide6.QtWidgets import QApplication

from .service import CloudAccessService
from .storage import AccountStore
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def _build_window(args) -> tuple[MainWindow, QApplication]:
    app = QApplication(list(args.argv))
    app.setApplicationName("CloudAccess")
    app.setApplicationDisplayName("CloudAccess")
    app.setOrganizationName("CloudAccess")
    apply_theme(app)

    if args.demo or args.screenshot:
        from .demo import FakeService, FakeStore

        store = FakeStore()
        service = FakeService(store)
    else:
        store = AccountStore()
        service = CloudAccessService(store)

    window = MainWindow(service=service, store=store, demo=bool(args.demo or args.screenshot))
    _set_window_icon(app)
    return window, app


def _set_window_icon(app: QApplication) -> None:
    from PySide6.QtGui import QIcon

    icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "resources", "icon.png")
    if not os.path.exists(icon_path):
        import sys

        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        icon_path = os.path.join(base, "resources", "icon.png")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))


def main(argv: list[str] | None = None) -> int:
    """console script ``cloudaccess`` 与 ``python -m cloudaccess`` 的入口。"""
    parser = argparse.ArgumentParser(prog="cloudaccess", description="多云服务器防火墙一键放通工具")
    parser.add_argument("--demo", action="store_true", help="使用内置演示数据启动（离线）")
    parser.add_argument("--screenshot", metavar="PNG", help="渲染主窗口并保存截图后退出（演示数据）")
    args_parsed = parser.parse_args(list(argv) if argv is not None else None)

    # 无头环境（CI）可显式设置 QT_QPA_PLATFORM=offscreen；有桌面环境时使用真实
    # 平台以获得完整字体渲染
    if os.environ.get("CLOUDACCESS_HEADLESS") == "1":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    args = argparse.Namespace(
        argv=[a for a in (["cloudaccess"] + ([] if argv is None else list(argv)))],
        demo=args_parsed.demo,
        screenshot=args_parsed.screenshot,
    )
    window, app = _build_window(args)
    window.show()

    if args_parsed.screenshot:
        from PySide6.QtCore import QTimer

        result: dict[str, int] = {}

        def _grab() -> None:
            window.grab().save(args_parsed.screenshot)
            result["done"] = 0
            app.quit()

        QTimer.singleShot(300, _grab)
        app.exec()
        return result.get("done", 1)

    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
