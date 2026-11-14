"""AI 只读问答与会话服务（契约 `C-AI-CHAT@1`）。

职责边界：

* 任务上下文委托 ``task_query_service.build_task_context``（按问题相关度），
  最多 20 条；``general`` / ``activity`` / ``task`` 作用域语义保持不变；
* 文档上下文只取 ``org_library_service.search_allowed`` 命中的开放资料片段，
  最多 3 条、整体不超过 1200 字符；
* 回答来源由服务端把模型返回的 ``ref`` 映射回真实任务 / 资料，模型给出的 ID /
  标题不落库；回答成功后自动收藏 ``kind="doc"`` 的引用，失败不影响回答；
* 会话按 ``user_id`` 归属，跨账号读写一律 4040，不泄露资源存在性；
* 会话作用域（``C-AI-SCOPE@1``）绑定通用 / 活动 / 任务，每次读取 / 续写前
  重新校验对象可见性，撤权后 4040 且保留历史行；
* 本模块只写 ``ai_conversations`` / ``ai_messages``，不改变任何业务表。

事务边界（`C-AI-RESERVATION@2`）：模型调用前用 ``BEGIN IMMEDIATE`` 的短事务
预留一份 ``pending`` 额度，模型调用期间不持有任何数据库锁；成功后在同一事务
内写消息并把预留行结算为 ``settled``，模型失败则删除预留行释放额度。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text
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
from app.services import authz, library_ref_service, org_library_service, task_query_service

logger = logging.getLogger(__name__)

MAX_CONTEXT_TASKS = 20
MAX_CONVERSATION_LIST = 50
MAX_CITATIONS = 5
TITLE_LENGTH = 30
#: 文档上下文（`C-AI-DOC-CONTEXT@1`）：最多 3 条片段，整体不超过 1200 字符。
MAX_DOC_ITEMS = 3
MAX_DOC_SNIPPET = 300
MAX_DOC_CONTEXT_CHARS = 1200

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"

#: 会话作用域（`C-AI-SCOPE@1`）：通用会话不绑定对象，活动 / 任务绑定正整数 ID。
SCOPE_GENERAL = "general"
SCOPE_ACTIVITY = "activity"
SCOPE_TASK = "task"
SCOPE_TYPES = (SCOPE_GENERAL, SCOPE_ACTIVITY, SCOPE_TASK)

ERR_NOT_FOUND = 4040
ERR_INVALID_INPUT = 4001
ERR_CONFLICT = 4090
ERR_QUOTA_EXCEEDED = 4290

#: 账本状态值域（`C-AI-RESERVATION@2`）：pending 为生成中的预留，settled 为已结算。
STATUS_PENDING = "pending"
STATUS_SETTLED = "settled"
#: 预留超时：只清理创建时间早于该时长的 pending 行，避免误释放仍在执行的调用。
RESERVATION_TIMEOUT = timedelta(minutes=10)
QUOTA_EXHAUSTED_MSG = "今日 AI 问答额度已用完；任务、通知与审批等协作功能仍可正常使用"

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
    """今日已占用次数：pending 预留与 settled 结算一并计入，避免并发生成超额。"""
    total = db.execute(
        select(func.coalesce(func.sum(AiUsageLedger.units), 0)).where(
            AiUsageLedger.user_id == int(user_id),
            AiUsageLedger.status.in_((STATUS_PENDING, STATUS_SETTLED)),
            func.substr(AiUsageLedger.created_at, 1, 10) == _today_text(),
        )
    ).scalar_one()
    return int(total or 0)


def _begin_immediate(db: Session) -> None:
    """结束旧事务并以 SQLite 写锁（BEGIN IMMEDIATE）开启预留 / 结算事务。"""
    db.rollback()
    db.execute(text("BEGIN IMMEDIATE"))


def _purge_stale_reservations(db: Session, user_id: int) -> None:
    """清理本用户超时仍为 pending 的预留行；未超时的占用不释放。"""
    cutoff = (datetime.now() - RESERVATION_TIMEOUT).strftime("%Y-%m-%d %H:%M:%S")
    db.execute(
        delete(AiUsageLedger).where(
            AiUsageLedger.user_id == int(user_id),
            AiUsageLedger.status == STATUS_PENDING,
            AiUsageLedger.created_at < cutoff,
        )
    )


def _reserve_quota(db: Session, user_id: int, request_id: str | None) -> int:
    """原子预留一份额度，返回 pending 行 id；超限抛 4290，同键冲突抛 IntegrityError。

    整个统计 + 条件插入处于同一 ``BEGIN IMMEDIATE`` 写事务，提交后立即释放锁，
    因此模型调用期间不持有锁。唯一约束冲突由调用方转为重放 / 4090。
    """
    _begin_immediate(db)
    try:
        _purge_stale_reservations(db, user_id)
        if _used_today(db, user_id) >= _quota_limit():
            db.rollback()
            raise ApiError(ERR_QUOTA_EXCEEDED, QUOTA_EXHAUSTED_MSG)
        reservation = AiUsageLedger(
            user_id=int(user_id),
            conversation_id=None,
            assistant_message_id=None,
            request_id=request_id,
            operation="chat",
            status=STATUS_PENDING,
            units=1,
            created_at=_now_text(),
        )
        db.add(reservation)
        db.flush()
        reservation_id = int(reservation.id)
        db.commit()
        return reservation_id
    except ApiError:
        raise
    except Exception:
        db.rollback()
        raise


def _release_reservation(db: Session, reservation_id: int) -> None:
    """在与预留对称的短事务内删除仍为 pending 的预留行（失败 / 结算异常时释放）。

    条件删除同样走 ``BEGIN IMMEDIATE``，避免与并发预留交错；失败重试一次，仍失败
    则抛出冲突错误，而不是只记录日志把额度占满 10 分钟。
    """
    last_error: Exception | None = None
    for _ in range(2):
        try:
            _begin_immediate(db)
            db.execute(
                delete(AiUsageLedger).where(
                    AiUsageLedger.id == int(reservation_id),
                    AiUsageLedger.status == STATUS_PENDING,
                )
            )
            db.commit()
            return
        except Exception as exc:  # noqa: BLE001 - 重试后统一上报
            db.rollback()
            last_error = exc
    logger.error(
        "释放 AI 额度预留失败: reservation_id=%s", reservation_id, exc_info=last_error
    )
    raise ApiError(ERR_CONFLICT, "请求状态同步失败，请稍后重试") from last_error


def _usage_item(ledger: AiUsageLedger) -> AiUsageItem:
    return AiUsageItem.model_validate(ledger)


def _replay(
    db: Session,
    user: User,
    request_id: str,
    *,
    expected_message: str | None = None,
    expected_scope: tuple[str, int | None] | None = None,
) -> AiChatOut | None:
    """按 ``(user_id, request_id)`` 重放首次成功回答；未找到返回 None。

    同键异内容或异作用域不复用旧答案：按既有冲突语义拒绝，避免把旧回答错配给
    不同问题 / 不同作用域。
    """
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
    if expected_message is not None and user_message.content != expected_message:
        raise ApiError(ERR_CONFLICT, "相同 request_id 的请求内容不一致，请重新提问")
    if expected_scope is not None and (
        conversation.scope_type,
        conversation.scope_id,
    ) != expected_scope:
        raise ApiError(ERR_CONFLICT, "相同 request_id 的请求作用域不一致，请重新提问")
    return AiChatOut(
        conversation_id=int(conversation.id),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant),
        mock=bool(assistant.mock),
        replayed=True,
    )


@dataclass(frozen=True)
class _ContextItem:
    """模型上下文的纯值快照：不在模型调用期间持有 ORM 对象。

    ``kind`` 区分 ``task`` / ``activity`` / ``doc``；文档条目没有任务字段，
    只填 ``title`` 与 ``summary``（片段）以及 ``resource_id``。
    """

    ref: str
    title: str
    kind: str = "task"
    task_id: int | None = None
    activity_id: int | None = None
    activity_title: str | None = None
    status: str = ""
    deadline: str | None = None
    location: str | None = None
    description: str | None = None
    sop: str | None = None
    acceptance: str | None = None
    latest_submission: str | None = None
    review_result: str | None = None
    resource_id: int | None = None
    summary: str | None = None


class _RawAnswer(BaseModel):
    """模型原始输出（只接受回答与 ref，其余字段忽略）。"""

    model_config = ConfigDict(extra="ignore")

    answer: str
    refs: list[str] = Field(default_factory=list)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_scope(scope_type: str | None, scope_id: int | None) -> tuple[str, int | None]:
    """归一化会话作用域；非法组合统一 4001（`C-AI-SCOPE@1`）。"""
    normalized = (scope_type or SCOPE_GENERAL).strip()
    if normalized not in SCOPE_TYPES:
        raise ApiError(ERR_INVALID_INPUT, "会话作用域无效")
    if normalized == SCOPE_GENERAL:
        if scope_id is not None:
            raise ApiError(ERR_INVALID_INPUT, "会话作用域无效")
        return SCOPE_GENERAL, None
    if scope_id is None or isinstance(scope_id, bool) or int(scope_id) <= 0:
        raise ApiError(ERR_INVALID_INPUT, "会话作用域无效")
    return normalized, int(scope_id)


def _scope_visible(db: Session, user: User, scope_type: str, scope_id: int) -> bool:
    """作用对象存在且当前用户可见；general 恒为可见。"""
    if scope_type == SCOPE_ACTIVITY:
        activity = db.get(Activity, scope_id)
        return activity is not None and authz.can_view_activity(db, user, activity)
    if scope_type == SCOPE_TASK:
        task = db.get(Task, scope_id)
        return task is not None and authz.can_view_task(db, user, task)
    return True


def _scope_object(db: Session, user: User, scope_type: str, scope_id: int) -> None:
    """校验作用对象存在且当前用户可见；不可见与不存在同样 4040。"""
    if not _scope_visible(db, user, scope_type, scope_id):
        raise ApiError(ERR_NOT_FOUND, "会话作用对象不存在", 404)


def _conversation_scope_visible(db: Session, user: User, conversation: AiConversation) -> bool:
    """列表口径：逐条判断会话作用对象当前是否可见（行本身保留）。"""
    try:
        scope_type, scope_id = _normalize_scope(conversation.scope_type, conversation.scope_id)
    except ApiError:
        return False
    if scope_type == SCOPE_GENERAL:
        return True
    return _scope_visible(db, user, scope_type, int(scope_id))


def _ensure_conversation_scope_visible(
    db: Session, user: User, conversation: AiConversation
) -> None:
    """读取 / 续写前按会话行重新校验作用对象可见性（撤权后拒绝，保留历史行）。"""
    scope_type, scope_id = _normalize_scope(conversation.scope_type, conversation.scope_id)
    if scope_type != SCOPE_GENERAL:
        _scope_object(db, user, scope_type, int(scope_id))


def _visible_context(
    db: Session,
    user: User,
    scope_type: str = SCOPE_GENERAL,
    scope_id: int | None = None,
    question: str = "",
) -> list[_ContextItem]:
    """按问题相关度取当前用户可见任务（委托 ``task_query_service``）。

    没有任何关键词 / 意图命中时按截止时间取最近任务，保持旧行为；
    ``general`` 取全部可见任务，``activity`` / ``task`` 只取对应作用域任务，
    均最多 ``MAX_CONTEXT_TASKS`` 条。
    """
    rows = task_query_service.build_task_context(
        db,
        user,
        question,
        scope_type=scope_type,
        scope_id=scope_id,
        limit=MAX_CONTEXT_TASKS,
    )
    return [
        _ContextItem(
            ref=f"T{index}",
            kind="task",
            task_id=int(row["task_id"]),
            title=str(row["title"]),
            activity_id=row.get("activity_id"),
            activity_title=row["activity_name"],
            status=str(row["status"] or ""),
            deadline=row["deadline"],
            location=row["location"],
            description=row.get("description"),
            sop=row["sop"],
            acceptance=row["acceptance"],
            latest_submission=row["latest_submission"],
            review_result=row["review_result"],
        )
        for index, row in enumerate(rows, start=1)
    ]


def _doc_context(db: Session, user: User, question: str) -> list[_ContextItem]:
    """开放资料片段：最多 3 条、整体不超过 ``MAX_DOC_CONTEXT_CHARS``。

    检索失败只记日志并返回空上下文，不阻断问答（资料是增强信息，不是必需输入）。
    """
    try:
        hits = org_library_service.search_allowed(db, user, question, limit=MAX_DOC_ITEMS)
    except Exception:  # noqa: BLE001 - 资料检索失败不得中断回答
        logger.warning("资料检索失败，跳过文档上下文", exc_info=True)
        return []

    items: list[_ContextItem] = []
    total = 0
    for hit in hits:
        snippet = str(hit.get("snippet") or "").strip()[:MAX_DOC_SNIPPET]
        if not snippet:
            continue
        if total + len(snippet) > MAX_DOC_CONTEXT_CHARS:
            break
        total += len(snippet)
        items.append(
            _ContextItem(
                ref=f"D{len(items) + 1}",
                kind="doc",
                title=str(hit.get("title") or ""),
                summary=snippet,
                resource_id=int(hit["resource_id"]),
            )
        )
    return items


def _citation(item: _ContextItem) -> AiCitation:
    if item.kind == "doc":
        return AiCitation(
            type="doc",
            id=int(item.resource_id or 0),
            title=item.title,
            activity_id=None,
            kind="doc",
            resource_id=item.resource_id,
        )
    return AiCitation(
        type="task",
        id=int(item.task_id or 0),
        title=item.title,
        activity_id=item.activity_id,
        kind=item.kind if item.kind in ("task", "activity") else "task",
    )


def _context_payload(items: list[_ContextItem]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for item in items:
        if item.kind == "doc":
            payload.append(
                {
                    "ref": item.ref,
                    "kind": "doc",
                    "title": item.title,
                    "snippet": item.summary,
                }
            )
            continue
        payload.append(
            {
                "ref": item.ref,
                "kind": item.kind,
                "title": item.title,
                "activity": item.activity_title,
                "status": item.status,
                "deadline": item.deadline,
                "location": item.location,
                "description": item.description,
                "sop": item.sop,
                "acceptance": item.acceptance,
                "latest_submission": item.latest_submission,
                "review_result": item.review_result,
            }
        )
    return payload


def _doc_block(doc_items: list[_ContextItem]) -> str:
    return "参考资料：\n" + "\n".join(f"- {item.title}" for item in doc_items)


def _with_docs(
    answer: str, citations: list[AiCitation], doc_items: list[_ContextItem]
) -> tuple[str, list[AiCitation]]:
    """把文档来源并入回答与 citation。

    有文档命中时为资料预留槽位（优先保留全部 doc 来源，总数仍受 ``MAX_CITATIONS``
    限制），保证正文列出的参考资料都能在 citations 中找到，而不是被任务来源挤掉。
    """
    if not doc_items:
        return answer, citations
    doc_citations = [_citation(item) for item in doc_items[:MAX_CITATIONS]]
    reserved = min(len(doc_citations), MAX_CITATIONS)
    merged = citations[: MAX_CITATIONS - reserved] + doc_citations
    return answer + "\n" + _doc_block(doc_items), merged


def _mock_answer(items: list[_ContextItem], question: str) -> tuple[str, list[AiCitation]]:
    """确定性 mock 回答：只使用可见上下文，便于行为回归。"""
    task_items = [item for item in items if item.kind != "doc"]
    doc_items = [item for item in items if item.kind == "doc"]

    if not task_items:
        if not doc_items:
            return (
                "当前没有你有权限查看的事务，因此暂时无法基于事务数据回答。"
                "可以到事务大厅查看公开范围，或联系组织管理员确认权限。",
                [],
            )
        return (
            "当前没有你有权限查看的任务，但检索到以下参考资料：\n" + _doc_block(doc_items),
            [_citation(item) for item in doc_items[:MAX_CITATIONS]],
        )

    if "活动" in question:
        activity_names: list[str] = []
        for item in task_items:
            if item.activity_title is None:
                continue
            if item.activity_title not in activity_names:
                activity_names.append(item.activity_title)
        if activity_names:
            shown = "、".join(activity_names[:5])
            cited = [item for item in task_items if item.activity_title is not None][:3]
            return _with_docs(
                f"你有权限查看的活动包括：{shown}。每个活动下的任务可以在活动详情中查看，"
                "本回答只使用当前可见范围。",
                [_citation(item) for item in cited],
                doc_items,
            )

    selected = task_items[:3]
    lines = []
    for item in selected:
        activity = f"（{item.activity_title}）" if item.activity_title is not None else ""
        deadline = item.deadline or "未设置截止时间"
        lines.append(f"{item.ref}. {item.title}{activity}，截止：{deadline}")
    answer = (
        f"根据你有权限查看的 {len(task_items)} 项事务，先列出最需要关注的 {len(selected)} 项：\n"
        + "\n".join(lines)
        + "\n以上内容来自当前可见任务；如需查看要求或更新进度，请打开对应任务详情。"
    )
    return _with_docs(answer, [_citation(item) for item in selected], doc_items)


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
        scope_type=conversation.scope_type,
        scope_id=conversation.scope_id,
    )


def chat(
    db: Session,
    user: User,
    *,
    conversation_id: int | None,
    message: str,
    request_id: str | None = None,
    scope_type: str = SCOPE_GENERAL,
    scope_id: int | None = None,
) -> AiChatOut:
    """执行一次只读问答并持久化用户与助手消息。

    顺序：请求幂等检查 → 归属校验 → 作用域一致 → 对象可见性 → 额度检查 →
    读取作用域内可见上下文 → 结束只读事务 → 生成回答 → 写会话、消息与用量账本。
    模型调用期间不持有数据库事务；模型或作用域校验失败时不写任何一行、不扣额度。
    """
    text = message.strip()
    if not text:
        raise ApiError(ERR_INVALID_INPUT, "消息不能为空")

    normalized_scope_type, normalized_scope_id = _normalize_scope(scope_type, scope_id)

    normalized_request_id: str | None = None
    if request_id is not None:
        normalized_request_id = request_id.strip()
        if not normalized_request_id or not REQUEST_ID_PATTERN.fullmatch(normalized_request_id):
            raise ApiError(ERR_INVALID_INPUT, "request_id 格式无效")
        replayed = _replay(
            db,
            user,
            normalized_request_id,
            expected_message=text,
            expected_scope=(normalized_scope_type, normalized_scope_id),
        )
        db.rollback()
        if replayed is not None:
            return replayed

    if conversation_id is not None:
        conversation = _get_conversation(db, user, conversation_id)
        if (
            conversation.scope_type != normalized_scope_type
            or conversation.scope_id != normalized_scope_id
        ):
            raise ApiError(ERR_INVALID_INPUT, "会话作用域无效")
    if normalized_scope_type != SCOPE_GENERAL:
        _scope_object(db, user, normalized_scope_type, int(normalized_scope_id))
    # 只读校验后结束事务，避免模型调用期间持有 SQLite 读锁。
    db.rollback()

    items = _visible_context(db, user, normalized_scope_type, normalized_scope_id, text)
    items.extend(_doc_context(db, user, text))
    db.rollback()

    try:
        reservation_id = _reserve_quota(db, int(user.id), normalized_request_id)
    except IntegrityError as exc:
        db.rollback()
        if normalized_request_id is not None:
            replayed = _replay(db, user, normalized_request_id)
            db.rollback()
            if replayed is not None:
                return replayed
            raise ApiError(ERR_CONFLICT, "该请求正在处理中，请稍后重试") from exc
        raise

    # 模型调用期间不持有数据库锁；失败按预留行释放，不扣额度。
    mock = llm_client.is_mock_mode()
    try:
        if mock:
            answer, citations = _mock_answer(items, text)
        else:
            answer, citations = _real_answer(items, text)
    except Exception:
        _release_reservation(db, reservation_id)
        raise

    try:
        _begin_immediate(db)
        reservation = db.get(AiUsageLedger, reservation_id)
        if reservation is None or reservation.status != STATUS_PENDING:
            db.rollback()
            raise ApiError(ERR_CONFLICT, "该请求已处理，但原回答不可用，请重新提问")

        if conversation_id is None:
            conversation = AiConversation(
                user_id=int(user.id),
                title=text[:TITLE_LENGTH],
                scope_type=normalized_scope_type,
                scope_id=normalized_scope_id,
            )
            db.add(conversation)
            db.flush()
        else:
            conversation = _get_conversation(db, user, conversation_id)
            _ensure_conversation_scope_visible(db, user, conversation)

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

        reservation.status = STATUS_SETTLED
        reservation.conversation_id = int(conversation.id)
        reservation.assistant_message_id = int(assistant_message.id)
        conversation.updated_at = now
        db.commit()
    except ApiError:
        db.rollback()
        _release_reservation(db, reservation_id)
        raise
    except IntegrityError as exc:
        db.rollback()
        _release_reservation(db, reservation_id)
        if normalized_request_id is not None:
            replayed = _replay(db, user, normalized_request_id)
            db.rollback()
            if replayed is not None:
                return replayed
        logger.warning("并发请求唯一约束冲突且未找到可重放结果: %s", exc)
        raise ApiError(ERR_CONFLICT, "请求冲突，请稍后重试") from exc
    except Exception:
        db.rollback()
        _release_reservation(db, reservation_id)
        raise
    db.refresh(user_message)
    db.refresh(assistant_message)

    out = AiChatOut(
        conversation_id=int(conversation.id),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
        mock=mock,
        replayed=False,
    )
    # 回答已提交，引用收藏走独立短事务；任何失败都只记日志，不影响回答返回。
    _record_doc_citations(db, user, citations)
    return out


def _record_doc_citations(db: Session, user: User, citations: list[AiCitation]) -> None:
    """回答成功后自动收藏 ``kind="doc"`` 的资料引用（`C-AI-DOC-CONTEXT@1`）。"""
    resource_ids = [
        int(citation.resource_id)
        for citation in citations
        if citation.kind == "doc" and citation.resource_id is not None
    ]
    if not resource_ids:
        return
    try:
        library_ref_service.record_citations(db, user, resource_ids)
    except Exception:  # noqa: BLE001 - 收藏失败不得影响已成功返回的回答
        db.rollback()
        logger.exception("记录 AI 资料引用失败（user_id=%s）", getattr(user, "id", None))


def get_usage(db: Session, user: User, limit: int = 20) -> AiUsageOut:
    """返回本人今日问答额度与最近用量记录（`C-AI-USAGE@1`）。"""
    used = _used_today(db, int(user.id))
    quota = _quota_limit()
    bounded = max(1, min(int(limit), 50))
    rows = db.execute(
        select(AiUsageLedger)
        .where(
            AiUsageLedger.user_id == int(user.id),
            AiUsageLedger.status == STATUS_SETTLED,
        )
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


def list_conversations(
    db: Session,
    user: User,
    offset: int = 0,
    limit: int = 20,
    scope_type: str | None = None,
    scope_id: int | None = None,
) -> AiConversationListOut:
    """本人会话分页（`C-AI-HISTORY@3`）；给定作用域时只返回该作用域。

    排序固定 ``updated_at DESC, id DESC``（同秒写入也稳定）。``total`` 为同一
    owner、同一 scope 过滤条件下的可见会话总数。不带作用域时逐条重校验作用
    对象可见性（撤权后的 scoped 会话不出现，行与消息保留不删除），因此先过滤
    再切片，保证 ``total`` 与 offset 翻页对齐。
    """
    bounded = max(1, min(int(limit), MAX_CONVERSATION_LIST))
    start = max(0, int(offset))
    scoped_request = scope_type is not None or scope_id is not None
    query = (
        select(AiConversation, func.count(AiMessage.id))
        .outerjoin(AiMessage, AiMessage.conversation_id == AiConversation.id)
        .where(AiConversation.user_id == user.id)
    )
    if scoped_request:
        normalized_type, normalized_id = _normalize_scope(scope_type, scope_id)
        if normalized_type == SCOPE_GENERAL:
            query = query.where(
                AiConversation.scope_type == SCOPE_GENERAL,
                AiConversation.scope_id.is_(None),
            )
        else:
            _scope_object(db, user, normalized_type, int(normalized_id))
            query = query.where(
                AiConversation.scope_type == normalized_type,
                AiConversation.scope_id == normalized_id,
            )
    rows = db.execute(
        query.group_by(AiConversation.id).order_by(
            AiConversation.updated_at.desc(), AiConversation.id.desc()
        )
    ).all()
    visible = [
        (conversation, count)
        for conversation, count in rows
        if scoped_request or _conversation_scope_visible(db, user, conversation)
    ]
    page = visible[start : start + bounded]
    items = [
        AiConversationSummary(
            id=int(conversation.id),
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=int(count),
            scope_type=conversation.scope_type,
            scope_id=conversation.scope_id,
        )
        for conversation, count in page
    ]
    return AiConversationListOut(items=items, total=len(visible))


def get_conversation(db: Session, user: User, conversation_id: int) -> AiConversationDetailOut:
    conversation = _get_conversation(db, user, conversation_id)
    _ensure_conversation_scope_visible(db, user, conversation)
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