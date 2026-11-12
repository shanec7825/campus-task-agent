#!/usr/bin/env python
"""T10-③ Agent mock 规则逐条断言 + 增量知识库检索（契约 `C-AGENT@1` / `C-KB@1`）。

覆盖（plan T10 用例矩阵 ③，规则表见 plan `2.2.7`）：
1. ``/api/agent/extract``、``/api/agent/review``、``/api/agent/stream/parse`` 三接口
   在 mock 模式下均返回 ``mock=true``；
2. mock 提炼规则逐条：秋之韵 / 搬桌椅 / 摄影追加 / 教三→教四 更正 / 明天下午两点 /
   仅"下午"→unresolved / 5 个人 / 措辞严谨剥离 / 奖励 20 积分 → unresolved；
3. ``spans`` 的字段归属与原文顺序、``style_prompt`` 顶层与 ``draft`` 一致；
4. ``/stream/parse`` 服务端草稿合并：非空字段覆盖、``extra_tags`` 键级合并、
   ``is_final=true`` 不清空草稿、``parse_sessions`` 累计原文落库；
5. ``/api/kb/similar``：``threshold=0.6``、top ≤ 3、相似度降序、默认只返回 ≥0.6；
   ``q`` 为空 / 超长 → 4001，未登录 → 401/4010。

两种 KB 模式（用于记录"过滤 / 不过滤"的实测差异）：
- 默认（``KB_MIN_SIMILARITY`` 未设置 = 0.6）：断言每条 ``similarity >= 0.6``；
- ``--kb-mode=unfiltered``（后端以 ``KB_MIN_SIMILARITY=0`` 启动）：只断言 top≤3 与降序，
  打印可见条数供对比，**不作为失败判据**。

运行前提：``T10_BASE_URL``、``T10_DB_PATH``、``T10_BACKEND_DIR``（由 ``run_all.sh`` 导出）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.getenv("T10_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
DB_PATH = (os.getenv("T10_DB_PATH") or "").strip()

# 造 KB 数据用：description 留空（避免长描述稀释 jaccard 导致相似度掉到阈值以下）
KB_TITLES = [
    "秋之韵志愿招募",
    "秋之韵志愿招募活动",
    "秋之韵志愿招募工作人员",
    "秋之韵志愿者招募",
    "秋之韵晚会志愿招募",
    "校内志愿招募",
]
KB_QUERY = "秋之韵志愿招募"
KB_WEAK_QUERY = "秋之韵"

#: spans[].field 白名单（plan 2.2.7：非法值一律视为无法归属）
SPAN_FIELDS = {
    "title",
    "time",
    "location",
    "details",
    "quota",
    "volunteer_hours",
    "notes",
    "requirements",
    "extra_tags",
}

_passed = 0


def expect(condition: bool, message: str) -> bool:
    """断言包装：通过打印 ``PASS`` 并计数，失败打印 ``FAIL`` 后立即退出 1。"""
    global _passed
    if condition:
        _passed += 1
        print(f"PASS: {message}")
        return True
    print(f"FAIL: {message}")
    raise SystemExit(1)


# --------------------------------------------------------------------------- #
# HTTP 工具（仅标准库）
# --------------------------------------------------------------------------- #
def http_json(
    method: str,
    path: str,
    body: object | None = None,
    token: str | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE_URL + path, data=payload, method=method)
    if payload is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        request.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"code": None, "msg": raw[:200], "data": None}
    except urllib.error.URLError as exc:
        print(f"FAIL: 无法连接后端 {BASE_URL}（{exc}）；请先执行 bash tests/backend/run_all.sh")
        raise SystemExit(1)


def api_ok(method: str, path: str, body: object | None = None, token: str | None = None, label: str = "") -> dict:
    status, payload = http_json(method, path, body, token)
    code = payload.get("code")
    expect(
        status == 200 and code == 0,
        f"{label}：期望 HTTP 200 + code=0，实际 HTTP {status} + code={code}（msg={payload.get('msg')}）",
    )
    data = payload.get("data")
    expect(isinstance(data, dict), f"{label}：data 为对象（实际 {type(data).__name__}）")
    return data


def api_err(
    method: str,
    path: str,
    code: int,
    body: object | None = None,
    token: str | None = None,
    expected_status: int = 200,
    label: str = "",
) -> dict:
    status, payload = http_json(method, path, body, token)
    expect(
        payload.get("code") == code,
        f"{label}：期望 code={code}，实际 HTTP {status} + code={payload.get('code')}（msg={payload.get('msg')}）",
    )
    expect(status == expected_status, f"{label}：期望 HTTP {expected_status}，实际 HTTP {status}")
    return payload


def login(username: str) -> str:
    data = api_ok("POST", "/api/auth/login", {"username": username}, label=f"登录 {username}")
    token = data.get("token")
    expect(isinstance(token, str) and bool(token), f"{username} 返回非空 token")
    return token


def extract(token: str, text: str) -> dict:
    data = api_ok("POST", "/api/agent/extract", {"text": text}, token=token, label=f"extract: {text[:12]}…")
    expect(isinstance(data.get("draft"), dict), f"extract「{text[:12]}…」返回 draft 对象")
    expect(isinstance(data.get("spans"), list), "extract 返回 spans 数组")
    expect(isinstance(data.get("unresolved"), list), "extract 返回 unresolved 数组")
    # `C-AGENT@2`：三接口新增 changes；extract 另返回 applied_texts，两者等长且顺序一致
    expect(isinstance(data.get("changes"), list), "extract 返回 changes 数组")
    expect(isinstance(data.get("applied_texts"), list), "extract 返回 applied_texts 数组")
    expect(
        len(data["changes"]) == len(data["applied_texts"]),
        f"extract changes 与 applied_texts 等长（{len(data['changes'])} vs {len(data['applied_texts'])}）",
    )
    expect(data.get("mock") is True, f"extract 在 mock 模式返回 mock=true（实际 {data.get('mock')}）")
    draft = data["draft"]
    expect(
        data.get("style_prompt") == draft.get("style_prompt"),
        f"顶层 style_prompt 与 draft.style_prompt 一致（{data.get('style_prompt')!r} vs {draft.get('style_prompt')!r}）",
    )
    return data


def stream_parse(token: str, session_id: str, chunk: str, is_final: bool) -> dict:
    data = api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": session_id, "chunk": chunk, "is_final": is_final},
        token=token,
        label=f"stream/parse chunk={chunk[:10]}… is_final={is_final}",
    )
    expect(isinstance(data.get("draft"), dict), "stream/parse 返回全量 draft")
    expect(data.get("mock") is True, f"stream/parse 返回 mock=true（实际 {data.get('mock')}）")
    expect(isinstance(data.get("changes"), list), "stream/parse 返回 changes 数组（本片 diff）")
    return data


# --------------------------------------------------------------------------- #
# 规则表逐条断言
# --------------------------------------------------------------------------- #
def assert_extract_rules(token: str) -> None:
    """逐条断言 plan `2.2.7` 的 mock 规则表。"""
    main_text = "秋之韵志愿招募，明天下午两点在教三集合，需要 5 个人搬桌椅，措辞严谨一点，完成奖励 20 积分"
    result = extract(token, main_text)
    draft = result["draft"]

    expect(draft.get("title") == "秋之韵志愿招募", f"规则「含秋之韵」→ title=秋之韵志愿招募（实际 {draft.get('title')}）")
    applied = result.get("applied_texts") or []
    expect(
        applied and applied[0] == "AI建议：补充标题为「秋之韵志愿招募」",
        f"applied_texts[0] 逐字模板（实际 {applied[:2]}）",
    )
    quota_changes = [c for c in result.get("changes") or [] if c.get("field") == "quota"]
    expect(
        len(quota_changes) == 1 and quota_changes[0].get("old_value") is None and quota_changes[0].get("new_value") == 5,
        f"changes 含 quota 新增（实际 {quota_changes}）",
    )
    expect(draft.get("time") == "明天下午两点", f"规则「明天下午两点」→ time 命中整串（实际 {draft.get('time')!r}）")
    expect(draft.get("location") == "教三", f"规则「地点词」→ location=教三（实际 {draft.get('location')!r}）")
    expect(draft.get("quota") == 5, f"规则「5 个人」→ quota=5（实际 {draft.get('quota')!r}）")
    expect(
        draft.get("extra_tags") == {"工作内容": "搬桌椅"},
        f"规则「含搬桌椅」→ extra_tags[工作内容]=搬桌椅（实际 {draft.get('extra_tags')!r}）",
    )
    expect(draft.get("style_prompt") == "措辞严谨一点", f"规则「措辞严谨」→ style_prompt（实际 {draft.get('style_prompt')!r}）")
    expect(
        "措辞严谨" not in (draft.get("details") or ""),
        f"风格短语不得混入 details（实际 details={draft.get('details')!r}）",
    )
    expect(
        "是否设置完成奖励积分为 20？" in (result.get("unresolved") or []),
        f"规则「奖励 20 积分」→ unresolved 追加提问（实际 {result.get('unresolved')!r}）",
    )
    expect("credit_reward" not in draft, "奖励积分不写入 draft（属于前端表单字段）")
    expect(result.get("corrections") == [], f"无更正时 corrections 为空数组（实际 {result.get('corrections')!r}）")

    # spans：字段归属 + 原文顺序
    spans = result.get("spans") or []
    dynamic_fields = set((draft.get("extra_tags") or {}).keys())  # 规则表允许 extras 的键名作 field
    allowed_fields = SPAN_FIELDS | dynamic_fields
    expect(
        all(span.get("field") in allowed_fields or span.get("field") is None for span in spans),
        f"spans.field 均在白名单 / extras 键名内或为 null（实际 {[s.get('field') for s in spans]}）",
    )
    expected_fields = {"title", "time", "location", "quota", "工作内容"}
    actual_fields = {span.get("field") for span in spans}
    expect(expected_fields <= actual_fields, f"spans 覆盖 title/time/location/quota/工作内容（实际 {sorted(str(f) for f in actual_fields)}）")
    positions = [main_text.find(span["text"]) for span in spans]
    expect(all(p >= 0 for p in positions), "spans 文本均可在原文定位")
    expect(positions == sorted(positions), f"spans 按原文首次出现位置排序（实际下标 {positions}）")

    # 确定性（R9-AC3）
    repeat = extract(token, main_text)
    expect(repeat == result, "同一输入两次 extract 结果完全一致（确定性）")

    # 摄影追加
    photo = extract(token, "秋之韵招募，需要摄影和搬桌椅")["draft"]
    expect(photo.get("extra_tags") == {"工作内容": "搬桌椅、摄影"}, f"规则「含摄影」→ 工作内容追加摄影（实际 {photo.get('extra_tags')!r}）")
    photo_only = extract(token, "秋之韵招募，需要摄影")["draft"]
    expect(photo_only.get("extra_tags") == {"工作内容": "摄影"}, f"「摄影」单独出现时不重复追加（实际 {photo_only.get('extra_tags')!r}）")

    # 教三 → 教四 更正
    fix = extract(token, "在教三集合，哎不对是教四")
    expect(fix["draft"].get("location") == "教四", f"规则「教三→教四」→ location 取最后出现（实际 {fix['draft'].get('location')!r}）")
    corrections = fix.get("corrections") or []
    expect(len(corrections) == 1, f"更正登记 1 条（实际 {len(corrections)}）")
    expect(
        corrections[0].get("target") == "location"
        and corrections[0].get("old_value") == "教三"
        and corrections[0].get("new_value") == "教四",
        f"更正结构为 location 教三→教四（实际 {corrections[0] if corrections else None}）",
    )
    expect("更正原话" in (corrections[0].get("reason") or ""), f"更正 reason 含用户原话（实际 {corrections[0].get('reason')}）")

    # 仅时段 → unresolved
    period = extract(token, "下午在操场集合")
    expect(period["draft"].get("time") == "下午", f"规则「仅有下午」→ time=下午（实际 {period['draft'].get('time')!r}）")
    expect(
        "下午具体几点开始？" in (period.get("unresolved") or []),
        f"规则「仅时段」→ unresolved 含具体几点（实际 {period.get('unresolved')!r}）",
    )
    expect(period["draft"].get("location") == "操场", f"地点「操场」命中（实际 {period['draft'].get('location')!r}）")

    # 时间完整命中时不再抛出 unresolved
    plain_time = extract(token, "明天下午两点")
    expect(plain_time["draft"].get("time") == "明天下午两点", "规则「明天下午两点」单独成句命中")
    expect(plain_time.get("unresolved") == [], f"命中具体时刻时不产生 unresolved（实际 {plain_time.get('unresolved')!r}）")

    # 未提及字段为 null（禁止编造）
    expect(
        plain_time["draft"].get("title") is None and plain_time["draft"].get("quota") is None,
        "未提及的 title/quota 保持 null（禁止编造）",
    )

    # 措辞严谨剥离（details 不含短语，style_prompt 有值）
    style_only = extract(token, "秋之韵招募，措辞严谨一点")
    expect(style_only["draft"].get("style_prompt") == "措辞严谨一点", "风格指令单独命中")
    expect("措辞严谨" not in (style_only["draft"].get("details") or ""), "风格指令从 details 中剥离")


def assert_stream_merge(token: str) -> None:
    """断言 `/stream/parse` 的服务端草稿合并规则（plan `2.2.7` 第 4 步）。"""
    session_id = "t10-stream-merge-session"

    step1 = stream_parse(token, session_id, "秋之韵志愿招募，", False)
    expect(step1["draft"].get("title") == "秋之韵志愿招募", "step1：title 被写入")
    expect(step1["draft"].get("details") is None, "step1：非最终片不写 details（不猜测未完成内容）")

    step2 = stream_parse(token, session_id, "明天下午两点在教三集合，", False)
    expect(step2["draft"].get("title") == "秋之韵志愿招募", "step2：前一片已确定的 title 未被空值覆盖")
    expect(step2["draft"].get("time") == "明天下午两点", f"step2：time 合并（实际 {step2['draft'].get('time')!r}）")
    expect(step2["draft"].get("location") == "教三", f"step2：location 合并（实际 {step2['draft'].get('location')!r}）")

    step3 = stream_parse(token, session_id, "需要 5 个人搬桌椅，措辞严谨一点", True)
    merged = step3["draft"]
    expect(step3["draft"].get("quota") == 5, f"step3：quota 合并（实际 {merged.get('quota')!r}）")
    expect(merged.get("extra_tags", {}).get("工作内容") == "搬桌椅", f"step3：extra_tags 键级合并（实际 {merged.get('extra_tags')!r}）")
    expect(merged.get("style_prompt") == "措辞严谨一点", f"step3：style_prompt 合并（实际 {merged.get('style_prompt')!r}）")
    expect(merged.get("title") == "秋之韵志愿招募", "step3（is_final=true）：草稿未被清空")
    expect(merged.get("time") == "明天下午两点" and merged.get("location") == "教三", "step3：此前字段全部保留")
    expect(isinstance(step3.get("spans"), list) and step3["spans"], "step3：返回本片 spans（非 diff 全量草稿）")

    # parse_sessions 落库（累计原文 + draft JSON）
    if DB_PATH and os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                "SELECT accumulated_text, draft FROM parse_sessions WHERE session_id=?", (session_id,)
            ).fetchone()
        finally:
            conn.close()
        expect(row is not None, "parse_sessions 写入会话记录")
        expect(
            row[0] == "秋之韵志愿招募，明天下午两点在教三集合，需要 5 个人搬桌椅，措辞严谨一点",
            f"parse_sessions.accumulated_text 为累计原文（实际 {row[0]!r}）",
        )
        expect(isinstance(json.loads(row[1]), dict), "parse_sessions.draft 以 JSON 文本落库并可解析为 dict")


def assert_review(token: str) -> None:
    """断言 `/review` 的 mock 输出（润色 / 歧义 / 拆解）。"""
    with_style = api_ok(
        "POST",
        "/api/agent/review",
        {
            "draft": {
                "title": "秋之韵志愿招募",
                "time": "下午",
                "details": "招募志愿者",
                "style_prompt": "措辞严谨一点",
            }
        },
        token=token,
        label="review（含 style_prompt）",
    )
    expect(with_style.get("mock") is True, f"review 返回 mock=true（实际 {with_style.get('mock')}）")
    polished = with_style.get("polished")
    expect(isinstance(polished, dict), "有 style_prompt 时 polished 非 null")
    expect(polished.get("details", "").startswith("（已按风格要求润色）"), f"polished.details 带润色前缀（实际 {polished.get('details')!r}）")
    expect(isinstance(polished.get("notes"), str), "polished.notes 为字符串（缺项补空串）")

    ambiguities = with_style.get("ambiguities") or []
    expect(len(ambiguities) == 1, f"仅「下午」时产生 1 条歧义（实际 {len(ambiguities)}）")
    expect(
        ambiguities[0].get("field") == "time" and "几点" in (ambiguities[0].get("question") or ""),
        f"歧义字段为 time 且问题含「几点」（实际 {ambiguities[0] if ambiguities else None}）",
    )
    # `C-AGENT@2` D 节：suggestion 收紧为纯值（P1 的 "14:00 或 15:00" 已作废）
    expect(
        ambiguities[0].get("suggestion") == "14:00",
        f"ambiguities[0].suggestion 为纯值 14:00（实际 {ambiguities[0].get('suggestion')!r}）",
    )
    review_changes = with_style.get("changes")
    expect(isinstance(review_changes, list), "review 返回 changes 数组")
    expect(
        any(c.get("field") == "time" and c.get("new_value") == "14:00" for c in review_changes),
        f"review changes 含 time→14:00（实际 {review_changes}）",
    )
    expect(
        not any(c.get("field") in ("details", "notes") for c in review_changes),
        f"polished 整段文本不进入 changes（实际 {[c.get('field') for c in review_changes]}）",
    )

    suggestions = with_style.get("suggested_sub_tasks") or []
    expect(len(suggestions) == 3, f"秋之韵任务固定 3 条拆解建议（实际 {len(suggestions)}）")
    expect([s.get("depends_on") for s in suggestions] == [None, 0, 1], f"拆解依赖索引 null,0,1（实际 {[s.get('depends_on') for s in suggestions]}）")
    expect(
        all(len([line for line in (s.get("sop_guide") or "").splitlines() if line.strip()]) == 3 for s in suggestions),
        "每条拆解建议 sop_guide 为 3 步",
    )

    no_style = api_ok(
        "POST",
        "/api/agent/review",
        {"draft": {"title": "秋之韵志愿招募", "time": "明天下午两点", "details": "招募志愿者"}},
        token=token,
        label="review（无 style_prompt）",
    )
    expect(no_style.get("polished") is None, f"无 style_prompt 时 polished 为 null（实际 {no_style.get('polished')!r}）")
    expect(no_style.get("ambiguities") == [], f"时间含「点」时不产生歧义（实际 {no_style.get('ambiguities')!r}）")

    other_title = api_ok(
        "POST",
        "/api/agent/review",
        {"draft": {"title": "图书馆整理", "time": "明天下午两点"}},
        token=token,
        label="review（非晚会标题）",
    )
    expect(other_title.get("suggested_sub_tasks") == [], "标题不含晚会/秋之韵时无拆解建议")

    # ------------------------------------------------------------------ #
    # B11 拆解收紧（`C-AGENT@3` G / R18-AC8）
    # ------------------------------------------------------------------ #
    simple = api_ok(
        "POST",
        "/api/agent/review",
        {
            "draft": {
                "title": "明天下午搬桌椅",
                "time": "明天下午两点",
                "location": "操场",
                "quota": 3,
            }
        },
        token=token,
        label="review（简单单环节任务）",
    )
    expect(
        simple.get("suggested_sub_tasks") == [],
        f"简单任务（明天下午搬桌椅）拆解为空数组（实际 {simple.get('suggested_sub_tasks')!r}）",
    )
    expect(simple.get("polished") is None, "简单任务无 style/details/请求词时 polished=null")

    party = api_ok(
        "POST",
        "/api/agent/review",
        {"draft": {"title": "办一场校园晚会", "time": "下周三下午三点", "location": "操场"}},
        token=token,
        label="review（晚会类任务）",
    )
    party_subs = party.get("suggested_sub_tasks") or []
    expect(2 <= len(party_subs) <= 6, f"晚会类任务给 2~6 条拆解建议（实际 {len(party_subs)}）")
    expect(
        [item.get("depends_on") for item in party_subs][:3] == [None, 0, 1],
        f"晚会类拆解依赖串行（实际 {[item.get('depends_on') for item in party_subs]}）",
    )

    # B10 介绍建议：details 空 + style ⇒ polished.details 为完整介绍，仍不写字段
    intro = api_ok(
        "POST",
        "/api/agent/review",
        {
            "draft": {
                "title": "秋之韵志愿招募",
                "time": "明天下午两点",
                "location": "操场",
                "quota": 3,
                "style_prompt": "温柔一点",
            }
        },
        token=token,
        label="review（details 空 + style → 介绍建议）",
    )
    intro_polished = intro.get("polished") or {}
    intro_details = (intro_polished.get("details") or "").strip()
    expect(len(intro_details) >= 20, f"polished.details 为完整介绍文案（实际 {intro_details!r}）")
    expect(
        not any(c.get("field") in ("details", "notes") for c in intro.get("changes") or []),
        f"介绍文案不进入 changes（实际 {[c.get('field') for c in intro.get('changes') or []]}）",
    )

    api_err("POST", "/api/agent/review", 4001, {"draft": "not-an-object"}, token=token, label="review 非法 draft 4001")


def assert_extract_errors(token: str) -> None:
    """`/extract` 入参边界（4001）与鉴权（401/4010）。"""
    api_err("POST", "/api/agent/extract", 4001, {"text": ""}, token=token, label="extract 空文本 4001")
    api_err("POST", "/api/agent/extract", 4001, {"text": "一" * 4001}, token=token, label="extract 超长文本 4001")

    api_err("POST", "/api/agent/extract", 4010, {"text": "秋之韵"}, expected_status=401, label="extract 未登录 401/4010")


def assert_kb(token: str, kb_mode: str) -> None:
    """`/api/kb/similar`：top≤3、降序、threshold=0.6；默认模式校验 ≥0.6 过滤。"""
    unfiltered = kb_mode == "unfiltered"

    if not unfiltered:
        # 逐条发布造数：description 留空，保证与 q 的重叠不被长描述稀释
        for title in KB_TITLES:
            created = api_ok("POST", "/api/tasks", {"title": title}, token=token, label=f"造 KB 数据：{title}")
            expect(isinstance(created.get("id"), int), f"KB 数据任务「{title}」发布成功")

    query = urllib.parse.quote(KB_QUERY)
    data = api_ok("GET", f"/api/kb/similar?q={query}", token=token, label="kb/similar（强相似）")
    items = data.get("items")
    expect(isinstance(items, list), "kb/similar 返回 items 数组")
    expect(data.get("threshold") == 0.6, f"threshold 恒为 0.6（实际 {data.get('threshold')}）")
    expect(len(items) >= 1, f"强相似查询返回 ≥1 条（实际 {len(items)}）")
    expect(len(items) <= 3, f"top 截断为 ≤3 条（实际 {len(items)}）")

    similarities = [float(item.get("similarity") or 0) for item in items]
    expect(
        similarities == sorted(similarities, reverse=True),
        f"相似度降序排列（实际 {similarities}）",
    )
    expect(all(0 < s <= 1 for s in similarities), f"相似度取值区间 (0,1]（实际 {similarities}）")
    expect(
        any(item.get("title") == KB_QUERY for item in items),
        f"返回结果包含目标标题「{KB_QUERY}」（实际 {[i.get('title') for i in items]}）",
    )
    top1 = items[0]
    expect(top1.get("similarity") >= 0.6, f"top1 相似度 ≥0.6（实际 {top1.get('similarity')}）")
    expect(isinstance(top1.get("task_id"), int), f"SimilarItem 含 int task_id（实际 {top1.get('task_id')!r}）")

    if unfiltered:
        print(f"INFO: unfiltered 模式 similarity 列表 = {similarities}")
    else:
        expect(
            all(s >= 0.6 for s in similarities),
            f"默认模式（KB_MIN_SIMILARITY=0.6）所有返回项 similarity ≥0.6（实际 {similarities}）",
        )

    weak = api_ok("GET", f"/api/kb/similar?q={urllib.parse.quote(KB_WEAK_QUERY)}", token=token, label="kb/similar（弱相似）")
    weak_items = weak.get("items") or []
    expect(isinstance(weak_items, list), "弱相似查询返回 items 数组")
    expect(len(weak_items) <= 3, f"弱相似查询同样 top ≤3（实际 {len(weak_items)}）")
    if unfiltered:
        print(f"INFO: unfiltered 模式 q={KB_WEAK_QUERY!r} 可见 {len(weak_items)} 条（默认模式应为 0 条）")
    else:
        expect(
            weak_items == [],
            f"默认模式过滤掉低于 0.6 的候选：q={KB_WEAK_QUERY!r} 返回 0 条（实际 {len(weak_items)} 条）",
        )

    api_err("GET", "/api/kb/similar?q=", 4001, token=token, label="kb/similar 空 q 4001")
    api_err("GET", f"/api/kb/similar?q={'%E4%B8%80' * 501}", 4001, token=token, label="kb/similar q 超长 4001")
    api_err(
        "GET",
        f"/api/kb/similar?q={urllib.parse.quote(KB_QUERY)}",
        4010,
        expected_status=401,
        label="kb/similar 未登录 401/4010",
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    kb_mode = "default"
    for arg in sys.argv[1:]:
        if arg.startswith("--kb-mode="):
            kb_mode = arg.split("=", 1)[1].strip() or "default"
    expect(kb_mode in {"default", "unfiltered"}, f"--kb-mode 取值合法（实际 {kb_mode}）")
    print(f"INFO: 运行模式 kb_mode={kb_mode}，后端 {BASE_URL}")

    token = login("teacher01")

    if kb_mode == "default":
        assert_extract_rules(token)
        assert_stream_merge(token)
        assert_review(token)
        assert_extract_errors(token)
        # stream/parse 的 session_id 必填（4001）
        api_err(
            "POST",
            "/api/agent/stream/parse",
            4001,
            {"session_id": "   ", "chunk": "秋之韵"},
            token=token,
            label="stream/parse 空 session_id 4001",
        )
    assert_kb(token, kb_mode)

    print(f"---- test_agent_mock.py（{kb_mode}）全部通过：{_passed} 项断言 ----")
    return 0


if __name__ == "__main__":
    sys.exit(main())