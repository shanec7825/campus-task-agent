"""提炼助手（契约 `C-AGENT@3`，owner = T3）。

职责：把 ``llm_client`` 的原始 JSON 归一化成 :class:`ExtractOut`，
并提供 mock / 真实两条等价路径（mock 判定唯一来源 = ``llm_client.is_mock_mode()``）。

真实路径的 Prompt 见 ``prompts.EXTRACTOR_SYSTEM_PROMPT``（§5.1 逐字 + P2/P3 追加段）；
其输出 Schema 已按 plan `2.2.7` 追加 ``spans`` 数组（原文片段 → 字段名）。

P2 增量模式（`C-AGENT@2` A.4 第 3 条）：``mode="incremental"`` 时把**本次增量文本**
连同 ``当前草稿`` 一起发给模型，只让模型解析增量；user payload 键名固定为
``当前时间 / 用户文本 / 当前草稿 / 模式``。

P3 顺序增量链式（`C-AGENT@3` B7）：``extract_stream`` 只把**本次新增片段**发给
模型（payload 三键：``本次新增片段 / 当前已合并草稿 / 是否最终``，**不再把全量文本
拼进 prompt**），返回结果在**本模块内**与 ``before_draft`` 合并，保证多片之间不会
因重复解析旧内容而反复产出同一条 change。

合并、diff、文案生成全部由 ``app.agents.diffing``（纯函数）完成，本模块只做编排。

值净化（`C-AGENT@2` G 节，R13-AC5 回归红线）：写入 ``Draft`` 前的文本值一律经
``diffing.sanitize_value``，保证字段值不出现 ``AI建议`` / ``改为`` / ``用户：``。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agents import diffing, llm_client, mock_fixtures, prompts
from app.errors import ApiError
from app.schemas import CorrectionOut, Draft, ExtractOut, SpanOut

logger = logging.getLogger(__name__)

# `2.2.7`：spans[].field 的白名单（extras 的键名在运行时动态加入）
SPAN_FIELD_WHITELIST: frozenset[str] = frozenset(
    {
        "title",
        "time",
        "deadline",
        "location",
        "details",
        "quota",
        "volunteer_hours",
        "notes",
        "requirements",
        "extra_tags",
    }
)

#: 解析模式（`C-AGENT@2`：`/extract` 的 ``mode``）
FULL_MODE = "full"
INCREMENTAL_MODE = "incremental"


class _RawExtract(BaseModel):
    """LLM 原始输出（宽松类型 + 缺省值，避免因个别字段类型偏差判定为非法）。"""

    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    time: str | None = None
    deadline: str | None = None
    location: str | None = None
    details: str | None = None
    quota: float | None = None
    volunteer_hours: float | None = None
    notes: str | None = None
    requirements: str | None = None
    extra_tags: dict[str, Any] = Field(default_factory=dict)
    style_prompt: str | None = None
    unresolved: list[Any] = Field(default_factory=list)
    corrections: list[CorrectionOut] = Field(default_factory=list)
    spans: list[SpanOut] = Field(default_factory=list)
    half_sentence: bool = False


def _clean_text(value: str | None) -> str | None:
    """去首尾空白；空串按"未提到"处理（-> None）。"""
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def _safe_text(value: str | None) -> str | None:
    """文本字段的**唯一**写入通道：先值净化（剥离追溯句），再去空白。"""
    return _clean_text(diffing.sanitize_value(value))


def _clean_quota(value: float | None) -> int | None:
    if value is None:
        return None
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_extra_tags(raw: dict[str, Any]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for key, value in (raw or {}).items():
        key_text = _safe_text(str(key)) if key is not None else None
        if key_text is None or value is None:
            continue
        value_text = _safe_text(str(value))
        if value_text is None:
            continue
        cleaned[key_text] = value_text
    return cleaned


def _clean_spans(raw_spans: list[SpanOut], extra_keys: set[str]) -> list[SpanOut]:
    """过滤非法 field（契约：只允许白名单或 extras 键名）。"""
    allowed = SPAN_FIELD_WHITELIST | extra_keys
    spans: list[SpanOut] = []
    for span in raw_spans or []:
        text = _clean_text(span.text)
        if text is None:
            continue
        field = span.field if span.field in allowed else None
        spans.append(SpanOut(text=text, field=field))
    return spans


def _to_extract_out(raw: _RawExtract) -> ExtractOut:
    """把 LLM 原始输出归一化为对外契约 ``ExtractOut``。"""
    extra_tags = _clean_extra_tags(raw.extra_tags)
    style_prompt = _clean_text(raw.style_prompt)
    draft = Draft(
        title=_safe_text(raw.title),
        time=_safe_text(raw.time),
        deadline=_safe_text(raw.deadline),
        location=_safe_text(raw.location),
        details=_safe_text(raw.details),
        quota=_clean_quota(raw.quota),
        volunteer_hours=float(raw.volunteer_hours) if raw.volunteer_hours is not None else None,
        notes=_safe_text(raw.notes),
        requirements=_safe_text(raw.requirements),
        extra_tags=extra_tags,
        style_prompt=style_prompt,
    )
    return ExtractOut(
        draft=draft,
        spans=_clean_spans(raw.spans, set(extra_tags.keys())),
        unresolved=diffing.merge_unresolved(raw.unresolved),
        # 契约：顶层 style_prompt 与 draft.style_prompt 必须一致
        style_prompt=style_prompt,
        corrections=diffing.merge_corrections(None, raw.corrections),
        mock=False,
    )


def _validate_raw(payload: dict) -> _RawExtract:
    """``chat_json`` 的校验回调（Pydantic 强校验）。"""
    return _RawExtract.model_validate(payload)


def _call_llm(user_payload: dict[str, Any]) -> ExtractOut:
    """调用真实 LLM，并把 ``LLMError`` 统一转成 ``ApiError``（500x）。"""
    try:
        raw = llm_client.chat_json(
            prompts.render_extractor_prompt(),
            json.dumps(user_payload, ensure_ascii=False),
            validate=_validate_raw,
        )
    except llm_client.LLMError as exc:
        logger.warning("提炼助手调用失败: code=%s msg=%s", exc.code, exc.message)
        raise ApiError(exc.code, exc.message) from exc
    return _to_extract_out(raw)


def _incremental_payload(text: str, base_draft: Draft | None) -> dict[str, Any]:
    """增量模式的 user payload（键名与顺序按 `C-AGENT@2` A.4 第 3 条固定）。"""
    base = base_draft if base_draft is not None else Draft()
    return {
        "当前时间": prompts.now_text(),
        "用户文本": text or "",
        "当前草稿": base.model_dump(),
        "模式": "incremental",
    }


def extract_text(text: str, base_draft: Draft | None = None, mode: str = FULL_MODE) -> ExtractOut:
    """文字版解析（`POST /api/agent/extract`）。

    * ``mode="full"``：完全沿用 P1 行为（``base_draft`` 被忽略）；
    * ``mode="incremental"``：只解析本次增量文本，并附带 ``当前草稿`` 供模型对齐。

    返回值是**本次解析的增量结果**（``draft`` 只含本次提到的字段）；与基座草稿的
    合并、``changes`` / ``applied_texts`` 生成由路由层调用 ``diffing`` 完成。
    """
    if mode == INCREMENTAL_MODE:
        if llm_client.is_mock_mode():
            return mock_fixtures.mock_extract(
                text or "",
                is_final=True,
                base_draft=base_draft,
                mode=INCREMENTAL_MODE,
            )
        return _call_llm(_incremental_payload(text, base_draft))

    if llm_client.is_mock_mode():
        return mock_fixtures.mock_extract(text or "", is_final=True)
    return _call_llm({"当前时间": prompts.now_text(), "用户文本": text or ""})


def extract_stream(before_draft: Draft, chunk: str, is_final: bool) -> ExtractOut:
    """语音流式**顺序增量**解析（`POST /api/agent/stream/parse`，`C-AGENT@3` B7）。

    user payload 固定三键（**不含全量文本**）：

    * ``本次新增片段``：本片新内容，模型只解析它；
    * ``当前已合并草稿``：``before_draft.model_dump()``，供模型判断"已有非空字段不必重述"；
    * ``是否最终``：本片是否为最后一片。

    模型（或 mock 规则）只产出**本片**的增量字段，返回后在本函数内与
    ``before_draft`` 合并（``diffing.merge_draft``）；字段级 diff 仍由路由层用
    ``diffing.diff_draft(before, merged)`` 生成，因此不会重复产出旧片 change。
    """
    before = before_draft if before_draft is not None else Draft()

    if llm_client.is_mock_mode():
        # mock 规则只作用于本片（incremental 模式不把原话写进 details），
        # 与 before_draft 的合并由 mock_extract 内部调用 merge_draft 完成。
        return mock_fixtures.mock_extract(
            chunk or "",
            is_final=is_final,
            base_draft=before,
            mode=INCREMENTAL_MODE,
        )

    raw = _call_llm(
        {
            "本次新增片段": chunk or "",
            "当前已合并草稿": before.model_dump(),
            "是否最终": bool(is_final),
        }
    )
    merged = diffing.sanitize_draft(diffing.merge_draft(before, raw.draft))
    return ExtractOut(
        draft=merged,
        spans=raw.spans,
        unresolved=diffing.merge_unresolved(raw.unresolved),
        style_prompt=merged.style_prompt,
        corrections=diffing.merge_corrections(before, raw.corrections),
        mock=False,
    )


__all__ = [
    "SPAN_FIELD_WHITELIST",
    "FULL_MODE",
    "INCREMENTAL_MODE",
    "extract_text",
    "extract_stream",
]