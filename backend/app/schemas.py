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
    created_at: str | None = None
    platform_admin: bool = False


class LoginIn(BaseModel):
    """账号 + 密码（`C-DATA-AUTH@1`）：1..64 / 1..200，用户名 strip 后非空。"""

    model_config = ConfigDict(from_attributes=True)

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("username")
    @classmethod
    def _strip_username(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("用户名不能为空")
        return stripped


class OrgOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    status: str
    created_at: str


class OrgCreateIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=60)
    slug: str = Field(min_length=1, max_length=60)


class OrgMembershipOut(BaseModel):
    """当前用户在某个组织中的身份（`GET /api/auth/me` 与登录响应）。"""

    model_config = ConfigDict(from_attributes=True)

    org_id: int
    name: str
    slug: str
    role: str
    title: str | None = None
    status: str


class OrgMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    display_name: str
    role: str
    title: str | None = None
    status: str
    joined_at: str


class InvitationOut(BaseModel):
    """邀请的展示形态：不含明文 token（库中只有 ``token_hash``）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    role_cap: str
    expires_at: str
    max_uses: int
    used_count: int
    revoked_at: str | None = None
    created_at: str


class InvitationCreatedOut(InvitationOut):
    token: str


class InvitationCreateIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role_cap: str = "member"
    expires_in_hours: int = Field(default=72, ge=1, le=720)
    max_uses: int = Field(default=1, ge=1, le=200)


class MemberPatchIn(BaseModel):
    role: str | None = None
    title: str | None = None
    status: str | None = None


class RegisterIn(BaseModel):
    """凭邀请码注册（`C-ORG@1`）；``confirm_password`` 一致性由路由层校验。"""

    model_config = ConfigDict(from_attributes=True)

    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=200)
    confirm_password: str = Field(min_length=8, max_length=200)
    invite_token: str = Field(min_length=8, max_length=200)


class PasswordResetIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    token: str = Field(min_length=8, max_length=200)
    password: str = Field(min_length=8, max_length=200)
    confirm_password: str = Field(min_length=8, max_length=200)


class PasswordResetRequestOut(BaseModel):
    """一次性重置凭据：明文 token 只在此响应出现一次。"""

    model_config = ConfigDict(from_attributes=True)

    token: str
    expires_at: str


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserOut
    orgs: list[OrgMembershipOut] = Field(default_factory=list)


class LoginOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user: UserOut
    orgs: list[OrgMembershipOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 任务
# --------------------------------------------------------------------------- #


class TaskCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parent_id: int | None = None
    activity_id: int | None = None
    org_id: int | None = None
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
    # 多前置依赖（`C-TASK-GRAPH@1`）：显式提供时覆盖全部依赖边
    depends_on_ids: list[int] | None = None
    sop_guide: str | None = None
    style_note: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    reminder_rule: ReminderRule | None = None
    credit_reward: int = 20


class TaskUpdate(BaseModel):
    """所有字段默认 None；省略 = 不修改，显式 null = 清空该列。"""

    model_config = ConfigDict(from_attributes=True)

    parent_id: int | None = None
    activity_id: int | None = None
    org_id: int | None = None
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
    # 显式提供时整体替换依赖边；省略 = 不修改（`C-TASK-GRAPH@1`）
    depends_on_ids: list[int] | None = None
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
    activity_id: int | None = None
    org_id: int | None = None
    depends_on_ids: list[int] = Field(default_factory=list)


class TaskGraphNode(BaseModel):
    """共用图谱节点（`C-ACTIVITY-GRAPH@1`）：时间字段缺失保持 ``None``，不补值。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    parent_id: int | None = None
    start_time: str | None = None
    deadline: str | None = None
    assignee_names: list[str] = Field(default_factory=list)


class TaskGraphEdge(BaseModel):
    """依赖边：``from_id`` 为前置，``to_id`` 为当前任务。"""

    model_config = ConfigDict(from_attributes=True)

    from_id: int
    to_id: int


class TaskGraphOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nodes: list[TaskGraphNode] = Field(default_factory=list)
    edges: list[TaskGraphEdge] = Field(default_factory=list)


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
    activity_id: int | None = None
    org_id: int | None = None
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
    depends_on_ids: list[int] = Field(default_factory=list)
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
    activity_title: str | None = None
    parent_title: str | None = None
    # 直接前置 / 直接后继（只含当前用户可见任务，`C-ACTIVITY-GRAPH@1`）
    dependencies: list[TaskBrief] = Field(default_factory=list)
    dependents: list[TaskBrief] = Field(default_factory=list)
    # 局部图谱：当前任务 + 直接前置 + 直接后继，与活动详情共用同一结构
    graph: TaskGraphOut = Field(default_factory=TaskGraphOut)


# --------------------------------------------------------------------------- #
# 活动（契约 `C-DATA-ACTIVITY@1`）
# --------------------------------------------------------------------------- #


class ActivityProgressOut(BaseModel):
    """活动整体进度：只统计第一层任务，子任务完成不等于活动已验收。"""

    model_config = ConfigDict(from_attributes=True)

    total_tasks: int = 0
    completed_tasks: int = 0
    cancelled_tasks: int = 0
    subtask_total: int = 0
    subtask_completed: int = 0
    percent: int = 0
    awaiting_owner_confirm: bool = False


class ActivitySubtaskNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    deadline: str | None = None
    assignee_names: list[str] = Field(default_factory=list)


class ActivityTaskNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    deadline: str | None = None
    assignee_names: list[str] = Field(default_factory=list)
    children: list[ActivitySubtaskNode] = Field(default_factory=list)


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None = None
    location: str | None = None
    start_time: str | None = None
    deadline: str | None = None
    owner_id: int
    owner_name: str = ""
    org: str | None = None
    org_id: int | None = None
    status: str
    created_at: str
    progress: ActivityProgressOut = Field(default_factory=ActivityProgressOut)


class ActivityListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[ActivityOut] = Field(default_factory=list)


class ActivityDetailOut(ActivityOut):
    tasks: list[ActivityTaskNode] = Field(default_factory=list)
    graph: TaskGraphOut = Field(default_factory=TaskGraphOut)


class ActivityCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str = Field(min_length=1, max_length=120)
    description: str | None = None
    location: str | None = None
    start_time: str | None = None
    deadline: str | None = None
    org: str | None = None
    org_id: int | None = None


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


# --------------------------------------------------------------------------- #
# AI 只读问答（契约 `C-AI-CHAT@1`）
# --------------------------------------------------------------------------- #


class AiChatIn(BaseModel):
    """问答请求：``conversation_id`` 缺省时新建会话。

    空消息不在这里判 422，交给服务层统一返回业务错误 4001。
    """

    model_config = ConfigDict(from_attributes=True)

    conversation_id: int | None = None
    message: str = Field(max_length=2000)


class AiCitation(BaseModel):
    """回答来源：只由服务端从当前用户可见任务映射生成。"""

    model_config = ConfigDict(from_attributes=True)

    type: Literal["task"] = "task"
    id: int
    title: str
    activity_id: int | None = None


class AiMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    citations: list[AiCitation] = Field(default_factory=list)
    mock: bool = False
    created_at: str


class AiChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation_id: int
    user_message: AiMessageOut
    assistant_message: AiMessageOut
    mock: bool = False


class AiConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0


class AiConversationListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[AiConversationSummary] = Field(default_factory=list)


class AiConversationDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation: AiConversationSummary
    messages: list[AiMessageOut] = Field(default_factory=list)


__all__ = [
    "ReminderRule",
    "UserOut",
    "LoginIn",
    "LoginOut",
    "OrgOut",
    "OrgCreateIn",
    "OrgMembershipOut",
    "OrgMemberOut",
    "InvitationOut",
    "InvitationCreatedOut",
    "InvitationCreateIn",
    "MemberPatchIn",
    "RegisterIn",
    "PasswordResetIn",
    "PasswordResetRequestOut",
    "MeOut",
    "TaskCreate",
    "TaskUpdate",
    "TaskBrief",
    "TaskGraphNode",
    "TaskGraphEdge",
    "TaskGraphOut",
    "MemberOut",
    "TaskOut",
    "TaskDetailOut",
    "ActivityProgressOut",
    "ActivitySubtaskNode",
    "ActivityTaskNode",
    "ActivityOut",
    "ActivityListOut",

    "ActivityDetailOut",
    "ActivityCreate",
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
    "AiChatIn",
    "AiCitation",
    "AiMessageOut",
    "AiChatOut",
    "AiConversationSummary",
    "AiConversationListOut",
    "AiConversationDetailOut",
]

# --------------------------------------------------------------------------- #
# 前向引用统一解析（`C-DATA@2`）：字符串注解（``"TaskOut"`` / ``"TaskBrief"`` /
# ``"Draft | None"``）在文件末尾一次 rebuild，避免把 TaskOut 提前破坏既有类顺序。
# --------------------------------------------------------------------------- #
ApplyOut.model_rebuild()
VerifyOut.model_rebuild()
ApplicationItemOut.model_rebuild()
ExtractIn.model_rebuild()