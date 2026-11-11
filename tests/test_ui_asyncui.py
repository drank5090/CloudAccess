"""UI 异步任务桥测试。"""

from PySide6.QtCore import QObject, QThreadPool

from cloudaccess.ui.asyncui import run_async


def test_success_callback_after_pump(qapp):
    results: list[object] = []
    run_async(lambda: "演示结果", results.append, lambda m: results.append(("fail", m)))
    QThreadPool.globalInstance().waitForDone(10000)
    qapp.processEvents()
    assert results == ["演示结果"]


def test_failure_callback_receives_message(qapp):
    results: list[object] = []

    def boom() -> None:
        raise ValueError("演示失败")

    run_async(boom, results.append, results.append)
    QThreadPool.globalInstance().waitForDone(10000)
    qapp.processEvents()
    assert results == ["演示失败"]


def test_owner_keeps_task_referenced(qapp):
    class Owner(QObject):
        pass

    owner = Owner()
    done: list[object] = []
    run_async(lambda: 1, done.append, done.append, owner=owner)
    assert getattr(owner, "_pending_tasks", None)
    QThreadPool.globalInstance().waitForDone(10000)
    qapp.processEvents()
    assert done == [1]
