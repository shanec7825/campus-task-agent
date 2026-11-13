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
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.agents import llm_client, prompts
from app.errors import ApiError
from app.models import Activity, AiConversation, AiMessage, Task, User
from app.schemas import (
    AiChatOut,
    AiCitation,
    AiConversationDetailOut,
    AiConversationListOut,
    AiConversationSummary,
    AiMessageOut,
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


def chat(db: Session, user: User, *, conversation_id: int | None, message: str) -> AiChatOut:
    """执行一次只读问答并持久化用户与助手消息。

    顺序：归属校验 → 读取可见上下文 → 结束只读事务 → 生成回答 → 写会话与消息。
    模型调用期间不持有数据库事务；模型失败时直接返回错误，不写任何一行。
    """
    text = message.strip()
    if not text:
        raise ApiError(ERR_INVALID_INPUT, "消息不能为空")

    if conversation_id is not None:
        _get_conversation(db, user, conversation_id)
        # 只读校验后结束事务，避免模型调用期间持有 SQLite 读锁。
        db.rollback()

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
    db.add(assistant_message)
    conversation.updated_at = _now_text()
    try:
        db.commit()
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


__all__ = ["chat", "get_conversation", "list_conversations"]