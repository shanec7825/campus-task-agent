"""确定性 Mock 响应（契约 `C-AGENT@3`，owner = T3）。

实现 plan `2.2.7`（P1，保留）与 `C-AGENT@2` H 节（P2 增量 / 纯值）的 **Mock 规则表**，且：

* 不联网、不读 ``datetime.now()``、不使用随机数——同一
  ``(text, is_final, base_draft, mode)`` 必须恒定（R9-AC3）；
* 所有返回体 ``mock=True``；
* 规则表外的字段一律 ``None`` / 空容器（"未提到的字段填 null，禁止编造"）；
* ``changes`` / ``applied_texts`` 一律由 ``diffing.diff_draft`` +
  ``diffing.applied_texts_for`` 生成，**禁止**手写死字符串（与真实路径同一份代码）。

`C-AGENT@3` B10：``mock_review`` 在 ``diffing.needs_intro(draft)`` 为真且
``draft.details`` 为空时，必须产出一段**完整介绍文案**放进 ``polished.details``
（只是建议内容，不得写进任何 draft 字段）。

规则表（P1 `2.2.7` + P2 增量）：

==============================  ===============================================
输入特征                        输出
==============================  ===============================================
含 ``秋之韵``                   ``title = "秋之韵志愿招募"``
含 ``搬桌椅``                   ``extra_tags["工作内容"] = "搬桌椅"``
含 ``摄影``                     ``extra_tags["工作内容"]`` 追加 ``"、摄影"``
``操场/体育馆/教一/教三/教四``   取**最后出现**者作为 ``location``
``教三`` 在 ``教四`` 之前        ``corrections`` 追加 ``教三 → 教四``
时间正则命中                    ``time = 命中整串``（未含截止语义时）
时间紧邻截止语义词（``截止`` /   ``deadline = 命中整串``（与 ``time`` 互不推定，
``前提交`` / ``之前提交`` /        可同时存在；两个字段各自独立）
``前完成`` / ``之前完成``）
仅命中时段词（无具体时刻）       ``time = 时段词`` + ``unresolved`` 提问（截止同理）
``人数修改为 N 人`` / ``人数改为 N 人`` / ``人数改成 N 个``
                                ``quota = N``（增量下必然产出 quota 的 set change）
``([0-9]+) (...)`` 首个合理数字   ``quota = 该数字``（完整模式兜底）
含 ``措辞严谨``                 ``style_prompt = "措辞严谨一点"``（不进 details）
``奖励 N 积分``                 ``unresolved`` 追加"是否设置完成奖励积分为 N？"
``mode="incremental"``          只回增量字段（**不把增量原话写进 details**），
                                并与 ``base_draft`` 合并后返回
``base.location`` 非空且与片内地点不同、片段含「不对/不是」
                                ``corrections`` 追加 ``old_value=base.location``
                                （跨片更正，B7）
==============================  ===============================================
"""

from __future__ import annotations

import re

from app.agents import diffing
from app.schemas import (
    Ambiguity,
    CorrectionOut,
    Draft,
    ExtractOut,
    Polished,
    ReviewOut,
    SpanOut,
    SubTaskSuggestion,
)

# --------------------------------------------------------------------------- #
# 规则常量（全部为确定性字面量）
# --------------------------------------------------------------------------- #

LOCATION_WORDS: tuple[str, ...] = ("操场", "体育馆", "教一", "教三", "教四")

# 时间：可选日期词 + 可选时段词 + 数字 + "点"
# 说明：规则表的示例是"明天下午两点"，因此中文数字集合在原始
# ``[一二三四五六七八九十]`` 基础上补入"两"，否则示例无法命中。
TIME_RE = re.compile(
    r"(今天|明天|后天|下周三|本周五)?\s*(上午|中午|下午|晚上)?\s*"
    r"([0-9]{1,2}|[一二三四五六七八九十两]{1,3})\s*点"
)
PERIOD_RE = re.compile(r"上午|中午|下午|晚上")
PERIOD_WORDS: frozenset[str] = frozenset({"上午", "中午", "下午", "晚上"})

# 截止语义词：时间前后出现任一，该时间归属 deadline 而不是 time
DEADLINE_MARKERS: tuple[str, ...] = ("截止", "前提交", "之前提交", "前完成", "之前完成")
_DEADLINE_WINDOW_BEFORE = 8
#: 后窗口刻意收窄：避免"三点开始五点前提交"里前一时间的后窗口误含"前提交"
_DEADLINE_WINDOW_AFTER = 6

# 人数：数字 + 可选量词 + 可选"人" + 可选工作内容 + 可选"的"
QUOTA_RE = re.compile(r"([0-9]+)\s*(个|名)?\s*(人)?\s*(搬桌椅|摄影|布置|签到)?\s*的?")

# P2 增量：明确的"人数修改"表达（优先于上面的宽松规则）
QUOTA_MODIFY_RE = re.compile(r"(?:修改为|改成|改为)\s*([0-9]{1,3})\s*(?:人|个)?")

# 奖励积分（不写入 draft，只登记 unresolved）
REWARD_RE = re.compile(r"奖励\s*([0-9]+)\s*积分")

# 风格短语（措辞严谨[一点]）
STYLE_RE = re.compile(r"措辞严谨[一点]{0,2}")
STYLE_PROMPT = "措辞严谨一点"

# 动宾关键词（extra_tags["工作内容"]）
WORK_WORDS: tuple[str, ...] = ("搬桌椅", "摄影")

# 更正原话（"哎不对是教四"），用于 corrections.reason
CORRECTION_QUOTE_RE = re.compile(r"[^，。！？!?]{0,10}不对[^，。！？!?]{0,10}教四[^，。！？!?]{0,20}")

TITLE_WORD = "秋之韵"
TITLE_QIUZHIYUN = "秋之韵志愿招募"
TITLE_PARTY = "校园晚会"

#: 增量模式下建议给出的歧义默认提问时段
DEFAULT_PERIOD = "下午"

#: 纯值化的默认时间建议（P1 的 ``"14:00 或 15:00"`` 含「或」，会被纯值校验拒绝）
DEFAULT_TIME_SUGGESTION = "14:00"


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #


def _mask(text: str, start: int, end: int) -> str:
    """把 ``text[start:end]`` 替换为等长空格，保持后续 ``find`` 的下标不变。"""
    if end <= start:
        return text
    return text[:start] + " " * (end - start) + text[end:]


def _pick_location(text: str) -> tuple[str | None, int]:
    """按词表顺序匹配并取**最后出现**的地点词。

    返回 ``(地点词, 首次出现的下标)``；未命中返回 ``(None, -1)``。
    """
    best_word: str | None = None
    best_index = -1
    for word in LOCATION_WORDS:
        idx = text.rfind(word)
        if idx < 0:
            continue
        if idx > best_index:
            best_word = word
            best_index = idx
    if best_word is None:
        return None, -1
    return best_word, text.find(best_word)


def _has_deadline_marker(text: str, start: int, end: int) -> bool:
    """时间片段紧邻截止语义词（前 8 字 / 后 6 字窗口）时判定为截止时间。"""
    before = text[max(0, start - _DEADLINE_WINDOW_BEFORE) : start]
    after = text[end : end + _DEADLINE_WINDOW_AFTER]
    return any(marker in before or marker in after for marker in DEADLINE_MARKERS)


def _parse_times(text: str) -> tuple[str | None, str | None, list[re.Match[str]], list[str]]:
    """解析时间，并区分**开始时间**与**截止时间**。

    返回 ``(time 值, deadline 值, 命中的全部时间 match, 缺失提问)``。

    * 每个时间片段按 :func:`_has_deadline_marker` 归属 ``deadline`` 或 ``time``；
    * 两个字段各自独立：只出现一方时另一方为 ``None``，绝不互相复制或推定；
    * 完全没提到任何时间时返回 ``(None, None, [], [])``（交给审核助手）；
    * 只命中时段词（无具体时刻）时保留该时段词，并登记一条面向用户的提问。

    注意：规则表里的时间正则允许"日期/时段"全缺省，因此"多带一点水""好一点"
    中的"一点"也会命中；这种无日期、无时段前缀的纯"一点"不是时间，直接跳过
    （风格短语"措辞严谨一点"在调用前已被 mask，不会走到这里）。
    """
    matches: list[re.Match[str]] = []
    time_matches: list[re.Match[str]] = []
    deadline_matches: list[re.Match[str]] = []
    for match in TIME_RE.finditer(text):
        prefix = (match.group(1) or "") + (match.group(2) or "")
        whole = match.group(0).strip()
        if not prefix and whole == "一点":
            continue
        matches.append(match)
        owner = deadline_matches if _has_deadline_marker(text, match.start(), match.end()) else time_matches
        owner.append(match)

    questions: list[str] = []
    time_value = time_matches[0].group(0).strip() if time_matches else None
    deadline_value = deadline_matches[0].group(0).strip() if deadline_matches else None

    if time_value is None and deadline_value is None:
        period_match = PERIOD_RE.search(text)
        if period_match is not None:
            period = period_match.group(0)
            if _has_deadline_marker(text, period_match.start(), period_match.end()):
                deadline_value = period
                questions.append(f"{period}具体几点截止？")
            else:
                time_value = period
                questions.append(f"{period}具体几点开始？")

    return time_value, deadline_value, matches, questions


def _parse_quota(
    text: str, time_matches: list[re.Match[str]], prefer_modify: bool
) -> tuple[int | None, str | None, int]:
    """解析人数。

    * ``prefer_modify``（增量模式或文本里出现明确"改为 N 人"）优先取
      ``QUOTA_MODIFY_RE`` 命中的数字；
    * 否则取第一个"合理数字"（1..999），并先屏蔽所有时间串（开始/截止）与
      "奖励 N 积分"片段，避免把时刻或奖励积分数误判成人数（规则表：奖励积分
      不得写入 draft）。
    """
    modify_match = QUOTA_MODIFY_RE.search(text)
    if modify_match is not None and prefer_modify:
        value = int(modify_match.group(1))
        if 1 <= value <= 999:
            return value, modify_match.group(0).strip(), modify_match.start()
    elif modify_match is not None:
        # 完整模式下"改为 N 人"同样是人数语义，优先于宽松正则
        value = int(modify_match.group(1))
        if 1 <= value <= 999:
            return value, modify_match.group(0).strip(), modify_match.start()

    masked = text
    for time_match in time_matches:
        masked = _mask(masked, time_match.start(), time_match.end())
    for reward in REWARD_RE.finditer(text):
        masked = _mask(masked, reward.start(), reward.end())
    if modify_match is not None:
        masked = _mask(masked, modify_match.start(), modify_match.end())

    for match in QUOTA_RE.finditer(masked):
        raw = match.group(1)
        value = int(raw)
        if 1 <= value <= 999:
            return value, text[match.start() : match.end()].strip(), match.start()
    return None, None, -1


def _style_phrase(text: str) -> tuple[str | None, re.Match[str] | None]:
    """识别风格指令短语（只处理契约要求的"措辞严谨"）。"""
    match = STYLE_RE.search(text)
    if not match:
        return None, None
    return match.group(0), match


def _clean_details(text: str, style_match: re.Match[str] | None) -> str | None:
    """把原文去掉风格指令后作为 details（风格短语绝不允许混入）。"""
    cleaned = text
    if style_match is not None:
        cleaned = _mask(cleaned, style_match.start(), style_match.end())
    cleaned = re.sub(r"[，,]\s*[，,]+", "，", cleaned)
    cleaned = cleaned.strip(" \t\r\n，,。；;、:：")
    return cleaned or None


def _correction_reason(text: str) -> str:
    match = CORRECTION_QUOTE_RE.search(text)
    quote = match.group(0).strip(" ，,。；;、") if match else ""
    return f"用户的更正原话：{quote or '哎不对是教四'}"


# --------------------------------------------------------------------------- #
# Mock 提炼助手
# --------------------------------------------------------------------------- #


def mock_extract(
    text: str,
    is_final: bool = True,
    base_draft: Draft | None = None,
    mode: str = "full",
) -> ExtractOut:
    """确定性提炼（规则表逐条实现）。

    ``mode="incremental"`` 时：只解析 ``text`` 中的**增量字段**（不把增量原话写入
    ``details``），再与 ``base_draft`` 合并后返回完整草稿；``changes`` /
    ``applied_texts`` 由 ``diffing`` 生成（长度相等、顺序一致）。
    """
    incremental = mode == "incremental"
    source = text or ""
    base = diffing.sanitize_draft(base_draft) if (incremental and base_draft is not None) else None

    # ---- 1) title --------------------------------------------------------
    title: str | None = None
    if TITLE_WORD in source:
        title = TITLE_QIUZHIYUN
    elif "晚会" in source:
        title = TITLE_PARTY

    # ---- 2) 风格剥离（先做：确保"措辞严谨一点"不会被时间正则当成"一点"）---
    style_phrase, style_match = _style_phrase(source)
    style_prompt = STYLE_PROMPT if style_phrase else None
    time_search_text = (
        _mask(source, style_match.start(), style_match.end()) if style_match is not None else source
    )

    # ---- 3) 时间：开始时间与截止时间独立解析（互不推定）--------------------
    time_value, deadline_value, time_matches, time_questions = _parse_times(time_search_text)

    # ---- 4) 地点 + 更正 ---------------------------------------------------
    location, location_start = _pick_location(source)
    corrections: list[CorrectionOut] = []
    jiaosan_at = source.rfind("教三")
    jiaosi_at = source.rfind("教四")
    if jiaosan_at >= 0 and jiaosi_at >= 0 and jiaosan_at < jiaosi_at:
        corrections.append(
            CorrectionOut(
                target="location",
                old_value="教三",
                new_value="教四",
                reason=_correction_reason(source),
            )
        )

    # 跨片更正（B7）：base 已有地点与片内地点不同，且片内含否定/更正表达
    base_location = (base.location or "").strip() if base is not None else ""
    if (
        location
        and base_location
        and location != base_location
        and re.search(r"不对|不是", source)
    ):
        corrections.append(
            CorrectionOut(
                target="location",
                old_value=base_location,
                new_value=location,
                reason=_correction_reason(source),
            )
        )

    # ---- 5) 人数 ----------------------------------------------------------
    quota, quota_text, quota_start = _parse_quota(source, time_matches, prefer_modify=incremental)

    # ---- 6) extra_tags ----------------------------------------------------
    extra_tags: dict[str, str] = {}
    work_items = [word for word in WORK_WORDS if word in source]
    if work_items:
        extra_tags["工作内容"] = "、".join(work_items)

    # ---- 7) details / notes（增量模式不把增量原话当作详情）----------------
    if incremental:
        details = None
    else:
        details = _clean_details(source, style_match) if is_final else None

    delta = Draft(
        title=title,
        time=time_value,
        deadline=deadline_value,
        location=location,
        details=details,
        quota=quota,
        volunteer_hours=None,
        notes=None,
        requirements=None,
        extra_tags=extra_tags,
        style_prompt=style_prompt,
    )
    delta = diffing.sanitize_draft(delta)

    # ---- 8) unresolved ----------------------------------------------------
    unresolved: list[str] = list(time_questions)
    for reward in REWARD_RE.finditer(source):
        unresolved.append(f"是否设置完成奖励积分为 {int(reward.group(1))}？")

    # ---- 9) spans（按原文首次出现位置排序）--------------------------------
    raw_spans: list[tuple[int, SpanOut]] = []

    def _add(index: int, span_text: str, field: str | None) -> None:
        if index < 0 or not span_text:
            return
        raw_spans.append((index, SpanOut(text=span_text, field=field)))

    if delta.title is not None:
        title_word = TITLE_WORD if TITLE_WORD in source else "晚会"
        _add(source.find(title_word), title_word, "title")
    if delta.time is not None:
        start_match = next(
            (m for m in time_matches if not _has_deadline_marker(source, m.start(), m.end())),
            None,
        )
        if start_match is not None:
            _add(start_match.start(), source[start_match.start() : start_match.end()], "time")
        else:
            _add(source.find(delta.time), delta.time, "time")
    if delta.deadline is not None:
        deadline_match = next(
            (m for m in time_matches if _has_deadline_marker(source, m.start(), m.end())),
            None,
        )
        if deadline_match is not None:
            _add(
                deadline_match.start(),
                source[deadline_match.start() : deadline_match.end()],
                "deadline",
            )
        else:
            _add(source.find(delta.deadline), delta.deadline, "deadline")
    if delta.location is not None:
        _add(location_start, delta.location, "location")
    if quota_text and delta.quota is not None:
        _add(quota_start, quota_text, "quota")
    for word in work_items:
        _add(source.find(word), word, "工作内容")
    for reward in REWARD_RE.finditer(source):
        _add(reward.start(), source[reward.start() : reward.end()], None)
    if style_match is not None:
        _add(style_match.start(), source[style_match.start() : style_match.end()], None)

    spans = [span for _, span in sorted(raw_spans, key=lambda item: item[0])]

    # ---- 10) 合并 + changes/applied_texts（与真实路径同一份实现）----------
    merged = diffing.sanitize_draft(diffing.merge_draft(base, delta))
    changes = diffing.diff_draft(base, merged)
    applied_texts = diffing.applied_texts_for(changes)

    return ExtractOut(
        draft=merged,
        spans=spans,
        unresolved=diffing.merge_unresolved(unresolved),
        style_prompt=merged.style_prompt,
        corrections=diffing.merge_corrections(base, corrections),
        mock=True,
        changes=changes,
        applied_texts=applied_texts,
    )


# --------------------------------------------------------------------------- #
# Mock 审核助手
# --------------------------------------------------------------------------- #

_PARTY_SUB_TASKS: tuple[SubTaskSuggestion, ...] = (
    SubTaskSuggestion(
        title="布置场地",
        description="在活动开始前完成场地布置与物料摆放。",
        sop_guide="1. 提前 1 小时到场，确认场地已开放；\n"
        "2. 按图纸摆放桌椅、张贴指引牌并接通电源；\n"
        "3. 与负责人逐项核对物料清单后签字确认。",
        quota=3,
        depends_on=None,
    ),
    SubTaskSuggestion(
        title="活动执行",
        description="活动进行中维持秩序、引导参与者并处理突发情况。",
        sop_guide="1. 活动开始前 15 分钟到达指定岗位；\n"
        "2. 按分工引导签到、发放物资并记录到场人数；\n"
        "3. 遇到设备故障立即联系负责人，不擅自处理。",
        quota=4,
        depends_on=0,
    ),
    SubTaskSuggestion(
        title="收尾清场",
        description="活动结束后清理场地、归还物资并汇总现场情况。",
        sop_guide="1. 活动结束后按区域回收桌椅与剩余物料；\n"
        "2. 清扫垃圾并恢复场地原状，拍照留档；\n"
        "3. 向负责人汇报物资损耗与遗留问题。",
        quota=3,
        depends_on=1,
    ),
)


def _intro_text(draft: Draft) -> str:
    """生成一段完整的中文任务介绍（B10；确定性，不读时间、无随机）。

    用作 ``polished.details``：这是**建议内容**，前端只展示、人工采纳，
    绝不写回 ``draft`` 字段。
    """
    title = (draft.title or "").strip()
    work = (draft.extra_tags or {}).get("工作内容")
    details: list[str] = []
    if draft.time:
        details.append(f"活动时间为{draft.time}")
    if draft.location:
        details.append(f"地点在{draft.location}")
    if draft.quota:
        details.append(f"计划招募{draft.quota}名志愿者")
    if work:
        details.append(f"主要负责{work}")

    if not title and not details:
        return (
            "这是一项校园志愿任务，具体时间、地点与招募人数仍在确认中，"
            "欢迎有意向的同学报名参与，后续安排请留意任务更新。"
        )

    subject = title or "本项校园志愿任务"
    if details:
        return (
            f"{subject}现面向全校招募志愿者，{'，'.join(details)}。"
            "报名后请按通知准时到场，服从现场负责人安排，感谢大家的支持与参与。"
        )
    return (
        f"{subject}现面向全校招募志愿者。报名后请按通知准时到场，"
        "服从现场负责人安排，感谢大家的支持与参与。"
    )


def mock_review(draft: Draft) -> ReviewOut:
    """确定性审核（规则表逐条实现，``suggestion`` 为纯值）。"""
    # ---- 1) 歧义：时间无具体时刻（suggestion 必须是可直接落值的纯数据值）----
    ambiguities: list[Ambiguity] = []
    if not draft.time or "点" not in draft.time:
        period = draft.time if draft.time in PERIOD_WORDS else DEFAULT_PERIOD
        ambiguities.append(
            Ambiguity(
                field="time",
                question=f"{period}具体几点开始？",
                suggestion=DEFAULT_TIME_SUGGESTION,
            )
        )

    # ---- 2) 润色 / 介绍文案（B10：details 为空且需要介绍时必须给完整文案）----
    polished: Polished | None = None
    if diffing.needs_intro(draft):
        # needs_intro 为真 ⇒ details 必定为空：给出完整介绍文案（建议内容，不落字段）
        polished = Polished(details=_intro_text(draft), notes=draft.notes or "")
    elif (draft.style_prompt or "").strip():
        # 有 details 且有 style_prompt：按 P2 规则做整段润色
        core = (draft.details or "").strip()
        text = "（已按风格要求润色）" + core
        if not text.endswith("。"):
            text += "。"
        polished = Polished(details=text, notes=draft.notes or "")

    # ---- 3) 拆解建议：title 含"晚会"或"秋之韵"时固定 3 条 -----------------
    title = draft.title or ""
    suggested = list(_PARTY_SUB_TASKS) if ("晚会" in title or TITLE_WORD in title) else []

    # ---- 4) changes：ambiguities（纯值建议）+ polished（整段叙述通常不产出）--
    changes = diffing.changes_from_ambiguities(draft, ambiguities) + diffing.changes_from_polished(
        draft, polished
    )

    return ReviewOut(
        ambiguities=ambiguities,
        polished=polished,
        suggested_sub_tasks=suggested,
        mock=True,
        changes=changes,
    )


__all__ = [
    "mock_extract",
    "mock_review",
    "LOCATION_WORDS",
    "TIME_RE",
    "DEADLINE_MARKERS",
    "QUOTA_RE",
    "QUOTA_MODIFY_RE",
    "REWARD_RE",
    "STYLE_RE",
    "DEFAULT_TIME_SUGGESTION",
]