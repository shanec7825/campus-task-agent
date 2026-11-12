"""SSE 连接注册表（契约 `C-SSE@1`，owner = T4）。

设计要点
--------
1. ``_queues: dict[int, list[asyncio.Queue]]``：同一用户可持有**多条**队列
   （多标签页 / 多设备 / 前端断线重连前的残留连接），推送时必须全部投递。
2. ``publish`` 是**线程安全**的：业务事务（HTTP 请求线程）与催办调度
   （APScheduler 工作线程）都会调用它。实现上不在调用线程里触碰
   ``_queues``，只把投递动作通过 ``loop.call_soon_threadsafe`` 排队到事件
   循环线程执行，因此 ``_queues`` 的读写全部收敛在事件循环线程内。
3. 容错：未 ``bind_loop``（如单元测试 / 脚本 / 启动早期）或事件循环已关闭
   时，``publish`` **静默丢弃并返回 None**，绝不抛异常打断业务事务。
4. 背压：队列有界（``_QUEUE_MAXSIZE``）。队列满时丢弃**最旧**一条再写入
   新事件，避免慢客户端拖垮整轮推送；投递失败的死队列会被清理。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: 单连接队列上限。正常 SSE 消费速度远高于通知产生速度；上限只用于兜底
#: 慢客户端，避免内存无界增长。
_QUEUE_MAXSIZE = 256

_loop: asyncio.AbstractEventLoop | None = None
_queues: dict[int, list[asyncio.Queue[dict[str, Any]]]] = {}


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """绑定当前运行中的事件循环（由 ``main.py`` 的 lifespan 启动阶段调用）。

    幂等：重复绑定同一 loop 无副作用；绑定新 loop（如测试中重建）时覆盖。
    """
    global _loop
    if loop is None:  # 防御性：调用方传入 None 时保持"未绑定"状态
        logger.warning("bind_loop: 传入 None，SSE 推送将保持静默丢弃状态")
        _loop = None
        return
    if _loop is not None and _loop is not loop:
        logger.info("bind_loop: 事件循环已重新绑定（旧连接队列不可用）")
    _loop = loop


def subscribe(user_id: int) -> asyncio.Queue[dict[str, Any]]:
    """为指定用户注册一条新连接队列。

    **必须在事件循环内调用**（SSE 路由的异步生成器里）。若在循环外调用，
    ``asyncio.Queue`` 会绑定到错误/不存在的 loop，导致跨线程投递失效，
    因此这里直接抛出 ``RuntimeError`` 让调用方尽早暴露错误。
    """
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:  # pragma: no cover - 仅防御性分支
        raise RuntimeError(
            "notification_hub.subscribe() 必须在事件循环内调用（SSE 生成器）"
        ) from None

    if _loop is not None and _loop is not running_loop:
        # 不阻断业务，但必须留下线索：否则 publish 会把事件投递到另一个 loop。
        logger.warning("subscribe: 当前事件循环与 bind_loop 绑定的循环不一致")

    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _queues.setdefault(user_id, []).append(queue)
    logger.debug("subscribe: user_id=%s 在线连接数=%s", user_id, connection_count(user_id))
    return queue


def unsubscribe(user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """注销连接队列（SSE 生成器的 ``finally`` 中必须调用，避免连接泄漏）。

    幂等：重复注销 / 队列不存在均静默返回。若从非事件循环线程调用，
    则把删除动作调度回绑定的 loop，保证 ``_queues`` 只在 loop 线程被修改。
    """
    loop = _loop
    if loop is None or loop.is_closed():
        _remove_queue(user_id, queue)
        return

    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    if running_loop is loop:
        _remove_queue(user_id, queue)
        return

    try:
        loop.call_soon_threadsafe(_remove_queue, user_id, queue)
    except RuntimeError:  # loop 正在关闭
        _remove_queue(user_id, queue)


def publish(user_id: int, payload: dict[str, Any]) -> None:
    """向该用户的全部在线连接推送一条事件（线程安全）。

    - 内部使用 ``bind_loop`` 保存的 loop 与 ``loop.call_soon_threadsafe`` 投递；
    - 未 ``bind_loop`` / loop 已关闭 / 投递异常时**静默丢弃**，不抛异常；
    - 无在线连接时不产生任何代价（投递动作在执行时才发现队列为空）。
    """
    loop = _loop
    if loop is None or loop.is_closed():
        logger.debug("publish: 事件循环未就绪，丢弃 user_id=%s 的通知", user_id)
        return None

    try:
        loop.call_soon_threadsafe(_deliver, user_id, payload)
    except RuntimeError:  # loop 正在关闭
        logger.debug("publish: 事件循环已关闭，丢弃 user_id=%s 的通知", user_id)
    except Exception:  # 任何异常都不得影响业务事务
        logger.warning("publish: 投递失败 user_id=%s", user_id, exc_info=True)
    return None


def connection_count(user_id: int | None = None) -> int:
    """在线连接数（供自检 / 调试用，不参与契约流程）。

    注意：仅作近似观测，不保证跨线程一致性。
    """
    if user_id is None:
        return sum(len(items) for items in _queues.values())
    return len(_queues.get(user_id, []))


# --------------------------------------------------------------------------- #
# 内部实现：以下函数只在事件循环线程内执行（由 call_soon_threadsafe 调度）
# --------------------------------------------------------------------------- #
def _deliver(user_id: int, payload: dict[str, Any]) -> None:
    """把事件写入该用户全部队列（在事件循环线程内执行）。"""
    queues = _queues.get(user_id)
    if not queues:
        return

    stale: list[asyncio.Queue[dict[str, Any]]] = []
    for queue in list(queues):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            # 背压：丢弃最旧的一条，保证最新事件可达
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:  # pragma: no cover - 竞态下才会发生
                pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:  # pragma: no cover - 极端竞态
                logger.warning("_deliver: user_id=%s 的队列已满且丢弃失败，跳过", user_id)
        except Exception:  # 已关闭 / 已损坏的队列
            stale.append(queue)
            logger.warning("_deliver: user_id=%s 存在失效队列，已清理", user_id, exc_info=True)

    for queue in stale:
        _remove_queue(user_id, queue)


def _remove_queue(user_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
    """从注册表移除一条队列，并在列表为空时清理该用户的字典条目。"""
    queues = _queues.get(user_id)
    if not queues:
        return
    try:
        queues.remove(queue)
    except ValueError:
        return
    if not queues:
        _queues.pop(user_id, None)