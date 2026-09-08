"""后台任务生成器 — 统一给 fire-and-forget 的 asyncio.create_task 挂异常回调。

背景（4.1+ 修订清单）：裸 create_task 的意外异常会被任务静默吞掉（Python
仅在任务被 GC 时才补一条 "exception was never retrieved"）。建议引擎内已
捕获的 LLMUnavailableError 不会逃逸，但 _collect_context 的 DB 异常等
非预期错误必须留日志，否则排查无门。
"""
import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger('app.tasks')


def spawn_background(coro: Coroutine, *, name: str) -> asyncio.Task:
    """create_task + done-callback：取消静默，异常记 error 日志。"""
    task = asyncio.create_task(coro, name=name)

    def _done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error('后台任务 %s 异常终止：%r', name, exc, exc_info=exc)

    task.add_done_callback(_done)
    return task
