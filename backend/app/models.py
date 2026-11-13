"""共享数据模型（契约 `C-DATA@2` / `C-DATA-AUTH@1` / `C-AI-DATA@1`）。

18 张表：users / tasks / checkins / credit_logs / notifications /
kb_entries / parse_sessions / progress_logs / task_applications / task_members /
activities / organizations / org_members / invitations / user_sessions /
password_resets / ai_conversations / ai_messages。

说明：Demo 期不建数据库级外键约束，仅做应用层校验（PLAN 2.2.1 A：
「Demo 期不建数据库级外键，应用层校验」）；JSON 列落库为 SQLite TEXT，
默认值一律使用 callable（``default=dict`` / ``default=list``），禁止 ``default={}``。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Float,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# SQLite 本地时间默认表达式：datetime('now','localtime')
_NOW_SQL = text("(datetime('now','localtime'))")


def _now_local() -> str:
    """Python 侧默认值：YYYY-MM-DD HH:MM:SS（服务器本地时间）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="student", server_default=text("'student'"))
    org: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # 认证列（`C-DATA-AUTH@1`）：全部可空或带默认，兼容旧行。
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    # active | legacy_unclaimed | disabled；legacy_unclaimed 为无密码的旧演示账号，不可登录。
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default=text("'active'"))
    platform_admin: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_org_id", "org_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 活动归属（`C-DATA-ACTIVITY@1`）：NULL 表示独立任务；子任务必须与父任务一致。
    activity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 组织归属（`C-DATA-AUTH@1`）：只表达归属，不参与 parent_id / activity_id 的工作拆分语义。
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[str | None] = mapped_column(Text, nullable=True)
    quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volunteer_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="published", server_default=text("'published'"))
    claim_type: Mapped[str] = mapped_column(Text, nullable=False, default="open", server_default=text("'open'"))
    publisher_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depends_on: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sop_guide: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    extras: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    reminder_rule: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    credit_reward: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class Checkin(Base):
    __tablename__ = "checkins"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_checkins_task_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    checkin_time: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class CreditLog(Base):
    __tablename__ = "credit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str] = mapped_column(Text, nullable=False)  # info/warning/urgent/overdue
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    # 去重键（契约 `C-DATA-MEMBER@1`）：同一收件人 + 任务 + 键值只保留一条通知。
    dedupe_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class KbEntry(Base):
    __tablename__ = "kb_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class ParseSession(Base):
    __tablename__ = "parse_sessions"

    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    accumulated_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    draft: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class ProgressLog(Base):
    __tablename__ = "progress_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class TaskApplication(Base):
    """报名记录（第 9 张表，契约 `C-DATA@2`）。

    - ``UNIQUE(task_id, user_id)``：同一用户对同一任务仅一条记录；撤回后复用该行改状态，
      因此「同一用户同一任务」不会出现两行。
    - ``task_id`` / ``user_id`` / ``decided_by`` 为逻辑引用（不加数据库级外键，与全库口径一致），
      存在性由应用层校验。
    - ``status`` 只允许 ``pending`` / ``approved`` / ``rejected`` / ``cancelled``，常量定义在
      ``app.services.application_service``（禁止在别处另写字面量）。
    - legacy 兼容：任务无任何 ``approved`` 行但 ``tasks.assignee_id`` 非空时，读取视角视为
      该用户已 approved（不做数据迁移），见 ``app.services.application_service``。
    """

    __tablename__ = "task_applications"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_applications_task_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="pending", server_default=text("'pending'")
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )
    decided_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)


class TaskMember(Base):
    """逐人执行记录（契约 `C-DATA-MEMBER@1`）。

    - ``UNIQUE(task_id, user_id)`` 名为 ``uq_task_members_task_user``：同一用户对同一任务
      只有一条执行记录，``init_db`` 的回填与 ``ensure_member`` 均依赖该约束幂等。
    - ``status`` 只允许 ``not_started`` / ``in_progress`` / ``submitted`` / ``rejected`` /
      ``verified``（常量定义在 ``app.services.member_service``）。
    - ``submitted_at`` / ``verified_at`` 只由成员动作写入；``updated_at`` 每次写入时刷新。
    """

    __tablename__ = "task_members"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_members_task_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="not_started", server_default=text("'not_started'")
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class Activity(Base):
    """活动（契约 `C-DATA-ACTIVITY@1`）。

    - ``tasks.activity_id`` 指向本表；本轮不建数据库级外键（与全库口径一致）。
    - ``org`` 列先建但不参与查询过滤（组织可见范围留待阶段 2）。
    - ``status`` 本轮只写入 ``published``。
    """

    __tablename__ = "activities"
    __table_args__ = (Index("ix_activities_org_id", "org_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    deadline: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(Integer, nullable=False)
    org: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 组织归属（`C-DATA-AUTH@1`）：NULL 表示尚未归属任何组织（隔离，不自动推断）。
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="published", server_default=text("'published'"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class Organization(Base):
    """组织（契约 `C-DATA-AUTH@1`）。"""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default=text("'active'"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class OrgMember(Base):
    """组织成员（契约 `C-DATA-AUTH@1`）。

    ``role`` 只允许 ``admin`` / ``collaborator`` / ``member``；``platform_admin`` 不写入本表。
    """

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_org_members_org_user"),
        Index("ix_org_members_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, default="member", server_default=text("'member'"))
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active", server_default=text("'active'"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class Invitation(Base):
    """注册邀请（契约 `C-DATA-AUTH@1`）。

    库中只存 ``hash_token(token)``；明文令牌仅在创建响应出现一次。
    ``max_uses`` / ``used_count`` 由注册事务内的条件 UPDATE 原子消费。
    """

    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_org_id", "org_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role_cap: Mapped[str] = mapped_column(Text, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=text("1"))
    used_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )
    revoked_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserSession(Base):
    """服务端会话（契约 `C-SESSION@1`）：Cookie 里放明文令牌，库中只存哈希。"""

    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    csrf_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class AiConversation(Base):
    """AI 只读问答会话（契约 `C-AI-DATA@1`）。

    会话只按 ``user_id`` 归属；列表 / 详情 / 续写都由服务层校验归属，
    不把客户端传入的 user_id 当作可信输入。``updated_at`` 在每次问答后刷新。
    """

    __tablename__ = "ai_conversations"
    __table_args__ = (Index("ix_ai_conversations_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )
    updated_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class AiMessage(Base):
    """AI 会话消息（契约 `C-AI-DATA@1`）。

    ``citations`` 只保存服务端从当前用户可见任务映射出的来源，不直接落模型
    给出的标题或 ID；``mock`` 标记该条回答是否来自 mock 路径。
    """

    __tablename__ = "ai_messages"
    __table_args__ = (Index("ix_ai_messages_conversation_id", "conversation_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    mock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


class PasswordReset(Base):
    """一次性密码重置凭据（契约 `C-DATA-AUTH@1`）：``used_at`` 非空即已消费。"""

    __tablename__ = "password_resets"
    __table_args__ = (Index("ix_password_resets_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(
        Text, nullable=False, default=_now_local, server_default=_NOW_SQL
    )


__all__ = [
    "User",
    "Task",
    "Checkin",
    "CreditLog",
    "Notification",
    "KbEntry",
    "ParseSession",
    "ProgressLog",
    "TaskApplication",
    "TaskMember",
    "Activity",
    "Organization",
    "OrgMember",
    "Invitation",
    "UserSession",
    "PasswordReset",
    "AiConversation",
    "AiMessage",
]