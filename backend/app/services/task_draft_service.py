"""AI 任务树草案服务（契约 `C-AI-DRAFT@1`）。

* 只读：不写活动 / 任务 / 资料行，草案由前端填入发布表单后走既有整批发布接口；
* 检索范围限定为**可管理组织**：提供 ``org_id`` 时只检索该组织；未提供时只检索
  用户 ``admin|collaborator`` 的组织；没有任何可管理组织 → ``4030``；
* 参考资料最多 3 条，无开放资料时仍可生成（``sources=[]``）；
* 真实模型经 ``llm_client.chat_json``（强制 JSON + 校验失败重试一次），
  输出不合法统一 ``5030``，其余模型错误沿用既有 5001/5002 口径；
* 真实模型分支带进程内滑动窗口限流（每用户 60 秒 3 次，超限 ``4290``），
  mock 分支不受限。**未接入** ``ai_usage_ledger``：草案是低频的管理配置操作，
  不产生会话消息，也不改变问答额度口径；后续若要统一成本治理，可在账本中以
  ``operation="task_draft"`` 记录成功调用并复用同一额度上限；
* mock 返回确定性的 3 任务树，保证离线演示；
* 草案结构严格对齐整批发布校验：key 必须合法且唯一（重复 key 的任务直接丢弃），
  父任务必须存在且自身无父（仅一层父子），依赖必须存在、同层、无自依赖与无环；
  非法任务丢弃并记 warning，保证留下的草案可直接通过 ``publish-batch`` 校验。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.agents import llm_client, prompts
from app.errors import ApiError
from app.models import User
from app.schemas import TaskDraftItem, TaskDraftOut, TaskDraftSource
from app.services import authz, org_library_service

logger = logging.getLogger(__name__)

ERR_INVALID_PARAM = 4001
ERR_FORBIDDEN = 4030
ERR_TOO_MANY_REQUESTS = 4290
ERR_INVALID_OUTPUT = 5030

MAX_SOURCES = 3
MAX_TASKS = 8
MAX_SNIPPET_CHARS = 200
MAX_TITLE_CHARS = 120
MAX_SOP_CHARS = 2000
#: 检索候选上限（与 ``org_library_service.MAX_SEARCH_LIMIT`` 对齐），
#: 先取候选再按可管理组织过滤，最后只返回 ``MAX_SOURCES`` 条来源。
MAX_SEARCH_CANDIDATES = 20

#: 真实模型限流：每用户 60 秒 3 次（进程内滑动窗口，仅真实分支生效）。
REAL_RATE_LIMIT = 3
REAL_RATE_WINDOW_SECONDS = 60.0
_REAL_CALL_TIMES: dict[int, deque[float]] = {}
_REAL_CALL_LOCK = threading.Lock()

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
MOCK_TASK_COUNT = 3


class _RawTask(BaseModel):
    """模型返回的单个任务节点（多余字段忽略）。"""

    model_config = ConfigDict(extra="ignore")

    key: str | None = None
    title: str = Field(min_length=1, max_length=200)
    sop_guide: str | None = None
    deadline: str | None = None
    depends_on_keys: list[str] = Field(default_factory=list)
    parent_key: str | None = None


class _RawDraft(BaseModel):
    """模型返回的任务树（校验失败由 ``chat_json`` 重试一次）。"""

    model_config = ConfigDict(extra="ignore")

    activity_title: str = Field(min_length=1, max_length=200)
    tasks: list[_RawTask] = Field(default_factory=list)


def _clip(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _scope_org_ids(db: Session, user: User, org_id: int | None) -> set[int]:
    """草案可检索的组织范围：显式组织只取该组织，否则取全部可管理组织。"""
    if org_id is not None:
        org_library_service.require_manager(db, user, int(org_id))
        return {int(org_id)}
    managed = authz.org_ids_for(db, user, roles=authz.PUBLISH_ROLES)
    if not managed:
        raise ApiError(ERR_FORBIDDEN, "仅组织管理者可使用任务草案", 403)
    return {int(item) for item in managed}


def _check_real_rate_limit(user: User) -> None:
    """真实模型每用户滑动窗口限流；超限 4290。mock 分支不调用。"""
    now = time.monotonic()
    with _REAL_CALL_LOCK:
        window = _REAL_CALL_TIMES.setdefault(int(user.id), deque())
        while window and now - window[0] >= REAL_RATE_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= REAL_RATE_LIMIT:
            raise ApiError(ERR_TOO_MANY_REQUESTS, "操作过于频繁，请稍后再试", 429)
        window.append(now)


def _retrieve(
    db: Session, user: User, prompt: str, scope_org_ids: set[int]
) -> tuple[list[TaskDraftSource], list[dict[str, object]]]:
    """检索可管理组织内的开放资料：最终来源与模型片段均最多 3 条。"""
    hits = org_library_service.search_allowed(
        db, user, prompt, limit=MAX_SEARCH_CANDIDATES
    )
    scoped = [hit for hit in hits if int(hit.get("org_id") or 0) in scope_org_ids]
    scoped = scoped[:MAX_SOURCES]
    sources = [
        TaskDraftSource(resource_id=int(hit["resource_id"]), title=str(hit["title"]))
        for hit in scoped
    ]
    materials = [
        {
            "title": str(hit["title"]),
            "snippet": str(hit.get("snippet") or "").strip()[:MAX_SNIPPET_CHARS],
        }
        for hit in scoped
    ]
    return sources, materials


def _short_title(prompt: str) -> str:
    first_line = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    title = (first_line or "AI 任务草案")[:40]
    return title or "AI 任务草案"


def _mock_payload(prompt: str) -> dict[str, object]:
    """确定性 mock 草案：固定 3 个任务的线性树。"""
    title = _short_title(prompt)
    return {
        "activity_title": title,
        "tasks": [
            {
                "key": "t0",
                "title": f"{title} · 需求确认",
                "sop_guide": "1. 阅读活动需求；2. 确认时间与地点；3. 输出任务清单。",
                "deadline": None,
                "depends_on_keys": [],
                "parent_key": None,
            },
            {
                "key": "t1",
                "title": f"{title} · 物资准备",
                "sop_guide": "1. 列出物资清单；2. 联系场地负责人；3. 完成采购与清点。",
                "deadline": None,
                "depends_on_keys": ["t0"],
                "parent_key": None,
            },
            {
                "key": "t2",
                "title": f"{title} · 现场执行",
                "sop_guide": "1. 按清单布置场地；2. 现场分工；3. 结束后复盘归档。",
                "deadline": None,
                "depends_on_keys": ["t0"],
                "parent_key": None,
            },
        ][:MOCK_TASK_COUNT],
    }


def _real_payload(prompt: str, materials: list[dict[str, object]]) -> dict[str, object]:
    """真实模型草案；输出不合法重试一次后仍失败 ⇒ 5030。"""
    user_payload = json.dumps(
        {"需求": prompt, "可参考资料": materials}, ensure_ascii=False
    )
    try:
        raw = llm_client.chat_json(
            prompts.render_task_draft_prompt(),
            user_payload,
            validate=_RawDraft.model_validate,
        )
    except llm_client.LLMError as exc:
        if exc.code == llm_client.CODE_INVALID_OUTPUT:
            raise ApiError(ERR_INVALID_OUTPUT, "AI 草案生成失败，请稍后重试") from exc
        raise ApiError(exc.code, exc.message) from exc
    except Exception as exc:  # noqa: BLE001 - 客户端初始化等非 LLMError 统一按 5001
        logger.warning("任务树草案调用异常: %s", exc)
        raise ApiError(llm_client.CODE_API_ERROR, "LLM 调用失败，请稍后重试") from exc
    return raw.model_dump() if isinstance(raw, BaseModel) else dict(raw)


def _invalid_reason(
    task: TaskDraftItem, tasks: dict[str, TaskDraftItem]
) -> str | None:
    """单个任务相对当前任务集合的结构问题（None 表示合法）。"""
    parent_key = task.parent_key
    if parent_key is not None:
        parent = tasks.get(parent_key)
        if parent is None:
            return f"父任务 {parent_key} 不存在"
        if parent.parent_key is not None:
            return f"父任务 {parent_key} 自身还有父任务（仅支持一层父子）"
    for dep_key in task.depends_on_keys:
        if dep_key == task.key:
            return "不能依赖自身"
        dep = tasks.get(dep_key)
        if dep is None:
            return f"依赖任务 {dep_key} 不存在"
        if dep.parent_key != parent_key:
            return f"依赖任务 {dep_key} 与当前任务不在同一层级"
    return None


def _drop_invalid(
    tasks: dict[str, TaskDraftItem], warnings: list[str]
) -> None:
    """迭代剔除结构非法任务，直到集合稳定（父/依赖被剔除会连带剔除下游）。"""
    while True:
        changed = False
        for key, task in list(tasks.items()):
            reason = _invalid_reason(task, tasks)
            if reason is None:
                continue
            warnings.append(f"任务 {key} 被丢弃：{reason}")
            del tasks[key]
            changed = True
        if not changed:
            return


def _cyclic_keys(tasks: dict[str, TaskDraftItem]) -> set[str]:
    """返回处于依赖环内的任务 key（迭代遍历，任务数 ≤8）。"""
    cyclic: set[str] = set()
    for start in tasks:
        stack = list(tasks[start].depends_on_keys)
        seen: set[str] = set()
        while stack:
            node = stack.pop()
            if node == start:
                cyclic.add(start)
                break
            if node in seen or node not in tasks:
                continue
            seen.add(node)
            stack.extend(tasks[node].depends_on_keys)
    return cyclic


def _normalize_tasks(
    raw_tasks: list[dict[str, object]]
) -> tuple[list[TaskDraftItem], list[str]]:
    """校验并收敛任务树，返回 ``(可发布任务, 丢弃/调整说明)``。

    丢弃规则与 ``activity_service._validate_batch_drafts`` 对齐：key 合法且唯一、
    父存在且自身无父、依赖存在 / 同层 / 非自依赖 / 无环；重复依赖去重。
    """
    warnings: list[str] = []
    tasks: dict[str, TaskDraftItem] = {}

    for index, raw in enumerate(task for task in raw_tasks if isinstance(task, dict)):
        if index >= MAX_TASKS:
            break
        key = str(raw.get("key") or "").strip()
        if not KEY_PATTERN.fullmatch(key):
            warnings.append(f"任务 {index + 1} 的 key 非法（{key!r}），已丢弃")
            continue
        if key in tasks:
            warnings.append(f"任务 key 重复（{key}），已丢弃重复节点")
            continue

        dependencies: list[str] = []
        for ref in raw.get("depends_on_keys") or []:
            dep = str(ref).strip()
            if not dep:
                continue
            if dep in dependencies:
                warnings.append(f"任务 {key} 的重复依赖已去重：{dep}")
                continue
            dependencies.append(dep)
        parent_key = str(raw.get("parent_key") or "").strip() or None

        tasks[key] = TaskDraftItem(
            key=key,
            title=str(raw.get("title") or "").strip()[:MAX_TITLE_CHARS]
            or f"任务 {index + 1}",
            sop_guide=_clip(raw.get("sop_guide"), MAX_SOP_CHARS),
            deadline=_clip(raw.get("deadline"), 32),
            depends_on_keys=dependencies,
            parent_key=parent_key,
        )

    _drop_invalid(tasks, warnings)
    cyclic = _cyclic_keys(tasks)
    for key in sorted(cyclic):
        warnings.append(f"任务 {key} 被丢弃：依赖关系成环")
        tasks.pop(key, None)
    if cyclic:
        _drop_invalid(tasks, warnings)

    return list(tasks.values()), warnings


def generate(
    db: Session, user: User, prompt: str, org_id: int | None = None
) -> TaskDraftOut:
    """生成可编辑任务树草案；不写任何表，也不触发发布。

    ``org_id`` 提供时按 ``org_library_service.require_manager`` 校验（4040/4030），
    且只检索该组织资料；未提供时只检索用户可管理组织（admin/collaborator），
    没有任何可管理组织返回 4030。真实模型分支按用户限流（4290）。
    """
    text = (prompt or "").strip()
    if not text:
        raise ApiError(ERR_INVALID_PARAM, "草案需求不能为空")

    scope_org_ids = _scope_org_ids(db, user, org_id)
    mock = llm_client.is_mock_mode()
    if not mock:
        _check_real_rate_limit(user)

    sources, materials = _retrieve(db, user, text, scope_org_ids)
    payload = _mock_payload(text) if mock else _real_payload(text, materials)

    raw_tasks = payload.get("tasks") if isinstance(payload, dict) else None
    tasks, warnings = _normalize_tasks(list(raw_tasks or []))
    if warnings:
        logger.warning(
            "任务树草案丢弃/调整 %s 处：%s", len(warnings), "；".join(warnings)
        )
    activity_title = (
        str(payload.get("activity_title") or "").strip()[:MAX_TITLE_CHARS]
        if isinstance(payload, dict)
        else ""
    ) or _short_title(text)

    return TaskDraftOut(
        activity_title=activity_title,
        tasks=tasks,
        sources=sources,
        mock=mock,
    )


__all__ = [
    "ERR_INVALID_OUTPUT",
    "ERR_TOO_MANY_REQUESTS",
    "MAX_SEARCH_CANDIDATES",
    "MAX_SOURCES",
    "MAX_TASKS",
    "REAL_RATE_LIMIT",
    "REAL_RATE_WINDOW_SECONDS",
    "generate",
]