"""共享 Pydantic 模型（契约 `C-DATA@1`，T1 冻结）。

字段名与 JSON 键名必须与计划逐字一致；后续 owner 不得修改本文件，
发现契约缺口须报告 Leader。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.errors import ApiError

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


class TaskChangeMember(BaseModel):
    """改期/取消影响到的成员（契约 `C-TASK-CHANGE-API@1`）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TaskChangeDownstream(BaseModel):
    """影响预览中的后续任务：只暴露契约字段，避免带出无权元数据。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str


class TaskChangeImpactOut(BaseModel):
    """改期影响预览：只读，不写库、不发通知。"""

    model_config = ConfigDict(from_attributes=True)

    task_id: int
    title: str
    current_deadline: str | None = None
    proposed_deadline: str | None = None
    reminders_reset: bool = False
    affected_members: list[TaskChangeMember] = Field(default_factory=list)
    downstream_tasks: list[TaskChangeDownstream] = Field(default_factory=list)
    notified_user_ids: list[int] = Field(default_factory=list)


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


class ActivityAssigneeOut(BaseModel):
    """任务执行成员的最小只读投影（契约 `C-ACT-TABLE-DTO@1`）。"""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: str


class ActivitySubtaskNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int | None = None
    title: str
    status: str
    start_time: str | None = None
    deadline: str | None = None
    assignees: list[ActivityAssigneeOut] = Field(default_factory=list)
    assignee_names: list[str] = Field(default_factory=list)


class ActivityTaskNode(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    activity_id: int | None = None
    title: str
    status: str
    start_time: str | None = None
    deadline: str | None = None
    assignees: list[ActivityAssigneeOut] = Field(default_factory=list)
    assignee_names: list[str] = Field(default_factory=list)
    completed_children: int = 0
    total_children: int = 0
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


class ActivityBatchTaskDraft(BaseModel):
    """整批发布中的单个任务草稿（`C-BATCH-PUBLISH@1`）。

    字段集 = ``TaskCreate`` 去掉 ``activity_id`` / ``org_id`` / ``assignee_id`` /
    ``depends_on`` / ``depends_on_ids`` / ``reminder_rule``，另加批内引用字段。
    ``key`` 缺失时由服务层按数组索引生成 ``t0``、``t1``…；``parent_id`` 仅为字段集
    兼容保留，批内父任务必须用 ``parent_key`` 声明。
    """

    model_config = ConfigDict(from_attributes=True)

    key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,32}$")
    parent_id: int | None = None
    title: str = Field(min_length=1)
    description: str | None = None
    location: str | None = None
    start_time: str | None = None
    deadline: str | None = None
    quota: int | None = None
    volunteer_hours: float | None = None
    claim_type: Literal["open", "assign"] = "open"
    depends_on_keys: list[str] = Field(default_factory=list)
    parent_key: str | None = None
    sop_guide: str | None = None
    style_note: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)
    credit_reward: int = 20


class ActivityPublishBatchIn(BaseModel):
    """活动 + 全部任务的整批发布请求（`C-BATCH-PUBLISH@1`）；``tasks`` 允许为空。"""

    model_config = ConfigDict(from_attributes=True)

    activity: ActivityCreate
    tasks: list[ActivityBatchTaskDraft] = Field(default_factory=list)


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
    # 验收绑定的成果版本（`C-SUBMISSION@1`）：指定时必须等于该成员最新版本。
    submission_id: int | None = None


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
    stale: int = 0
    archived: int = 0
    archived_at: str | None = None
    created_at: str


class NotificationListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    unread: int
    total: int = 0
    items: list[NotificationOut] = Field(default_factory=list)


class ReadIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ids: list[int] = Field(default_factory=list)


class ArchiveIn(BaseModel):
    """归档通知（`C-NOTICE-ARCHIVE@1`）：只处理当前用户未归档的记录。"""

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
    # 客户端请求幂等键（`C-AI-USAGE@1`）：同一用户同一键只生成一次回答与账本。
    request_id: str | None = Field(default=None, max_length=64)
    # 会话作用域（`C-AI-SCOPE@1`）：缺省为 general，兼容旧客户端。
    scope_type: Literal["general", "activity", "task"] = "general"
    scope_id: int | None = None


class AiCitation(BaseModel):
    """回答来源：只由服务端从当前用户可见任务 / 开放资料映射生成。

    ``kind`` 区分任务、活动与资料；旧记录没有该字段时按 ``task`` 解析，
    旧客户端忽略不认识的 ``doc`` 项仍可正常展示。``doc`` 项额外带 ``resource_id``。
    """

    model_config = ConfigDict(from_attributes=True)

    type: Literal["task", "doc"] = "task"
    id: int
    title: str
    activity_id: int | None = None
    kind: Literal["task", "activity", "doc"] = "task"
    resource_id: int | None = None


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
    # 同一 request_id 重放时返回首次结果，不再新增消息或账本。
    replayed: bool = False


class AiUsageItem(BaseModel):
    """本人最近一条 AI 用量记录。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int | None = None
    request_id: str | None = None
    operation: str
    status: str
    units: int
    created_at: str


class AiUsageOut(BaseModel):
    """当日 AI 问答额度（`C-AI-USAGE@1`）：``used`` 统计本人 ``pending``/``settled``；``items`` 只列已结算。"""

    model_config = ConfigDict(from_attributes=True)

    date: str
    used: int
    limit: int
    remaining: int
    items: list[AiUsageItem] = Field(default_factory=list)


class AiConversationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    # 会话作用域（`C-AI-SCOPE@1`）：所有列表 / 详情 / 新建路径都返回。
    scope_type: Literal["general", "activity", "task"] = "general"
    scope_id: int | None = None


class AiConversationListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[AiConversationSummary] = Field(default_factory=list)
    # 同 owner（同 scope 过滤条件）的会话总数，供前端判断是否还有更旧记录。
    total: int = 0


class AiConversationDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    conversation: AiConversationSummary
    messages: list[AiMessageOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 资料库（契约 `C-RESOURCE@1`）
# --------------------------------------------------------------------------- #


class ResourceCreateIn(BaseModel):
    """资料新增 / 新版本入参。

    ``resource_key`` 缺省时新建一条资料（version=1）；提供已存在的 key 时，
    服务层在该 key 下追加下一版本，旧版本保留。
    """

    model_config = ConfigDict(from_attributes=True)

    title: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=1000)
    summary: str | None = Field(default=None, max_length=2000)
    resource_type: Literal["link", "document", "note"] = "link"
    activity_id: int | None = None
    task_id: int | None = None
    org_id: int | None = None
    resource_key: str | None = Field(default=None, max_length=80)


class ResourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    resource_key: str
    activity_id: int | None = None
    task_id: int | None = None
    org_id: int | None = None
    activity_title: str | None = None
    title: str
    summary: str | None = None
    resource_type: str = "link"
    url: str
    version: int = 1
    created_by: int
    created_by_name: str = ""
    created_at: str


class ResourceListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[ResourceOut] = Field(default_factory=list)
    total: int = 0


# --------------------------------------------------------------------------- #
# Library 私有参考链接（契约 `C-LIBRARY@1`，设计 §9.2）
# --------------------------------------------------------------------------- #


class LibraryLinkOut(BaseModel):
    """个人链接响应；``owner_id`` 不返回，所有者始终来自当前会话。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    note: str | None = None
    created_at: str
    updated_at: str


class LibraryLinkCreateIn(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=1, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)


class LibraryLinkUpdateIn(BaseModel):
    """PATCH 入参；缺省字段不变，``note: null`` 表示清空说明。"""

    model_config = ConfigDict(from_attributes=True)

    title: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=1000)
    note: str | None = Field(default=None, max_length=2000)


# --------------------------------------------------------------------------- #
# Library 资料引用（契约 `C-LIB-REF@1`）
# --------------------------------------------------------------------------- #


class LibraryRefIn(BaseModel):
    """新增 / 刷新一条资料引用；只接受资料 id，可见性由服务层校验。"""

    model_config = ConfigDict(from_attributes=True)

    resource_id: int = Field(gt=0)


class LibraryRefOut(BaseModel):
    """引用响应：资料快照字段 + 引用时间；不返回 ``owner_id`` 与正文。"""

    model_config = ConfigDict(from_attributes=True)

    resource_id: int
    title: str
    summary: str | None = None
    resource_type: str
    file_name: str | None = None
    file_size: int | None = None
    url: str | None = None
    org_id: int
    added_at: str
    last_used_at: str


# --------------------------------------------------------------------------- #
# 成果版本与预审（契约 `C-SUBMISSION@1` / `C-PRECHECK@1`）
# --------------------------------------------------------------------------- #


class SubmitIn(BaseModel):
    """提交成果（可选）：旧的无 body 提交仍按空内容生成一条版本。"""

    model_config = ConfigDict(from_attributes=True)

    content: str | None = Field(default=None, max_length=5000)
    resource_url: str | None = Field(default=None, max_length=1000)


class PrecheckItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    status: Literal["pass", "fail", "warn", "unknown"]
    message: str
    evidence: str | None = None
    source: str | None = None


class PrecheckSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    message: str
    evidence: str | None = None


class PrecheckResourceSnapshot(BaseModel):
    """预审引用的资料版本快照（`C-PRECHECK-EVIDENCE@2`）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    version: int


class PrecheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    submission_id: int
    requirement_digest: str
    checks: list[PrecheckItem] = Field(default_factory=list)
    verdict: Literal["pass", "fail", "unknown"]
    summary: str | None = None
    ai_suggestions: list[PrecheckSuggestion] = Field(default_factory=list)
    resource_snapshot: list[PrecheckResourceSnapshot] = Field(default_factory=list)
    mock: bool = False
    ai_error: str | None = None
    created_at: str


class PrecheckSummary(BaseModel):
    """列表内展示的预审摘要；``stale`` 表示任务要求或引用资料已变化。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    verdict: Literal["pass", "fail", "unknown"]
    summary: str | None = None
    mock: bool = False
    ai_error: str | None = None
    requirement_digest: str
    stale: bool = False
    created_at: str


class SubmissionFileIn(BaseModel):
    """成果文件上传（`C-SUBMISSION-FILE@1`）：JSON + base64，不引入 multipart 依赖。"""

    model_config = ConfigDict(from_attributes=True)

    file_name: str = Field(min_length=1, max_length=255)
    file_base64: str = Field(min_length=1)
    content: str | None = Field(default=None, max_length=5000)


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    user_id: int
    user_name: str = ""
    version: int
    content: str | None = None
    resource_url: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    file_mime: str | None = None
    created_at: str
    latest: bool = True
    precheck: PrecheckSummary | None = None


class SubmissionListOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    items: list[SubmissionOut] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# 组织资料库（契约 `C-ORG-LIBRARY@1`）
# --------------------------------------------------------------------------- #


class OrgResourceFileIn(BaseModel):
    """上传文件描述：JSON + base64，不引入 multipart 依赖。

    ``size`` 为声明的字节数，服务层解码后必须与 ``data_base64`` 实际长度一致。
    """

    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=255)
    mime: str = Field(default="", max_length=200)
    size: int = Field(ge=0)
    data_base64: str = Field(min_length=1)


class OrgResourceCreateIn(BaseModel):
    """组织资料新增入参；``file`` 与 ``url`` 二选一由服务层校验（同时给或都不给 → 4001）。"""

    model_config = ConfigDict(from_attributes=True)

    org_id: int
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=1000)
    file: OrgResourceFileIn | None = None


class OrgResourcePatchIn(BaseModel):
    """PATCH 入参：只改传入字段；服务层按 ``model_fields_set`` 区分缺省与显式值。"""

    model_config = ConfigDict(from_attributes=True)

    title: str | None = Field(default=None, min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=2000)
    allow_student_ai: bool | None = None
    archived: bool | None = None


class OrgResourceOut(BaseModel):
    """组织资料响应；不返回 ``content_text`` / ``search_text`` / ``file_path``。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    org_id: int
    title: str
    summary: str | None = None
    resource_type: str
    url: str | None = None
    file_name: str | None = None
    file_mime: str | None = None
    file_size: int | None = None
    text_status: Literal["pending", "ready", "failed"] = "pending"
    allow_student_ai: bool = False
    archived: bool = False
    created_by: int
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
# 成果提交策略（契约 `C-SUBMISSION-POLICY@1`）
# --------------------------------------------------------------------------- #

SUBMISSION_MODES: tuple[str, ...] = ("text", "link", "file")
SUBMISSION_ALLOWED_EXTS: tuple[str, ...] = (".pdf", ".docx", ".txt", ".md")
ACCEPTANCE_KEY = "acceptance"
MSG_ACCEPTANCE_MODES_INVALID = "成果提交方式配置不合法"
MSG_ACCEPTANCE_EXTS_INVALID = "成果文件类型配置不合法"
MSG_ACCEPTANCE_INVALID = "成果提交策略配置不合法"


class SubmissionAcceptance(BaseModel):
    """任务成果提交策略；存放于 ``tasks.extras["acceptance"]``。

    ``modes`` 必须是非空子集 ``text|link|file``；``allowed_exts`` 是
    ``.pdf|.docx|.txt|.md`` 的子集（不带点或大小写差异会被规范化），
    仅在 ``modes`` 含 ``file`` 时具有约束力。非法配置统一抛 4001。
    """

    model_config = ConfigDict(extra="ignore")

    modes: list[str]
    allowed_exts: list[str] = Field(default_factory=list)
    ai_precheck: bool = False

    @field_validator("modes")
    @classmethod
    def _check_modes(cls, value: list[str]) -> list[str]:
        if not value or any(str(item) not in SUBMISSION_MODES for item in value):
            raise ApiError(4001, MSG_ACCEPTANCE_MODES_INVALID)
        return list(dict.fromkeys(str(item) for item in value))

    @field_validator("allowed_exts")
    @classmethod
    def _check_allowed_exts(cls, value: list[str]) -> list[str]:
        exts: list[str] = []
        for item in value:
            ext = str(item).strip().lower()
            if ext and not ext.startswith("."):
                ext = f".{ext}"
            if ext not in SUBMISSION_ALLOWED_EXTS:
                raise ApiError(4001, MSG_ACCEPTANCE_EXTS_INVALID)
            if ext not in exts:
                exts.append(ext)
        return exts

    def allows(self, mode: str) -> bool:
        return mode in self.modes


def normalize_acceptance(extras: dict[str, Any] | None) -> dict[str, Any]:
    """校验并规范化 ``extras`` 中的 ``acceptance``（写库前调用，纯函数）。

    返回新字典，其它键原样保留；``acceptance`` 缺失或显式为 ``null`` 时视为
    未配置（不写入该键），非法值抛 4001。
    """
    normalized = dict(extras or {})
    if ACCEPTANCE_KEY not in normalized:
        return normalized
    raw = normalized[ACCEPTANCE_KEY]
    if raw is None:
        normalized.pop(ACCEPTANCE_KEY, None)
        return normalized
    if not isinstance(raw, dict):
        raise ApiError(4001, MSG_ACCEPTANCE_MODES_INVALID)
    try:
        policy = SubmissionAcceptance.model_validate(raw)
    except ValidationError as exc:
        # 字段类型本身不合法（如 modes 传字符串）时统一转成 4001，避免落成 500
        raise ApiError(4001, MSG_ACCEPTANCE_INVALID) from exc
    normalized[ACCEPTANCE_KEY] = {
        "modes": policy.modes,
        "allowed_exts": policy.allowed_exts,
        "ai_precheck": policy.ai_precheck,
    }
    return normalized


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
    "ActivityAssigneeOut",
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
    "ResourceCreateIn",
    "ResourceOut",
    "ResourceListOut",
    "SubmitIn",
    "PrecheckItem",
    "PrecheckSuggestion",
    "PrecheckResourceSnapshot",
    "PrecheckOut",
    "PrecheckSummary",
    "SubmissionOut",
    "SubmissionListOut",
    "SubmissionAcceptance",
    "SUBMISSION_MODES",
    "SUBMISSION_ALLOWED_EXTS",
    "ACCEPTANCE_KEY",
    "normalize_acceptance",
    "OrgResourceFileIn",
    "OrgResourceCreateIn",
    "OrgResourcePatchIn",
    "OrgResourceOut",
]

# --------------------------------------------------------------------------- #
# 前向引用统一解析（`C-DATA@2`）：字符串注解（``"TaskOut"`` / ``"TaskBrief"`` /
# ``"Draft | None"``）在文件末尾一次 rebuild，避免把 TaskOut 提前破坏既有类顺序。
# --------------------------------------------------------------------------- #
ApplyOut.model_rebuild()
VerifyOut.model_rebuild()
ApplicationItemOut.model_rebuild()
ExtractIn.model_rebuild()