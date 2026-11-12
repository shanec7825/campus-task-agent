"""服务层（只负责副作用：落库 / 推送 / 事务 / 调度）。

T1 仅提供签名桩，``notification_hub`` 为最小可用实现。
"""

__all__ = [
    "notification_hub",
    "reminder_scheduler",
    "notify_service",
    "credit",
    "kb_service",
]