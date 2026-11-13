"""AI 只读问答与会话服务（契约 `C-AI-CHAT@1`）。

职责边界：

* 上下文只取 ``authz.visible_task_filter`` 命中的任务，最多 20 条；
* 回答来源由服务端把模型返回的 ``ref`` 映射回真实任务，模型给出的 ID / 标题不落库；
* 会话按 ``user_id`` 归属，跨账号读写一律 4040，不泄露资源存在性；
* 本模块只写 ``ai_conversations`` / ``ai_messages``，不改变任何业务表。

事务边界：可见上下文与模型调用均在写库前完成，模型调用期间不持有 SQLite
读写事务；模型失败时不会留下半条会话。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.agents import llm_client, prompts
from app.errors import ApiError
from app.models import Activity, AiConversation, AiMessage, AiUsageLedger, Task, User
from app.schemas import (
    AiChatOut,
    AiCitation,
    AiConversationDetailOut,
    AiConversationListOut,
    AiConversationSummary,
    AiMessageOut,
    AiUsageItem,
    AiUsageOut,
)
from app.services import authz

logger = logging.getLogger(__name__)

MAX_CONTEXT_TASKS = 20
MAX_CONVERSATION_LIST = 50
MAX_CITATIONS = 5
TITLE_LENGTH = 30

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

ERR_NOT_FOUND = 4040
ERR_INVALID_INPUT = 4001
ERR_CONFLICT = 4090
ERR_QUOTA_EXCEEDED = 4290

#: 每日问答次数上限默认值（`C-AI-USAGE@1`）；0 表示当天不可生成，但协作功能不受影响。
DEFAULT_DAILY_QUOTA = 50
#: 请求幂等键格式：1–64 位字母、数字、下划线或连字符。
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _quota_limit() -> int:
    raw = os.getenv("AI_DAILY_QUOTA", str(DEFAULT_DAILY_QUOTA)).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("AI_DAILY_QUOTA=%r 非法，回退默认 %s", raw, DEFAULT_DAILY_QUOTA)
        return DEFAULT_DAILY_QUOTA
    return max(0, value)


def _today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _used_today(db: Session, user_id: int) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(AiUsageLedger.units), 0)).where(
            AiUsageLedger.user_id == int(user_id),
            AiUsageLedger.status == "settled",
            func.substr(AiUsageLedger.created_at, 1, 10) == _today_text(),
        )
    ).scalar_one()
    return int(total or 0)


def _usage_item(ledger: AiUsageLedger) -> AiUsageItem:
    return AiUsageItem.model_validate(ledger)


def _replay(db: Session, user: User, request_id: str) -> AiChatOut | None:
    """按 ``(user_id, request_id)`` 重放首次成功回答；未找到返回 None。"""
    ledger = db.execute(
        select(AiUsageLedger).where(
            AiUsageLedger.user_id == int(user.id),
            AiUsageLedger.request_id == request_id,
        )
    ).scalars().first()
    if ledger is None:
        return None
    if (
        ledger.status != "settled"
        or ledger.conversation_id is None
        or ledger.assistant_message_id is None
    ):
        raise ApiError(ERR_CONFLICT, "该请求正在处理中，请稍后重试")
    conversation = db.get(AiConversation, int(ledger.conversation_id))
    assistant = db.get(AiMessage, int(ledger.assistant_message_id))
    if (
        conversation is None
        or assistant is None
        or int(conversation.user_id) != int(user.id)
    ):
        raise ApiError(ERR_CONFLICT, "该请求已处理，但原回答不可用，请重新提问")
    user_message = db.execute(
        select(AiMessage)
        .where(
            AiMessage.conversation_id == int(conversation.id),
            AiMessage.role == ROLE_USER,
            AiMessage.id < int(assistant.id),
        )
        .order_by(AiMessage.id.desc())
        .limit(1)
    ).scalars().first()
    if user_message is None:
        raise ApiError(ERR_CONFLICT, "该请求已处理，但原回答不可用，请重新提问")
    return AiChatOut(
        conversation_id=int(conversation.id),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant),
        mock=bool(assistant.mock),
        replayed=True,
    )


@dataclass(frozen=True)
class _ContextItem:
    """模型上下文的纯值快照：不在模型调用期间持有 ORM 对象。"""

    ref: str
    task_id: int
    title: str
    activity_id: int | None
    activity_title: str | None
    status: str
    deadline: str | None
    location: str | None
    description: str | None


class _RawAnswer(BaseModel):
    """模型原始输出（只接受回答与 ref，其余字段忽略）。"""

    model_config = ConfigDict(extra="ignore")

    answer: str
    refs: list[str] = Field(default_factory=list)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _visible_context(db: Session, user: User) -> list[_ContextItem]:
    """按截止时间取当前用户可见任务摘要（NULL 截止排在最后）。"""
    rows = db.execute(
        select(Task, Activity)
        .outerjoin(Activity, Activity.id == Task.activity_id)
        .where(authz.visible_task_filter(db, user))
        .order_by(
            case((Task.deadline.is_(None), 1), else_=0),
            Task.deadline.asc(),
            Task.id.asc(),
        )
        .limit(MAX_CONTEXT_TASKS)
    ).all()
    items: list[_ContextItem] = []
    for index, (task, activity) in enumerate(rows, start=1):
        description = (task.description or "").strip()
        items.append(
            _ContextItem(
                ref=f"T{index}",
                task_id=int(task.id),
                title=task.title,
                activity_id=int(activity.id) if activity is not None else None,
                activity_title=activity.title if activity is not None else None,
                status=task.status,
                deadline=task.deadline,
                location=task.location,
                description=description[:300] if description else None,
            )
        )
    return items


def _citation(item: _ContextItem) -> AiCitation:
    return AiCitation(
        type="task",
        id=item.task_id,
        title=item.title,
        activity_id=item.activity_id,
    )


def _context_payload(items: list[_ContextItem]) -> list[dict[str, Any]]:
    return [
        {
            "ref": item.ref,
            "title": item.title,
            "activity": item.activity_title,
            "status": item.status,
            "deadline": item.deadline,
            "location": item.location,
            "description": item.description,
        }
        for item in items
    ]


def _mock_answer(items: list[_ContextItem], question: str) -> tuple[str, list[AiCitation]]:
    """确定性 mock 回答：只使用可见上下文，便于行为回归。"""
    if not items:
        return (
            "当前没有你有权限查看的事务，因此暂时无法基于事务数据回答。"
            "可以到事务大厅查看公开范围，或联系组织管理员确认权限。",
            [],
        )

    if "活动" in question:
        activity_names: list[str] = []
        for item in items:
            if item.activity_title is None:
                continue
            if item.activity_title not in activity_names:
                activity_names.append(item.activity_title)
        if activity_names:
            shown = "、".join(activity_names[:5])
            cited = [item for item in items if item.activity_title is not None][:3]
            return (
                f"你有权限查看的活动包括：{shown}。每个活动下的任务可以在活动详情中查看，"
                "本回答只使用当前可见范围。",
                [_citation(item) for item in cited],
            )

    selected = items[:3]
    lines = []
    for item in selected:
        activity = f"（{item.activity_title}）" if item.activity_title is not None else ""
        deadline = item.deadline or "未设置截止时间"
        lines.append(f"{item.ref}. {item.title}{activity}，截止：{deadline}")
    answer = (
        f"根据你有权限查看的 {len(items)} 项事务，先列出最需要关注的 {len(selected)} 项：\n"
        + "\n".join(lines)
        + "\n以上内容来自当前可见任务；如需查看要求或更新进度，请打开对应任务详情。"
    )
    return answer, [_citation(item) for item in selected]


def _real_answer(items: list[_ContextItem], question: str) -> tuple[str, list[AiCitation]]:
    """真实模型回答：只接受 ref，来源由服务端映射。"""
    payload = {"问题": question, "可见事务": _context_payload(items)}
    system_prompt = prompts.render_qa_prompt()
    user_payload = json.dumps(payload, ensure_ascii=False)
    try:
        raw = llm_client.chat_json(
            system_prompt,
            user_payload,
            validate=_RawAnswer.model_validate,
        )
    except llm_client.LLMError as exc:
        logger.warning("只读问答调用失败: code=%s msg=%s", exc.code, exc.message)
        raise ApiError(exc.code, exc.message) from exc
    except Exception as exc:  # noqa: BLE001 - 客户端初始化等非 LLMError 异常统一按 5001
        logger.warning("只读问答调用异常: %s", exc)
        raise ApiError(llm_client.CODE_API_ERROR, "LLM 调用失败，请稍后重试") from exc

    answer = (raw.answer or "").strip()
    if not answer:
        raise ApiError(llm_client.CODE_INVALID_OUTPUT, "LLM 返回内容为空")

    by_ref = {item.ref: item for item in items}
    citations: list[AiCitation] = []
    seen: set[str] = set()
    for ref in raw.refs:
        if ref in seen or ref not in by_ref:
            continue
        seen.add(ref)
        citations.append(_citation(by_ref[ref]))
        if len(citations) >= MAX_CITATIONS:
            break
    return answer, citations


def _get_conversation(db: Session, user: User, conversation_id: int) -> AiConversation:
    conversation = db.get(AiConversation, conversation_id)
    if conversation is None or int(conversation.user_id) != int(user.id):
        raise ApiError(ERR_NOT_FOUND, "会话不存在", 404)
    return conversation


def _message_out(message: AiMessage) -> AiMessageOut:
    return AiMessageOut(
        id=int(message.id),
        role=message.role,
        content=message.content,
        citations=list(message.citations or []),
        mock=bool(message.mock),
        created_at=message.created_at,
    )


def _summary(db: Session, conversation: AiConversation) -> AiConversationSummary:
    count = db.execute(
        select(func.count(AiMessage.id)).where(AiMessage.conversation_id == conversation.id)
    ).scalar_one()
    return AiConversationSummary(
        id=int(conversation.id),
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=int(count),
    )


def chat(
    db: Session,
    user: User,
    *,
    conversation_id: int | None,
    message: str,
    request_id: str | None = None,
) -> AiChatOut:
    """执行一次只读问答并持久化用户与助手消息。

    顺序：请求幂等检查 → 归属校验 → 额度检查 → 读取可见上下文 → 结束只读事务 →
    生成回答 → 写会话、消息与用量账本。模型调用期间不持有数据库事务；模型失败时
    直接返回错误，不写任何一行、不扣额度。
    """
    text = message.strip()
    if not text:
        raise ApiError(ERR_INVALID_INPUT, "消息不能为空")

    normalized_request_id: str | None = None
    if request_id is not None:
        normalized_request_id = request_id.strip()
        if not normalized_request_id or not REQUEST_ID_PATTERN.fullmatch(normalized_request_id):
            raise ApiError(ERR_INVALID_INPUT, "request_id 格式无效")
        replayed = _replay(db, user, normalized_request_id)
        db.rollback()
        if replayed is not None:
            return replayed

    if conversation_id is not None:
        _get_conversation(db, user, conversation_id)
        # 只读校验后结束事务，避免模型调用期间持有 SQLite 读锁。
        db.rollback()

    limit = _quota_limit()
    used = _used_today(db, int(user.id))
    db.rollback()
    if used >= limit:
        raise ApiError(
            ERR_QUOTA_EXCEEDED,
            "今日 AI 问答额度已用完；任务、通知与审批等协作功能仍可正常使用",
        )

    items = _visible_context(db, user)
    db.rollback()

    mock = llm_client.is_mock_mode()
    if mock:
        answer, citations = _mock_answer(items, text)
    else:
        answer, citations = _real_answer(items, text)

    if conversation_id is None:
        conversation = AiConversation(user_id=int(user.id), title=text[:TITLE_LENGTH])
        db.add(conversation)
        db.flush()
    else:
        conversation = _get_conversation(db, user, conversation_id)

    now = _now_text()
    user_message = AiMessage(
        conversation_id=int(conversation.id),
        role=ROLE_USER,
        content=text,
        citations=[],
        mock=0,
        created_at=now,
    )
    assistant_message = AiMessage(
        conversation_id=int(conversation.id),
        role=ROLE_ASSISTANT,
        content=answer,
        citations=[citation.model_dump() for citation in citations],
        mock=1 if mock else 0,
        created_at=_now_text(),
    )
    db.add(user_message)
    db.flush()
    db.add(assistant_message)
    db.flush()

    # 模型调用期间可能有并发请求已提交；写账本前在同一事务内二次校验（审查 I5）。
    # SQLite 单写者下可缩小竞态窗口；这是次数软上限，不是分布式配额。
    if _used_today(db, int(user.id)) >= limit:
        db.rollback()
        raise ApiError(
            ERR_QUOTA_EXCEEDED,
            "今日 AI 问答额度已用完；任务、通知与审批等协作功能仍可正常使用",
        )

    db.add(
        AiUsageLedger(
            user_id=int(user.id),
            conversation_id=int(conversation.id),
            assistant_message_id=int(assistant_message.id),
            request_id=normalized_request_id,
            operation="chat",
            status="settled",
            units=1,
            created_at=_now_text(),
        )
    )
    conversation.updated_at = _now_text()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if normalized_request_id is not None:
            replayed = _replay(db, user, normalized_request_id)
            db.rollback()
            if replayed is not None:
                return replayed
            logger.warning("并发请求唯一约束冲突且未找到可重放结果: %s", exc)
            raise ApiError(ERR_CONFLICT, "请求冲突，请稍后重试") from exc
        raise
    except Exception:
        db.rollback()
        raise
    db.refresh(user_message)
    db.refresh(assistant_message)

    return AiChatOut(
        conversation_id=int(conversation.id),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
        mock=mock,
        replayed=False,
    )


def get_usage(db: Session, user: User, limit: int = 20) -> AiUsageOut:
    """返回本人今日问答额度与最近用量记录（`C-AI-USAGE@1`）。"""
    used = _used_today(db, int(user.id))
    quota = _quota_limit()
    bounded = max(1, min(int(limit), 50))
    rows = db.execute(
        select(AiUsageLedger)
        .where(AiUsageLedger.user_id == int(user.id))
        .order_by(AiUsageLedger.id.desc())
        .limit(bounded)
    ).scalars().all()
    return AiUsageOut(
        date=_today_text(),
        used=used,
        limit=quota,
        remaining=max(0, quota - used),
        items=[_usage_item(row) for row in rows],
    )


def list_conversations(db: Session, user: User, limit: int = 20) -> AiConversationListOut:
    bounded = max(1, min(int(limit), MAX_CONVERSATION_LIST))
    rows = db.execute(
        select(AiConversation, func.count(AiMessage.id))
        .outerjoin(AiMessage, AiMessage.conversation_id == AiConversation.id)
        .where(AiConversation.user_id == user.id)
        .group_by(AiConversation.id)
        .order_by(AiConversation.updated_at.desc(), AiConversation.id.desc())
        .limit(bounded)
    ).all()
    return AiConversationListOut(
        items=[
            AiConversationSummary(
                id=int(conversation.id),
                title=conversation.title,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                message_count=int(count),
            )
            for conversation, count in rows
        ]
    )


def get_conversation(db: Session, user: User, conversation_id: int) -> AiConversationDetailOut:
    conversation = _get_conversation(db, user, conversation_id)
    messages = db.execute(
        select(AiMessage)
        .where(AiMessage.conversation_id == conversation.id)
        .order_by(AiMessage.id.asc())
    ).scalars().all()
    return AiConversationDetailOut(
        conversation=_summary(db, conversation),
        messages=[_message_out(message) for message in messages],
    )


__all__ = ["chat", "get_conversation", "get_usage", "list_conversations"]