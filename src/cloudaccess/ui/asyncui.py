"""UI 异步任务桥：把阻塞调用放到线程池，经信号回主线程。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _TaskSignals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:  # pragma: no cover - Qt 线程体内不可测
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 — 后台线程统一兜底
            self._signals.failed.emit(str(exc))
        else:
            self._signals.done.emit(result)


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None],
    on_fail: Callable[[str], None],
    owner: QObject | None = None,
) -> None:
    """在线程池中执行 ``fn``，完成后在主线程回调。

    ``owner`` 用于把任务挂在某个 QObject 上防止被垃圾回收；
    同时所有任务都会进入模块级保活列表，确保工作线程在 owner
    提前销毁时仍能安全 emit 信号。
    """
    signals = _TaskSignals()
    signals.done.connect(on_done)
    signals.failed.connect(on_fail)
    task = _Task(fn, signals)
    if owner is not None:
        owner._pending_tasks = getattr(owner, "_pending_tasks", []) + [task]  # noqa: SLF001
    # 无论是否提供 owner，都进入模块级保活列表：
    # 否则 owner 提前销毁（如窗口关闭 / 进程退出）时，工作线程 emit
    # 会命中已销毁的信号对象并抛 “Signal source has been deleted”。
    _KEEPALIVE.append(task)
    QThreadPool.globalInstance().start(task)


_KEEPALIVE: list[_Task] = []
