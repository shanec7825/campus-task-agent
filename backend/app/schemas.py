"""共享 Pydantic 模型（契约 `C-DATA@1`，T1 冻结）。

字段名与 JSON 键名必须与计划逐字一致；后续 owner 不得修改本文件，
发现契约缺口须报告 Leader。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- #
# 通用 / 认证
# --------------------------------------------------------------------------- #


class ReminderRule(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    days_before: int = 1
    day_of: bool = True
    on_overdue: bool = True


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    org: str | None = None
    credits: int


class LoginIn(BaseModel):
    """1..32，strip 后非空。"""

    model_config = ConfigDict(from_attributes=True)

    username: str = Field(min_length=1, max_length=32)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("用户名不能为空")
        return stripped


class LoginOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str
    user: UserOut


# --------------------------------------------------------------------------- #
# 任务
# --------------------------------------------------------------------------- #


class TaskCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parent_id: int | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    location: str | None = None
    start_time: str | None = None
    deadline: str | None = None
    quota: int | None = None
    volunteer_hours: float | None = None
    claim_type: Literal["open", "assign"] = "open"
    assignee_id: int | None = None
    depends_on: int | None = None
    sop_guide: str | None = None
    style_note: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    reminder_rule: ReminderRule | None = None
    credit_reward: int = 20


class TaskUpdate(BaseModel):
    """所有字段默认 None；省略 = 不修改，显式 null = 清空该列。"""

    model_config = ConfigDict(from_attributes=True)

    parent_id: int | None = None
    title: str | None = None
    description: str | None = None
    location: str | None = None
    start_time: str | None = None
    deadline: str | None = None
    quota: int | None = None
    volunteer_hours: float | None = None
    claim_type: Literal["open", "assign"] | None = None
    assignee_id: int | None = None
    depends_on: int | None = None
    sop_guide: str | None = None
    style_note: str | None = None
    extras: dict[str, Any] | None = None
    reminder_rule: ReminderRule | None = None
    credit_reward: int | None = None
    status: Literal["cancelled"] | None = None


class TaskBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    assignee_id: int | None = None
    depends_on: int | None = None
    quota: int | None = None
    parent_id: int | None = None


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    user_id: int
    user_name: str
    content: str
    created_at: str


class MemberOut(BaseModel):
    """逐人执行视图（契约 `C-DATA-MEMBER@1`），``user_name`` 由服务端批量填充。"""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    status: str
    rejection_reason: str | None = None
    submitted_at: str | None = None
    verified_at: str | None = None
    updated_at: str | None = None


class TaskOut(BaseModel):
    """tasks 表全部列 + 派生字段。

    报名审批扩展（`C-DATA@2`）：末尾 4 个字段均为「有默认值的非可选字段」，
    保证 P1 既有构造点（``routers/tasks.py`` 的 ``_task_payload``）在 T2 改造前
    仍可直接 ``model_validate``。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    parent_id: int | None = None
    title: str
    description: str | None = None
    location: str | None = None
    start_time: str | None = None
    deadline: str | None = None
    quota: int | None = None
    volunteer_hours: float | None = None
    status: str
    claim_type: str
    publisher_id: int
    assignee_id: int | None = None
    depends_on: int | None = None
    sop_guide: str | None = None
    style_note: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    reminder_rule: ReminderRule | None = None
    credit_reward: int | None = 0
    created_at: str
    assignee_name: str | None = None
    publisher_name: str
    is_claimable: bool = False
    applied_count: int = 0
    approved_count: int = 0
    my_application_status: str | None = None
    assignee_names: list[str] = Field(default_factory=list)
    members: list[MemberOut] = Field(default_factory=list)
    my_member_status: str | None = None


class TaskDetailOut(TaskOut):
    children: list[TaskBrief] = Field(default_factory=list)
    progress: list[ProgressOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 报名审批（`C-APPLY@1` 的数据结构，契约 `C-DATA@2`）
# --------------------------------------------------------------------------- #


class ApplicationOut(BaseModel):
    """单条报名记录（A3 / A5 的列表元素）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    user_id: int
    user_name: str
    status: str
    reason: str | None = None
    created_at: str
    decided_at: str | None = None


class ApplyOut(BaseModel):
    """报名 / 撤回 / 审批的返回体（A1 / A2 / A4、claim 兼容别名）。

    ``task`` 使用字符串前向引用，``TaskOut`` 已在上面定义，文件末尾统一
    ``model_rebuild()``，避免把 ``TaskOut`` 提前破坏既有类顺序。
    """

    model_config = ConfigDict(from_attributes=True)

    task_id: int
    application: ApplicationOut
    task: "TaskOut"


class DecisionIn(BaseModel):
    """审批请求体；``approve=false`` 时 ``reason`` 必填（由路由层校验错误码 4001）。"""

    model_config = ConfigDict(from_attributes=True)

    approve: bool
    reason: str | None = None


class ApplicationItemOut(BaseModel):
    """我的报名列表元素（A5）：报名记录 + 任务摘要。"""

    model_config = ConfigDict(from_attributes=True)

    application: ApplicationOut
    task: "TaskBrief"


class VerifyOut(BaseModel):
    """验收通过返回体（多人各自加分）。"""

    model_config = ConfigDict(from_attributes=True)

    task: "TaskOut"
    credit_delta: int
    credited_user_ids: list[int] = Field(default_factory=list)


class AssignIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int


class VerifyIn(BaseModel):
    """请求体键名为 ``pass``（Python 关键字），通过 alias 映射到 pass_。"""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    pass_: bool = Field(alias="pass")
    reason: str | None = None
    user_id: int | None = None


class ProgressIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    content: str = Field(min_length=1, max_length=1000)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("进度内容不能为空")
        return stripped


# --------------------------------------------------------------------------- #
# 签到 / 积分
# --------------------------------------------------------------------------- #


class CheckinIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int


class CheckinOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    user_id: int
    task_title: str | None = None
    checkin_time: str


class CreditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    task_id: int | None = None
    delta: int
    reason: str
    created_at: str


class CreditsMeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    credits: int
    logs: list[CreditLogOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 通知
# --------------------------------------------------------------------------- #


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    task_id: int | None = None
    level: str
    title: str
    content: str
    is_read: int
    created_at: str


class NotificationListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unread: int
    items: list[NotificationOut] = Field(default_factory=list)


class ReadIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ids: list[int] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Agent / 草稿
# --------------------------------------------------------------------------- #


class ChangeOut(BaseModel):
    """字段级变更（`C-AGENT@2`）。

    - ``op``：``set`` 写入标量字段 / ``add_tag`` 新增扩展标签 / ``remove_tag`` 移除扩展标签。
    - ``field``：标量字段名，或扩展项的 ``"extra_tags.<键名>"``。
    - ``old_value`` / ``new_value`` 只允许 ``str|int|float|None``（禁止 list/dict）。
    - ``reason`` 是建议说明，只展示、不落字段；``source`` 区分 AI 与用户手改。
    """

    model_config = ConfigDict(from_attributes=True)

    op: Literal["set", "add_tag", "remove_tag"]
    field: str
    old_value: Any | None = None
    new_value: Any | None = None
    reason: str = ""
    source: Literal["ai", "user"] = "ai"


class TraceBlock(BaseModel):
    """前端追溯块（`C-TRACE@1`）：后端只透传，不清洗、不排序、不重新生成。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    text: str
    kind: Literal["ai_applied", "user_edit", "user_note", "live"]
    field: str | None = None
    meta: dict[str, Any] | None = None


class ExtractIn(BaseModel):
    """提炼请求；``mode="incremental"`` 时以 ``base_draft`` 为基底做增量合并。"""

    model_config = ConfigDict(from_attributes=True)

    text: str = Field(min_length=1, max_length=4000)
    base_draft: "Draft | None" = None
    mode: Literal["full", "incremental"] = "full"


class SpanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    text: str
    field: str | None = None


class CorrectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    target: str
    old_value: str | None = None
    new_value: str
    reason: str


class Draft(BaseModel):
    """草稿结构：P1 的 10 个字段语义不变，末尾追加前端权威的追溯块。"""

    model_config = ConfigDict(from_attributes=True)

    title: str | None = None
    time: str | None = None
    deadline: str | None = None
    location: str | None = None
    details: str | None = None
    quota: int | None = None
    volunteer_hours: float | None = None
    notes: str | None = None
    requirements: str | None = None
    extra_tags: dict[str, str] = Field(default_factory=dict)
    style_prompt: str | None = None
    # 前端权威数据：后端原样透传（None 与 [] 都表示无追溯块），不加校验器。
    trace: list[TraceBlock] | None = None


class ExtractOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft: Draft
    spans: list[SpanOut] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    style_prompt: str | None = None
    corrections: list[CorrectionOut] = Field(default_factory=list)
    mock: bool = False
    # 与 applied_texts 长度相等、顺序一一对应（T8 断言）。
    changes: list[ChangeOut] = Field(default_factory=list)
    applied_texts: list[str] = Field(default_factory=list)


class ReviewIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft: Draft


class Ambiguity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    field: str
    question: str
    suggestion: str | None = None


class SubTaskSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str
    description: str
    sop_guide: str
    quota: int | None = None
    depends_on: int | None = None


class Polished(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    details: str
    notes: str


class ReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ambiguities: list[Ambiguity] = Field(default_factory=list)
    polished: Polished | None = None
    suggested_sub_tasks: list[SubTaskSuggestion] = Field(default_factory=list)
    mock: bool = False
    changes: list[ChangeOut] = Field(default_factory=list)


class StreamParseIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: str
    chunk: str = ""
    is_final: bool = False


class StreamParseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft: Draft
    spans: list[SpanOut] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    corrections: list[CorrectionOut] = Field(default_factory=list)
    mock: bool = False
    changes: list[ChangeOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 知识库
# --------------------------------------------------------------------------- #


class SimilarItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: int | None = None
    title: str
    summary: str | None = None
    similarity: float
    created_at: str | None = None


class KbSimilarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[SimilarItem] = Field(default_factory=list)
    threshold: float = 0.6


__all__ = [
    "ReminderRule",
    "UserOut",
    "LoginIn",
    "LoginOut",
    "TaskCreate",
    "TaskUpdate",
    "TaskBrief",
    "MemberOut",
    "TaskOut",
    "TaskDetailOut",
    "ApplicationOut",
    "ApplyOut",
    "DecisionIn",
    "ApplicationItemOut",
    "VerifyOut",
    "AssignIn",
    "VerifyIn",
    "ProgressIn",
    "ProgressOut",
    "CheckinIn",
    "CheckinOut",
    "CreditLogOut",
    "CreditsMeOut",
    "NotificationOut",
    "NotificationListOut",
    "ReadIn",
    "ExtractIn",
    "ChangeOut",
    "TraceBlock",
    "SpanOut",
    "CorrectionOut",
    "Draft",
    "ExtractOut",
    "ReviewIn",
    "Ambiguity",
    "SubTaskSuggestion",
    "Polished",
    "ReviewOut",
    "StreamParseIn",
    "StreamParseOut",
    "SimilarItem",
    "KbSimilarOut",
]

# --------------------------------------------------------------------------- #
# 前向引用统一解析（`C-DATA@2`）：字符串注解（``"TaskOut"`` / ``"TaskBrief"`` /
# ``"Draft | None"``）在文件末尾一次 rebuild，避免把 TaskOut 提前破坏既有类顺序。
# --------------------------------------------------------------------------- #
ApplyOut.model_rebuild()
VerifyOut.model_rebuild()
ApplicationItemOut.model_rebuild()
ExtractIn.model_rebuild()