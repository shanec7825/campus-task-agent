"""路由包。

T1 提供 7 个路由桩；T2 追加 ``applications``（报名审批，`C-APPLY@1`），
``main.py`` 在 ``tasks.router`` 之后挂载，保证 ``/api/tasks/...`` 不冲突。
"""

from app.routers import agent, applications, auth, checkin, credits, kb, notifications, resources, tasks

__all__ = [
    "auth",
    "tasks",
    "applications",
    "checkin",
    "credits",
    "notifications",
    "kb",
    "agent",
    "resources",
]