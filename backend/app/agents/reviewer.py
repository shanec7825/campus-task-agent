"""审核助手（契约 `C-AGENT@3`，owner = T3）。

职责：按 §5.2 的 System Prompt 获取"找茬 / 提问 / 润色 / 拆解建议"，
并做契约要求的归一化（plan `2.2.7` 与决策 D4）：

* ``suggested_sub_tasks`` 超过 6 条截断为 6 条；
* ``polished`` 缺项补空串；``details`` 与 ``notes`` 全部缺失时整体置 ``null``；
* 无 ``style_prompt`` 且无介绍请求时 ``polished`` 必须为 ``null``。

P3 修订（`C-AGENT@3` B10）：当 :func:`diffing.needs_intro` 为真（``details`` 为空且
有 ``style_prompt`` 或草稿文本含"生成介绍 / 帮我写 / 润色"类请求）时，模型**必须**
给出完整介绍文案放进 ``polished.details``。该文案只是建议内容，仍不进入
``changes`` / 任何数据字段；模型两次都没给出时按输出不合法（5003）报错，不静默。

P2 增量（`C-AGENT@2` D 节）：额外把 ``ambiguities[].suggestion`` 转成字段级
``changes``（``source="ai"``、``new_value`` 必须是**纯数据值**）。纯值判定与字段
归一化统一使用 ``app.agents.diffing``，**不在本文件内重写一套判定**；
未通过纯值校验的建议不产出 change（宁缺勿污染，R13-AC4），``ambiguities`` 原样保留。

T2 的 ``/api/tasks/{id}/decompose`` 也直接调用 :func:`review`。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.agents import diffing, llm_client, mock_fixtures, prompts
from app.errors import ApiError
from app.schemas import Ambiguity, Draft, Polished, ReviewOut, SubTaskSuggestion

logger = logging.getLogger(__name__)

MAX_SUB_TASKS = 6


class _RawReview(BaseModel):
    """LLM 原始输出（``polished`` 允许部分字段缺失，由后端补空串）。"""

    model_config = ConfigDict(extra="ignore")

    ambiguities: list[Ambiguity] = Field(default_factory=list)
    polished: dict[str, Any] | None = None
    suggested_sub_tasks: list[SubTaskSuggestion] = Field(default_factory=list)


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def normalize_polished(
    raw: dict[str, Any] | None,
    has_style: bool,
    intro_requested: bool = False,
) -> Polished | None:
    """归一化 ``polished``（决策 D4 + B10）。

    * 无 ``style_prompt`` **且**无介绍请求 ⇒ ``None``（契约硬要求）；
    * 两个字段都缺失 / 为空 ⇒ ``None``；
    * 仅缺一个字段 ⇒ 缺失项补空串。

    ``intro_requested``（B10）为真时，即使没有 ``style_prompt`` 也允许产出
    ``polished``（介绍文案兜底）。
    """
    if not (has_style or intro_requested) or not isinstance(raw, dict):
        return None

    details = _clean_text(raw.get("details"))
    notes = _clean_text(raw.get("notes"))
    if details is None and notes is None:
        return None
    return Polished(details=details or "", notes=notes or "")


def _to_review_out(raw: _RawReview, draft: Draft) -> ReviewOut:
    ambiguities = [
        item for item in raw.ambiguities if _clean_text(item.field) and _clean_text(item.question)
    ]
    # 建议值净化：模型可能把「AI建议：改为 14:00」整句塞进 suggestion
    ambiguities = [
        item.model_copy(update={"suggestion": diffing.sanitize_value(item.suggestion)})
        for item in ambiguities
    ]
    polished = normalize_polished(
        raw.polished,
        bool(_clean_text(draft.style_prompt)),
        intro_requested=diffing.needs_intro(draft),
    )
    return ReviewOut(
        ambiguities=ambiguities[:MAX_SUB_TASKS],
        polished=polished,
        suggested_sub_tasks=raw.suggested_sub_tasks[:MAX_SUB_TASKS],
        mock=False,
        # 唯一派生入口：diffing（纯值校验 + 字段归一化 + old_value 取值）
        changes=diffing.changes_from_ambiguities(draft, ambiguities)
        + diffing.changes_from_polished(draft, polished),
    )


def _make_validator(draft: Draft) -> Callable[[dict], _RawReview]:
    """构造 ``chat_json`` 的校验回调（Pydantic 强校验 + B10 介绍文案硬校验）。

    校验器内抛异常 ⇒ ``llm_client`` 视为"输出不合法"并按 temperature 0.3→0.1
    重试一次；两次都不合格 ⇒ ``LLMError(5003)`` ⇒ ``ApiError(5003)``，不静默。
    """
    has_style = bool(_clean_text(draft.style_prompt))
    intro_requested = diffing.needs_intro(draft)

    def _validate(payload: dict) -> _RawReview:
        raw = _RawReview.model_validate(payload)
        if intro_requested and (
            normalize_polished(raw.polished, has_style, intro_requested=True) is None
        ):
            raise ValueError("审核助手未按契约给出完整介绍文案（polished.details 为空）")
        return raw

    return _validate


def review(draft: Draft) -> ReviewOut:
    """审核草稿（`POST /api/agent/review`、`POST /api/tasks/{id}/decompose`）。"""
    if llm_client.is_mock_mode():
        return mock_fixtures.mock_review(draft)

    try:
        raw = llm_client.chat_json(
            prompts.render_reviewer_prompt(),
            json.dumps(draft.model_dump(), ensure_ascii=False),
            validate=_make_validator(draft),
        )
    except llm_client.LLMError as exc:
        logger.warning("审核助手调用失败: code=%s msg=%s", exc.code, exc.message)
        raise ApiError(exc.code, exc.message) from exc
    return _to_review_out(raw, draft)


__all__ = ["MAX_SUB_TASKS", "normalize_polished", "review"]