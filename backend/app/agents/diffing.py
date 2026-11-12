"""草稿增量合并 / 字段级 diff / 追溯文案 / 纯值校验（契约 `C-AGENT@3`，owner = T3）。

本模块是**纯函数模块**：零 I/O、无网络、无随机、不读当前时间；不得 import
LLM 客户端、ORM 数据库会话或时间模块（保证 T8 可独立 import 做纯函数断言，
不触发任何外部依赖）。
extract / review / stream 三条路径共用同一份实现（plan `2.3.1` 的唯一实现位置表），
T8 可直接 import 本模块做纯函数断言。

`C-AGENT@3` 修订：

* B8：``style_prompt`` 由「非空覆盖」改为「叠加拼接」（:func:`join_style_prompt`），
  多轮风格指令不再互相覆盖；
* B10：新增 :func:`needs_intro`，作为「审核助手必须给出完整介绍文案」的唯一判定，
  ``reviewer`` 与 ``mock_fixtures`` 共用，避免两套条件。


约定：
* ``Draft`` 不含 ``unresolved`` / ``corrections``（它们是 ``ExtractOut`` 的顶层字段），
  因此这两项的合并语义由 :func:`merge_unresolved` / :func:`merge_corrections` 提供，
  并在路由层拼装 ``ExtractOut`` 时使用。
* ``new_value`` 一律经 :func:`is_pure_value` 过滤：未通过则丢弃该条 change
  （宁缺勿污染，R13-AC4），并写一条 warning 日志。
"""

from __future__ import annotations

import logging
import re

from app.schemas import Ambiguity, ChangeOut, CorrectionOut, Draft, Polished

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 常量（唯一来源；前端 `utils/traceText.ts` 的 FIELD_LABELS 与此逐字一致）
# --------------------------------------------------------------------------- #

#: 9 个标量字段（diff 与合并的**固定顺序**，applied_texts 与 changes 依赖该顺序）
#: ``deadline``（截止时间）与 ``time``（开始时间）是两个独立字段，互不派生。
SCALAR_FIELDS: tuple[str, ...] = (
    "title",
    "time",
    "deadline",
    "location",
    "details",
    "quota",
    "volunteer_hours",
    "notes",
    "requirements",
)

#: 字段中文名（`applied_texts` 文案模板的唯一来源）
FIELD_LABELS: dict[str, str] = {
    "title": "标题",
    "time": "时间",
    "deadline": "截止时间",
    "location": "地点",
    "details": "详情",
    "quota": "名额",
    "volunteer_hours": "志愿时长",
    "notes": "备注",
    "requirements": "要求",
}

#: 扩展项字段路径前缀（``extra_tags.<键名>``）
EXTRA_TAG_PREFIX = "extra_tags."

#: 纯值上限长度 / 禁用语（R13-AC2）
PURE_VALUE_MAX_LEN = 64
PURE_VALUE_FORBIDDEN: tuple[str, ...] = (
    "建议",
    "改为",
    "请",
    "或",
    "可",
    "推荐",
    "AI",
    "用户：",
    "：",
)

#: 值净化标记（命中即说明该值被写进了追溯句，R13-AC5 回归红线）
_TRACE_PREFIX_MARKERS: tuple[str, ...] = ("AI建议", "改为", "用户：")
_QUOTED_RE = re.compile(r"「([^」]{1,200})」")

#: 整段润色文本的句末标点：出现即代表"这是一段叙述"，不是可直接落库的纯数据值
_SENTENCE_END_MARKERS: tuple[str, ...] = ("。", "！", "？", "!", "?", "；", "\n")

#: 建议来源前缀（`ai` / `user`）
_SOURCE_PREFIX: dict[str, str] = {"ai": "AI建议", "user": "用户"}

#: B8：``style_prompt`` 多段拼接的分隔符
STYLE_PROMPT_SEPARATOR = "、"

#: B10：草稿文本中出现这些请求词时，审核助手必须给出完整介绍文案
INTRO_REQUEST_KEYWORDS: tuple[str, ...] = (
    "生成介绍",
    "生成一段",
    "生成一段介绍",
    "帮我写",
    "帮我生成",
    "写一段",
    "写个介绍",
    "写介绍",
    "介绍文案",
    "润色",
)


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #


def _is_blank(value: object) -> bool:
    """``None`` 或空白字符串视为"本片未给出"。"""
    if value is None:
        return True
    return isinstance(value, str) and not value.strip()


def _as_text(value: object) -> str:
    """把任意标量渲染成文案里用的字符串（``None`` -> 空串）。"""
    if value is None:
        return ""
    return str(value)


def _typed_value(field: str, value: object) -> object:
    """按字段类型输出（``quota`` -> int，``volunteer_hours`` -> float，文本 -> str）。

    契约要求 "``quota`` / ``volunteer_hours`` 输出为 int / float，不做字符串化"，
    而文本字段输出 ``str``。
    """
    if value is None:
        return None
    if field == "quota":
        try:
            return int(round(float(value)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    if field == "volunteer_hours":
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
    return str(value).strip()


def _same_value(left: object, right: object) -> bool:
    """去空白后按 ``str()`` 归一比较（输出仍保留原始类型）。"""
    return _as_text(left).strip() == _as_text(right).strip()


def _split_field(field: str) -> tuple[str, str]:
    """返回 ``(文案用标签, 扩展项键名)``；标量字段的键名为字段名本身。"""
    if field.startswith(EXTRA_TAG_PREFIX):
        key = field[len(EXTRA_TAG_PREFIX) :]
        return key, key
    return FIELD_LABELS.get(field, field), field


# --------------------------------------------------------------------------- #
# 纯值判定与值净化（唯一实现）
# --------------------------------------------------------------------------- #


def is_pure_value(value: object) -> bool:
    """纯数据值判定（`C-AGENT@2` 的 E 节，唯一实现）。

    * ``None`` -> ``False``；``bool`` -> ``False``（布尔不是数据值）；
    * ``int`` / ``float`` -> ``True``（如名额 ``5``）；
    * ``str`` -> strip 后非空、长度 ≤ :data:`PURE_VALUE_MAX_LEN`、无换行、
      且不含 :data:`PURE_VALUE_FORBIDDEN` 任一子串；
    * 其他类型（list/dict）-> ``False``。
    """
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > PURE_VALUE_MAX_LEN:
        return False
    if "\n" in text or "\r" in text:
        return False
    return not any(marker in text for marker in PURE_VALUE_FORBIDDEN)


def sanitize_value(value: str | None) -> str | None:
    """值净化（`C-AGENT@2` 的 G 节，回归红线 R13-AC5）。

    1. ``None`` 或 strip 后为空 -> ``None``；
    2. 命中 ``AI建议`` / ``改为`` / ``用户：`` -> 取**最后一个**「…」内的内容；
       无「」可提取 -> ``None``（丢弃，记 warning）；
    3. 其余原样返回（已 strip）。
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if any(marker in text for marker in _TRACE_PREFIX_MARKERS):
        matches = _QUOTED_RE.findall(text)
        if not matches:
            logger.warning("值净化丢弃疑似追溯句的值: %r", text)
            return None
        return matches[-1].strip() or None
    return text


def sanitize_draft(draft: Draft) -> Draft:
    """对草稿的数据字段做值净化（``quota`` 已是数值，不参与文本净化）。

    ``trace`` / ``style_prompt`` 原样保留（前者是前端权威数据，后者是表达指令）。
    """
    data = draft.model_dump()
    for field in ("title", "time", "deadline", "location", "details", "notes", "requirements"):
        data[field] = sanitize_value(data.get(field))
    data["extra_tags"] = {
        str(key): cleaned
        for key, value in (draft.extra_tags or {}).items()
        if (cleaned := sanitize_value(str(value))) is not None
    }
    data["trace"] = draft.trace
    return Draft.model_validate(data)


# --------------------------------------------------------------------------- #
# 合并（`C-AGENT@2` 的 A.4 合并表，`C-AGENT@3` B8 修订 style_prompt 分支）
# --------------------------------------------------------------------------- #


def _split_style_parts(value: object) -> list[str]:
    """把 ``style_prompt`` 按「、」拆成去空白的片段列表。"""
    text = _as_text(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(STYLE_PROMPT_SEPARATOR) if part.strip()]


def join_style_prompt(base_style: object, incoming_style: object) -> str | None:
    """``style_prompt`` 叠加拼接（B8）。

    * base / incoming 均非空且 trim 后相同 -> 保留 base（不重复拼接）；
    * 均非空且不同 -> 按「、」拆分、去重（保留首次出现顺序）后用「、」连接；
    * 一方为空 -> 取另一方；双方都为空 -> ``None``。

    **不做**语义矛盾判断（用户可能先后给出看似冲突的风格要求，全部保留）。
    """
    base_parts = _split_style_parts(base_style)
    incoming_parts = _split_style_parts(incoming_style)

    if not base_parts:
        return STYLE_PROMPT_SEPARATOR.join(incoming_parts) or None
    if not incoming_parts or base_parts == incoming_parts:
        return STYLE_PROMPT_SEPARATOR.join(base_parts)

    merged: list[str] = []
    for part in base_parts + incoming_parts:
        if part not in merged:
            merged.append(part)
    return STYLE_PROMPT_SEPARATOR.join(merged)


def needs_intro(draft: Draft) -> bool:
    """审核助手是否**必须**给出完整介绍文案（B10）。

    条件（全部满足）：

    * ``draft.details`` 为空（已有详情就不需要重新生成整段介绍）；
    * 且 ``draft.style_prompt`` 非空，**或**草稿文本里含"生成介绍 / 帮我写 / 润色"
      这类请求词。

    说明：``/api/agent/review`` 的入参只有 ``draft``，拿不到原始用户文本，因此
    "用户文本含请求"以草稿可获得的文本（title / notes / requirements /
    extra_tags 的值）近似判断。
    """
    if not _is_blank(draft.details):
        return False
    if not _is_blank(draft.style_prompt):
        return True
    blob = " ".join(
        [
            _as_text(draft.title),
            _as_text(draft.notes),
            _as_text(draft.requirements),
            *(str(value) for value in (draft.extra_tags or {}).values()),
        ]
    )
    return any(keyword in blob for keyword in INTRO_REQUEST_KEYWORDS)


def merge_draft(base: Draft | None, incoming: Draft) -> Draft:
    """把增量解析结果合并进基座草稿。

    规则（逐条对应契约）：

    ================================  ===========================================
    项                                规则
    ================================  ===========================================
    9 个标量字段                       ``incoming`` 非 ``None`` 且非空白才覆盖
    ``extra_tags``                    键级合并；空白的新值忽略
    ``style_prompt``                  叠加拼接（B8，见 :func:`join_style_prompt`）
    ``trace``                         **原样保留** ``base.trace``（后端不清洗/不排序）
    ================================  ===========================================

    ``mode="full"`` 时由调用方传入 ``base=None``（等价于全空 :class:`Draft`）。
    ``corrections`` / ``unresolved`` 不在 ``Draft`` 内，见 :func:`merge_corrections`
    / :func:`merge_unresolved`。
    """
    base_draft = base if base is not None else Draft()
    data = base_draft.model_dump()

    for field in SCALAR_FIELDS:
        value = getattr(incoming, field, None)
        if _is_blank(value):
            continue
        data[field] = value

    merged_tags: dict[str, str] = dict(base_draft.extra_tags or {})
    for key, value in (incoming.extra_tags or {}).items():
        key_text = str(key).strip()
        if not key_text or _is_blank(value):
            continue
        merged_tags[key_text] = str(value).strip()
    data["extra_tags"] = merged_tags

    joined_style = join_style_prompt(base_draft.style_prompt, incoming.style_prompt)
    if joined_style is not None:
        data["style_prompt"] = joined_style

    # trace 原样透传（不复制、不重建、不排序）
    data["trace"] = base_draft.trace
    return Draft.model_validate(data)


def merge_corrections(base: Draft | None, corrections: list[CorrectionOut] | None) -> list[CorrectionOut]:
    """``corrections`` 按 ``target`` 覆盖；模型未给 ``old_value`` 时取合并前的值。

    同一 ``target`` 只保留一条（后出现的覆盖先出现的），顺序按首次出现位置。
    ``new_value`` 经值净化；净化后为空（纯追溯句且无「」可提取）的条目丢弃。
    """
    base_draft = base if base is not None else Draft()
    ordered: dict[str, CorrectionOut] = {}

    for correction in corrections or []:
        target = (correction.target or "").strip()
        if not target:
            continue
        new_value = sanitize_value(correction.new_value)
        if new_value is None:
            logger.warning("丢弃无法净化的 correction: target=%s new_value=%r", target, correction.new_value)
            continue

        old_value = correction.old_value
        if _is_blank(old_value):
            previous = _field_value(base_draft, target)
            old_value = None if _is_blank(previous) else str(previous)

        ordered[target] = CorrectionOut(
            target=target,
            old_value=None if _is_blank(old_value) else str(old_value).strip(),
            new_value=new_value,
            reason=correction.reason,
        )
    return list(ordered.values())


def merge_unresolved(unresolved: list[str] | None) -> list[str]:
    """``unresolved`` **全量替换**为本次结果（基座的不保留）。"""
    return [str(item).strip() for item in (unresolved or []) if str(item).strip()]


# --------------------------------------------------------------------------- #
# 字段级 diff（`C-AGENT@2` 的 B 节）
# --------------------------------------------------------------------------- #


def diff_draft(old: Draft | None, new: Draft) -> list[ChangeOut]:
    """字段级 diff，``source="ai"``，输出顺序固定（9 个标量 → ``extra_tags`` 键）。

    * ``old`` 无值、``new`` 有值 -> ``op="set"``（``old_value=None``）；
    * 双方有值但不同 -> ``op="set"``（``old_value`` 取旧值，类型保留）；
    * 值相同 / ``new`` 无值 -> 不产出（增量解析不做删除）；
    * ``extra_tags`` 新增键 -> ``op="add_tag"``；同键改值 -> ``op="set"``；
    * ``new_value`` 未通过 :func:`is_pure_value` 的条目直接丢弃（记 warning）。
    """
    old_draft = old if old is not None else Draft()
    changes: list[ChangeOut] = []

    for field in SCALAR_FIELDS:
        old_value = getattr(old_draft, field, None)
        new_value = getattr(new, field, None)
        if _is_blank(new_value):
            continue
        label = FIELD_LABELS[field]
        if _is_blank(old_value):
            changes.append(
                ChangeOut(
                    op="set",
                    field=field,
                    old_value=None,
                    new_value=_typed_value(field, new_value),
                    reason=f"增量解析：补充了{label}",
                )
            )
        elif not _same_value(old_value, new_value):
            changes.append(
                ChangeOut(
                    op="set",
                    field=field,
                    old_value=_typed_value(field, old_value),
                    new_value=_typed_value(field, new_value),
                    reason=f"增量解析：修改了{label}",
                )
            )

    old_tags = old_draft.extra_tags or {}
    for key, value in (new.extra_tags or {}).items():
        key_text = str(key)
        if _is_blank(value):
            continue
        field = f"{EXTRA_TAG_PREFIX}{key_text}"
        if key_text not in old_tags:
            changes.append(
                ChangeOut(
                    op="add_tag",
                    field=field,
                    old_value=None,
                    new_value=str(value).strip(),
                    reason=f"增量解析：新增了扩展项「{key_text}」",
                )
            )
        elif not _same_value(old_tags[key_text], value):
            changes.append(
                ChangeOut(
                    op="set",
                    field=field,
                    old_value=str(old_tags[key_text]).strip(),
                    new_value=str(value).strip(),
                    reason=f"增量解析：修改了扩展项「{key_text}」",
                )
            )

    kept: list[ChangeOut] = []
    for change in changes:
        if is_pure_value(change.new_value):
            kept.append(change)
        else:
            logger.warning(
                "丢弃非纯值 change: field=%s new_value=%r（宁缺勿污染）",
                change.field,
                change.new_value,
            )
    return kept


# --------------------------------------------------------------------------- #
# 追溯文案（`C-AGENT@2` 的 C 节，逐字模板）
# --------------------------------------------------------------------------- #


def applied_texts_for(changes: list[ChangeOut] | None) -> list[str]:
    """逐条生成中文追溯文案，**与 ``changes`` 等长且顺序一一对应**。

    模板（``{label}`` / ``{key}`` 为中文名与扩展项键名）：

    * ``ai`` + ``set`` + 无旧值      -> ``AI建议：补充{label}为「{new}」``
    * ``ai`` + ``set`` + 有旧值      -> ``AI建议：将{label}由「{old}」改为「{new}」``
    * ``ai`` + ``add_tag``           -> ``AI建议：新增扩展项「{key}」，内容为「{new}」``
    * ``ai`` + ``remove_tag``        -> ``AI建议：删除扩展项「{key}」``
    * ``user`` + ``set`` + 无旧值    -> ``用户：新建{label}，内容为「{new}」``
    * ``user`` + ``set`` + 有旧值    -> ``用户：将{label}由「{old}」改为「{new}」``
    * ``user`` + ``remove_tag``      -> ``用户：删除扩展项「{key}」（原「{old}」）``
    * ``new`` 为空（防御分支）       -> ``{前缀}：清空{label}（原「{old}」）``
    """
    return [_applied_text(change) for change in (changes or [])]


def _applied_text(change: ChangeOut) -> str:
    prefix = _SOURCE_PREFIX.get(change.source, _SOURCE_PREFIX["ai"])
    label, key = _split_field(change.field)
    new_text = _as_text(change.new_value)
    old_text = _as_text(change.old_value)

    if change.op == "add_tag":
        return f"{prefix}：新增扩展项「{key}」，内容为「{new_text}」"
    if change.op == "remove_tag":
        if change.source == "user":
            return f"用户：删除扩展项「{key}」（原「{old_text}」）"
        return f"AI建议：删除扩展项「{key}」"
    if _is_blank(change.new_value):
        return f"{prefix}：清空{label}（原「{old_text}」）"
    if _is_blank(change.old_value):
        if change.source == "user":
            return f"用户：新建{label}，内容为「{new_text}」"
        return f"AI建议：补充{label}为「{new_text}」"
    if change.source == "user":
        return f"用户：将{label}由「{old_text}」改为「{new_text}」"
    return f"AI建议：将{label}由「{old_text}」改为「{new_text}」"


# --------------------------------------------------------------------------- #
# 审核建议 -> changes（`C-AGENT@2` 的 D 节）
# --------------------------------------------------------------------------- #


def normalize_change_field(field: str | None) -> str:
    """把 ``ambiguity.field`` 归一化为变更字段路径。

    ``extra_tags.`` 开头 -> 原样；标量字段 -> 原样；否则视为扩展项裸键 ->
    ``"extra_tags.<field>"``；空 -> 空串（调用方丢弃）。
    """
    name = (field or "").strip()
    if not name:
        return ""
    if name.startswith(EXTRA_TAG_PREFIX):
        return name
    if name in FIELD_LABELS:
        return name
    return f"{EXTRA_TAG_PREFIX}{name}"


def _field_value(draft: Draft, field_path: str) -> object:
    """取草稿中某字段路径的值（``extra_tags.<key>`` 取该键值，缺失为 ``None``）。"""
    if field_path.startswith(EXTRA_TAG_PREFIX):
        key = field_path[len(EXTRA_TAG_PREFIX) :]
        return (draft.extra_tags or {}).get(key)
    if field_path in FIELD_LABELS:
        return getattr(draft, field_path, None)
    return None


def changes_from_ambiguities(draft: Draft, ambiguities: list[Ambiguity] | None) -> list[ChangeOut]:
    """把 ``ambiguities[].suggestion`` 转成字段级 ``changes``（R13-AC1 / R13-AC4）。

    * ``suggestion`` 先经 :func:`sanitize_value` 净化，再经 :func:`is_pure_value` 判定；
    * 未通过纯值判定的建议**不产出** change（保留 ``ambiguities`` 供人工处理）；
    * ``old_value`` 取 ``draft`` 对应字段值；``reason`` 取 ``ambiguity.question``。
    """
    changes: list[ChangeOut] = []
    for ambiguity in ambiguities or []:
        field_path = normalize_change_field(ambiguity.field)
        if not field_path:
            continue
        suggestion = sanitize_value(ambiguity.suggestion)
        if suggestion is None or not is_pure_value(suggestion):
            logger.warning(
                "审核建议非纯值，不产出 change: field=%s suggestion=%r",
                ambiguity.field,
                ambiguity.suggestion,
            )
            continue
        if field_path.startswith(EXTRA_TAG_PREFIX):
            new_value: object = suggestion
        else:
            new_value = _typed_value(field_path, suggestion)
            if new_value is None:
                continue
        changes.append(
            ChangeOut(
                op="set",
                field=field_path,
                old_value=_field_value(draft, field_path),
                new_value=new_value,
                reason=(ambiguity.question or "").strip(),
                source="ai",
            )
        )
    return changes


def changes_from_polished(draft: Draft, polished: Polished | None) -> list[ChangeOut]:
    """整段润色结果 -> ``changes``（仅 ``details`` / ``notes``，且必须有 ``style_prompt``）。

    决策 D5 的理由：润色结果是**整段文本**，天然带建议语气，不适合直接落字段。
    因此这里额外收紧一档：除 :func:`is_pure_value` 外，还要求不含句末标点
    （``。！？；`` / 换行）——出现句末标点即代表"这是一段叙述"，不产出 change，
    与 D5「``polished`` 不进入 ``changes``」的结论一致；只有极短的纯值式润色
    （如用户要求的单字/短语替换）才会产出。
    """
    if polished is None or not str(draft.style_prompt or "").strip():
        return []

    changes: list[ChangeOut] = []
    for field in ("details", "notes"):
        candidate = sanitize_value(getattr(polished, field, None))
        if candidate is None or not is_pure_value(candidate):
            continue
        if any(marker in candidate for marker in _SENTENCE_END_MARKERS):
            logger.info("润色结果含句末标点，视为整段叙述不产出 change: field=%s", field)
            continue
        old_value = getattr(draft, field, None)
        if _same_value(old_value, candidate):
            continue
        changes.append(
            ChangeOut(
                op="set",
                field=field,
                old_value=old_value if _is_blank(old_value) else str(old_value).strip(),
                new_value=candidate,
                reason="审核润色建议",
                source="ai",
            )
        )
    return changes


__all__ = [
    "SCALAR_FIELDS",
    "FIELD_LABELS",
    "EXTRA_TAG_PREFIX",
    "PURE_VALUE_MAX_LEN",
    "PURE_VALUE_FORBIDDEN",
    "STYLE_PROMPT_SEPARATOR",
    "INTRO_REQUEST_KEYWORDS",
    "join_style_prompt",
    "needs_intro",
    "merge_draft",
    "merge_corrections",
    "merge_unresolved",
    "diff_draft",
    "applied_texts_for",
    "is_pure_value",
    "sanitize_value",
    "sanitize_draft",
    "normalize_change_field",
    "changes_from_ambiguities",
    "changes_from_polished",
]