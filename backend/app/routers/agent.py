"""Agent 路由（契约 `C-AGENT@3`，owner = T3）。

三接口均需登录（``Depends(get_current_user)``，plan `2.2.7`）：

* ``POST /api/agent/extract``      —— 文字版解析（``full`` / ``incremental``）+ changes
* ``POST /api/agent/review``      —— 审核（歧义 / 润色 / 拆解建议）+ changes
* ``POST /api/agent/stream/parse`` —— 语音顺序增量解析 + 服务端草稿合并 + changes

合并、diff、追溯文案、纯值校验的**唯一实现**是 ``app.agents.diffing``（纯函数）：
本路由只负责编排与错误码，不再自己写合并逻辑，保证 extract / review / stream
三条路径行为一致。

`C-AGENT@3` B7：``stream/parse`` 只把**本片 chunk** 传给提炼助手，
``parse_sessions.accumulated_text`` 仅用于留痕写库，**不再进入 prompt**。

三接口返回的 ``draft`` 字段值统一经 ``diffing.sanitize_draft`` 净化（回归红线
R13-AC5：字段值不出现 ``AI建议`` / ``改为`` / ``用户：``）。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agents import diffing, extractor, reviewer
from app.db import get_db
from app.deps import get_current_user
from app.errors import ApiError, ok
from app.models import ParseSession, User
from app.schemas import (
    Draft,
    ExtractIn,
    ExtractOut,
    ReviewIn,
    StreamParseIn,
    StreamParseOut,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _now_text() -> str:
    """``YYYY-MM-DD HH:MM:SS``（服务器本地时间，`2.3.1` 时间口径）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _extract_out(payload: ExtractIn) -> ExtractOut:
    """``/extract`` 的核心：解析 → 合并 → diff → 文案（`C-AGENT@2` A 节）。"""
    text = (payload.text or "").strip()
    if not text:
        raise ApiError(4001, "文本不能为空")

    mode = (payload.mode or extractor.FULL_MODE).strip()
    if mode == extractor.INCREMENTAL_MODE and payload.base_draft is None:
        raise ApiError(4001, "增量解析必须提供 base_draft")

    # `mode="full"` 时基座为全空 Draft（忽略 base_draft，保证 P1 行为不回归）
    if mode == extractor.INCREMENTAL_MODE and payload.base_draft is not None:
        base = diffing.sanitize_draft(payload.base_draft)
    else:
        base = Draft()

    raw = extractor.extract_text(text, base, mode)
    merged = diffing.sanitize_draft(diffing.merge_draft(base, raw.draft))
    changes = diffing.diff_draft(base, merged)
    applied_texts = diffing.applied_texts_for(changes)

    return ExtractOut(
        draft=merged,
        # spans 只含本次文本的片段，不合并历史 spans
        spans=raw.spans,
        # unresolved 全量替换为本次结果（Draft 内不保存该字段）
        unresolved=diffing.merge_unresolved(raw.unresolved),
        style_prompt=merged.style_prompt,
        corrections=diffing.merge_corrections(base, raw.corrections),
        mock=raw.mock,
        changes=changes,
        applied_texts=applied_texts,
    )


@router.post("/extract")
def extract(
    payload: ExtractIn,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """文字版解析：``{text, base_draft?, mode?}`` → draft / changes / applied_texts / …。"""
    return ok(_extract_out(payload).model_dump())


@router.post("/review")
def review(
    payload: ReviewIn,
    _current_user: User = Depends(get_current_user),
) -> dict:
    """审核草稿：``{draft}`` → ambiguities / polished / suggested_sub_tasks / changes / mock。"""
    return ok(reviewer.review(payload.draft).model_dump())


@router.post("/stream/parse")
def stream_parse(
    payload: StreamParseIn,
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
) -> dict:
    """语音顺序增量解析：本片 chunk 交模型解析 + 服务端草稿全量合并 + 本片 changes。"""
    session_id = (payload.session_id or "").strip()
    if not session_id:
        raise ApiError(4001, "session_id 不能为空")

    chunk = payload.chunk or ""
    session = db.get(ParseSession, session_id)
    if session is None:
        session = ParseSession(session_id=session_id, accumulated_text="", draft={})
        db.add(session)
        db.flush()

    # ② accumulated_text += chunk（chunk 允许为空串）；仅留痕写库，不进入 prompt（B7）
    accumulated_text = (session.accumulated_text or "") + chunk
    session.accumulated_text = accumulated_text

    # ③ before = 本片解析前的服务端草稿；④ 只传本片 chunk，合并发生在提炼助手内
    before = diffing.sanitize_draft(Draft.model_validate(session.draft or {}))
    result = extractor.extract_stream(before, chunk, bool(payload.is_final))
    merged = diffing.sanitize_draft(result.draft)

    # ⑤ 写回 draft 与 updated_at（is_final 只停止累计，不清空草稿）
    session.draft = merged.model_dump()
    session.updated_at = _now_text()
    db.commit()

    out = StreamParseOut(
        draft=merged,
        spans=result.spans,
        unresolved=diffing.merge_unresolved(result.unresolved),
        corrections=diffing.merge_corrections(before, result.corrections),
        mock=result.mock,
        # changes = 本片合并产生的差异（frontend 语音路径不生成追溯块，故无 applied_texts）
        changes=diffing.diff_draft(before, merged),
    )
    return ok(out.model_dump())


__all__ = ["router"]