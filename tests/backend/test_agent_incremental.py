#!/usr/bin/env python
"""第三轮（`C-AGENT@3`）增量 / 链式 / 拼接 / 介绍建议 / 纯值回归。

覆盖（plan P3 T5 ①）：
1. **纯函数矩阵**（直接 import `app.agents.diffing`，无 I/O）：
   - `is_pure_value` 允许/拒绝值矩阵；`sanitize_value` 三条规则；
   - `diff_draft` 的 op/field/old_value/new_value 与固定顺序；
   - `applied_texts_for` 逐字模板（AI 补充/修改/新增扩展项、用户新建/修改/删除）；
   - `merge_draft` 保留 `base.trace`、`extra_tags` 键级合并、`unresolved` 全量替换；
   - `mock_extract` 增量：`quota 3→6` 只产生 1 条 change，且与 `base` 合并。
2. **P3 新契约纯函数**：
   - `inspect.signature(extract_stream) == (before_draft, chunk, is_final)`，旧形参
     `accumulated_text` / `draft` 已删除；
   - 真实路径 payload 固定三键（`本次新增片段 / 当前已合并草稿 / 是否最终`），
     且**不含** `累计原文`（用 monkeypatch 截获 `chat_json` 的 user payload）；
   - `join_style_prompt` 6 组矩阵（去重拼接 / 相等 / 一方空）；
   - `needs_intro` 3 组（style / 请求词 / details 已有）；
   - 审核助手介绍建议：`Draft(details=None, style_prompt=...)` ⇒ `polished.details`
     非空，且入参 `draft.details` 仍为空、`changes` 不含 details；
   - `Draft(details=None, style_prompt=None)` 且无请求词 ⇒ `polished is None`；
   - `grep "累计原文" backend/app` 0 命中（脚本内文件扫描，不依赖外部 grep）。
3. **HTTP 增量解析**：full 取 base → incremental `人数修改为 6 人` ⇒ quota=6、
   `changes` 仅 quota、`applied_texts[0]` 逐字模板；缺 `base_draft` → 4001；
   `mode=full` 忽略 `base_draft`（R12-AC9）。
4. **HTTP review 介绍建议**：details 缺失 + style_prompt ⇒ `polished.details` 非空，
   `changes` 不含 details/notes（建议永不自动落值）。
5. **HTTP stream/parse 三片链式（B7）**：片 1「明天下午两点」→ 片 2「在操场」→
   片 3「搬桌椅，3 个人」；片 2 `changes` 不含 time，片 3 不含 time/location，
   `extra_tags["工作内容"]=="搬桌椅"` 不重复。
6. **HTTP stream/parse 跨片更正**（保留 P2 行为）：教三 → 教四。
7. **红线**：所有响应 `draft` 的 8 个标量字段与 `extra_tags` 值、`changes[].new_value`
   以及本轮新增的 `polished.details` / `style_prompt` 均不含
   `AI建议` / `改为` / `用户：`（任一命中即 FAIL）。

运行前提：``T10_BASE_URL``（默认 8040）、``T10_BACKEND_DIR``（后端工程根，供 sys.path）。
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = os.getenv("T10_BASE_URL", "http://127.0.0.1:8040").rstrip("/")
BACKEND_DIR = (os.getenv("T10_BACKEND_DIR") or str(Path(__file__).resolve().parents[2] / "backend")).strip()

#: 红线标记（R13-AC5 / R18-AC10）
TRACE_MARKERS = ("AI建议", "改为", "用户：")

#: draft 需要检查的 8 个标量字段
SCALAR_FIELDS = (
    "title",
    "time",
    "location",
    "details",
    "quota",
    "volunteer_hours",
    "notes",
    "requirements",
)

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
# 后端纯函数导入（只导入 diffing / extractor / mock_fixtures / schemas）
# --------------------------------------------------------------------------- #
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
try:
    from app.agents import diffing, extractor, llm_client, mock_fixtures  # noqa: E402
    from app.schemas import Ambiguity, ChangeOut, Draft, TraceBlock  # noqa: E402
except Exception as exc:  # 依赖缺失时给出可执行原因（不得静默跳过纯函数断言）
    print(f"FAIL: 无法导入 app.agents.*（{type(exc).__name__}: {exc}）；BACKEND_DIR={BACKEND_DIR}")
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


def assert_no_trace_markers(draft: dict, label: str) -> None:
    """红线：draft 标量字段 + extra_tags 值不得含追溯建议语。"""
    for field in SCALAR_FIELDS:
        value = draft.get(field)
        if isinstance(value, str):
            for marker in TRACE_MARKERS:
                expect(marker not in value, f"{label}：draft.{field} 不含「{marker}」（实际 {value!r}）")
    tags = draft.get("extra_tags") or {}
    expect(isinstance(tags, dict), f"{label}：extra_tags 为对象")
    for key, value in tags.items():
        expect(isinstance(value, str), f"{label}：extra_tags[{key}] 为字符串")
        for marker in TRACE_MARKERS:
            expect(marker not in value, f"{label}：extra_tags[{key}] 不含「{marker}」（实际 {value!r}）")


def assert_changes_pure(data: dict, label: str) -> None:
    """红线：changes[].new_value 必须通过 is_pure_value，且字段值不含建议语。"""
    changes = data.get("changes")
    expect(isinstance(changes, list), f"{label}：changes 为数组")
    for change in changes:
        new_value = change.get("new_value")
        expect(diffing.is_pure_value(new_value), f"{label}：new_value 为纯值（实际 {new_value!r}，field={change.get('field')}）")
        if isinstance(new_value, str):
            for marker in TRACE_MARKERS:
                expect(marker not in new_value, f"{label}：new_value 不含「{marker}」（实际 {new_value!r}）")


# --------------------------------------------------------------------------- #
# 1) is_pure_value / sanitize_value 矩阵
# --------------------------------------------------------------------------- #
def case_pure_value_matrix() -> None:
    allowed: list[object] = ["14:00", "教四", "搬桌椅、摄影", "5", "秋之韵志愿招募", 5, 3.5]
    for value in allowed:
        expect(diffing.is_pure_value(value), f"is_pure_value({value!r}) 为 True")

    rejected: list[object] = [
        None,
        True,
        False,
        "",
        "   ",
        "建议改为 14:00",
        "14:00 或 15:00",
        "请补充",
        "推荐 5 人",
        "AI建议：补充时间为「14:00」",
        "用户：将时间改为 14:00",
        "a" * 65,
        "a\nb",
        ["14:00"],
        {"time": "14:00"},
    ]
    for value in rejected:
        expect(not diffing.is_pure_value(value), f"is_pure_value({value!r}) 为 False")

    expect(diffing.sanitize_value("AI建议：将名额改为 6") is None, "sanitize_value 纯建议句无「」→ None")
    expect(diffing.sanitize_value("AI建议：补充名额为「6」") == "6", "sanitize_value 提取最后一个「」内容")
    expect(diffing.sanitize_value("教四") == "教四", "sanitize_value 普通值原样返回")
    expect(diffing.sanitize_value("  教四  ") == "教四", "sanitize_value 去首尾空白")
    expect(diffing.sanitize_value("") is None and diffing.sanitize_value(None) is None, "sanitize_value 空值 → None")

    dirty = Draft(
        title="AI建议：改为「秋之韵志愿招募」",
        time="用户：将时间由「下午」改为「14:00」",
        extra_tags={"工作内容": "AI建议：新增扩展项「摄影」"},
    )
    clean = diffing.sanitize_draft(dirty)
    expect(clean.title == "秋之韵志愿招募", f"sanitize_draft 净化 title（实际 {clean.title!r}）")
    expect(clean.time == "14:00", f"sanitize_draft 取最后一个「」为 time（实际 {clean.time!r}）")
    expect(clean.extra_tags.get("工作内容") == "摄影", f"sanitize_draft 净化 extra_tags（实际 {clean.extra_tags!r}）")
    assert_no_trace_markers(clean.model_dump(), "sanitize_draft")


# --------------------------------------------------------------------------- #
# 2) diff_draft / applied_texts_for 逐字模板
# --------------------------------------------------------------------------- #
def case_diff_and_texts() -> None:
    changes = diffing.diff_draft(None, Draft(quota=6))
    expect(len(changes) == 1, f"diff(None, quota=6) 只 1 条（实际 {len(changes)}）")
    expect(changes[0].op == "set" and changes[0].field == "quota", "op=set / field=quota")
    expect(changes[0].old_value is None and changes[0].new_value == 6, "old=None / new=6（int 不解字符串化）")
    texts = diffing.applied_texts_for(changes)
    expect(texts == ["AI建议：补充名额为「6」"], f"补充模板逐字一致（实际 {texts}）")

    changes = diffing.diff_draft(Draft(quota=3), Draft(quota=6))
    expect(len(changes) == 1, "3→6 只 1 条 change")
    expect(changes[0].old_value == 3 and changes[0].new_value == 6, "old_value=3 / new_value=6")
    texts = diffing.applied_texts_for(changes)
    expect(texts == ["AI建议：将名额由「3」改为「6」"], f"修改模板逐字一致（实际 {texts}）")

    changes = diffing.diff_draft(Draft(), Draft(extra_tags={"摄影": "2 人"}))
    expect(len(changes) == 1 and changes[0].op == "add_tag", "新增扩展项 op=add_tag")
    expect(changes[0].field == "extra_tags.摄影", f"扩展项 field 路径（实际 {changes[0].field}）")
    texts = diffing.applied_texts_for(changes)
    expect(texts == ["AI建议：新增扩展项「摄影」，内容为「2 人」"], f"add_tag 模板逐字一致（实际 {texts}）")

    ordered = diffing.diff_draft(None, Draft(title="秋之韵志愿招募", quota=6))
    expect([c.field for c in ordered] == ["title", "quota"], f"字段顺序固定（实际 {[c.field for c in ordered]}）")
    expect(diffing.diff_draft(Draft(quota=6), Draft(quota=6)) == [], "值相同不产出 change")
    expect(diffing.diff_draft(Draft(notes="原备注"), Draft()) == [], "增量解析不产出删除 change")
    expect(diffing.diff_draft(Draft(), Draft(details="建议改为 14:00")) == [], "非纯值 new_value 被丢弃（宁缺勿污染）")

    user_cases = [
        (ChangeOut(op="set", field="quota", old_value=None, new_value="6", source="user"), "用户：新建名额，内容为「6」"),
        (ChangeOut(op="set", field="quota", old_value=3, new_value=6, source="user"), "用户：将名额由「3」改为「6」"),
        (ChangeOut(op="remove_tag", field="extra_tags.摄影", old_value="2 人", new_value=None, source="user"), "用户：删除扩展项「摄影」（原「2 人」）"),
        # 契约 2.2.3 C：add_tag 模板与 source 无关，仅前缀随 source 变化（后端唯一实现）
        (ChangeOut(op="add_tag", field="extra_tags.摄影", old_value=None, new_value="2 人", source="user"), "用户：新增扩展项「摄影」，内容为「2 人」"),
        (ChangeOut(op="set", field="time", old_value="下午", new_value=None, source="user"), "用户：清空时间（原「下午」）"),
    ]
    for change, expected in user_cases:
        actual = diffing.applied_texts_for([change])
        expect(actual == [expected], f"用户模板逐字一致（期望 {expected!r}，实际 {actual}）")

    mixed = diffing.diff_draft(Draft(time="下午"), Draft(time="14:00", location="教四"))
    expect(len(diffing.applied_texts_for(mixed)) == len(mixed), "applied_texts 与 changes 等长")


# --------------------------------------------------------------------------- #
# 3) merge_draft / unresolved / review changes / mock 确定性
# --------------------------------------------------------------------------- #
def case_merge_and_mock() -> None:
    trace_block = TraceBlock(id=1, text="用户：将名额由「3」改为「6」", kind="user_edit", field="quota")
    base = Draft(
        title="秋之韵志愿招募",
        quota=3,
        extra_tags={"工作内容": "搬桌椅"},
        trace=[trace_block],
    )
    incoming = Draft(quota=6, extra_tags={"摄影": "2 人"}, style_prompt="措辞严谨一点")
    merged = diffing.merge_draft(base, incoming)
    expect(merged.title == "秋之韵志愿招募", "merge：base.title 在增量未提及时保留")
    expect(merged.quota == 6, f"merge：quota 覆盖为 6（实际 {merged.quota}）")
    expect(merged.extra_tags == {"工作内容": "搬桌椅", "摄影": "2 人"}, f"merge：extra_tags 键级合并（实际 {merged.extra_tags}）")
    expect(merged.style_prompt == "措辞严谨一点", "merge：无 base style 时取 incoming style")
    expect(
        isinstance(merged.trace, list) and len(merged.trace) == 1 and merged.trace[0].id == 1
        and merged.trace[0].text == trace_block.text,
        "merge：base.trace 原样保留（不清洗/不重建/不排序）",
    )
    kept = diffing.merge_draft(base, Draft())
    expect(kept.quota == 3 and kept.title == "秋之韵志愿招募", "merge：incoming 空值不覆盖 base")
    expect(diffing.merge_unresolved(["下午具体几点开始？"]) == ["下午具体几点开始？"], "unresolved 全量替换")
    expect(diffing.merge_unresolved(None) == [], "unresolved 为空时为 []")

    # review：suggestion 纯值 → changes 含 time → "14:00"；polished 整段不进入 changes
    review = mock_fixtures.mock_review(Draft(time="下午", details="招募志愿者", style_prompt="措辞严谨一点"))
    expect(review.mock is True, "mock_review 返回 mock=true")
    expect(review.polished is not None, "mock_review 有 details+style_prompt 时 polished 非 null")
    expect(bool(review.ambiguities), "mock_review ambiguities 非空")
    expect(review.ambiguities[0].field == "time", f"歧义字段为 time（实际 {review.ambiguities[0].field}）")
    expect(review.ambiguities[0].suggestion == "14:00", f"suggestion 为纯值 14:00（实际 {review.ambiguities[0].suggestion!r}）")
    time_changes = [c for c in review.changes if c.field == "time"]
    expect(len(time_changes) == 1, f"changes 含 1 条 time（实际 {len(time_changes)}）")
    expect(time_changes[0].old_value == "下午" and time_changes[0].new_value == "14:00", "time change 下午→14:00")
    expect(time_changes[0].source == "ai", "review changes source=ai")
    expect(all(diffing.is_pure_value(c.new_value) for c in review.changes), "review changes 全部为纯值")
    expect(
        not any(c.field in ("details", "notes") for c in review.changes),
        f"polished 整段文本不进入 changes（实际 fields={[c.field for c in review.changes]}）",
    )
    impure = diffing.changes_from_ambiguities(
        Draft(time="下午"), [Ambiguity(field="time", question="几点？", suggestion="14:00 或 15:00")]
    )
    expect(impure == [], "含「或」的建议不产出 change（R13-AC4），ambiguities 另行保留")

    # mock_extract 增量（T3 验收 ⑤）：quota 3→6 只 1 条 change
    out = mock_fixtures.mock_extract(
        "人数修改为 6 人",
        base_draft=Draft(title="秋之韵志愿招募", quota=3),
        mode="incremental",
    )
    expect(out.mock is True, "mock_extract 增量返回 mock=true")
    expect(out.draft.title == "秋之韵志愿招募", f"增量保留 base.title（实际 {out.draft.title!r}）")
    expect(out.draft.quota == 6, f"增量合并 quota=6（实际 {out.draft.quota}）")
    expect(len(out.changes) == 1, f"quota 3→6 只 1 条 change（实际 {len(out.changes)}）")
    expect(out.changes[0].field == "quota" and out.changes[0].old_value == 3 and out.changes[0].new_value == 6, "change 结构 3→6")
    expect(len(out.applied_texts) == len(out.changes), "changes 与 applied_texts 等长")
    expect(out.applied_texts[0] == "AI建议：将名额由「3」改为「6」", f"applied_texts 逐字模板（实际 {out.applied_texts}）")
    assert_no_trace_markers(out.draft.model_dump(), "mock_extract 增量")
    assert_changes_pure(out.model_dump(), "mock_extract 增量")
    again = mock_fixtures.mock_extract(
        "人数修改为 6 人",
        base_draft=Draft(title="秋之韵志愿招募", quota=3),
        mode="incremental",
    )
    expect(again.model_dump() == out.model_dump(), "同一输入两次 mock_extract 结果完全一致（确定性）")

    # 值净化红线：把建议句塞进输入，draft 字段与 extra_tags 不得被污染
    dirty = mock_fixtures.mock_extract("AI建议：将名额改为 6 人")
    assert_no_trace_markers(dirty.draft.model_dump(), "mock_extract 净化")
    assert_changes_pure(dirty.model_dump(), "mock_extract 净化")


# --------------------------------------------------------------------------- #
# 4) P3 纯函数：signature / payload 三键 / join_style_prompt / needs_intro
# --------------------------------------------------------------------------- #
def case_extract_stream_signature() -> None:
    signature = inspect.signature(extractor.extract_stream)
    params = list(signature.parameters)
    expect(params == ["before_draft", "chunk", "is_final"], f"extract_stream 形参为 (before_draft, chunk, is_final)（实际 {params}）")
    expect("accumulated_text" not in params, "extract_stream 已删除旧形参 accumulated_text")
    expect("draft" not in params, "extract_stream 已删除旧形参 draft（改名为 before_draft）")
    defaults = [p.default for p in signature.parameters.values()]
    expect(all(value is inspect.Parameter.empty for value in defaults), "三个形参均为必填（无默认值）")


def case_stream_payload_three_keys() -> None:
    """截获真实路径的 user payload：必须恰好三键且不含累计原文（B7 / R18-AC3/AC5）。"""
    captured: dict[str, object] = {}
    original_is_mock = llm_client.is_mock_mode
    original_chat_json = llm_client.chat_json

    def fake_is_mock() -> bool:
        return False

    def fake_chat_json(system_prompt: str, user_payload: str, validate=None):  # noqa: ANN001
        captured["system_prompt"] = system_prompt
        captured["raw_payload"] = user_payload
        payload = json.loads(user_payload)
        captured["payload"] = payload
        raw = {"location": "操场"}
        return validate(raw) if validate is not None else raw

    llm_client.is_mock_mode = fake_is_mock  # type: ignore[assignment]
    llm_client.chat_json = fake_chat_json  # type: ignore[assignment]
    try:
        before = Draft(title="已有标题", time="明天下午两点")
        out = extractor.extract_stream(before, "在操场", False)
    finally:
        llm_client.is_mock_mode = original_is_mock  # type: ignore[assignment]
        llm_client.chat_json = original_chat_json  # type: ignore[assignment]

    payload = captured.get("payload")
    expect(isinstance(payload, dict), f"截获到真实路径 user payload（实际 {payload!r}）")
    keys = list(payload.keys())
    expect(keys == ["本次新增片段", "当前已合并草稿", "是否最终"], f"payload 固定三键且顺序固定（实际 {keys}）")
    expect("累计原文" not in keys, "payload 不含「累计原文」键（B7）")
    expect("当前草稿" not in keys, "payload 不含旧键「当前草稿」")
    expect(payload["本次新增片段"] == "在操场", f"本次新增片段=chunk（实际 {payload['本次新增片段']!r}）")
    expect(payload["是否最终"] is False, "是否最终=false")
    expect(payload["当前已合并草稿"].get("title") == "已有标题", "当前已合并草稿为 before_draft")
    expect("累计原文" not in str(captured.get("raw_payload")), "原始 payload 文本中无累计原文")
    expect(out.draft.location == "操场" and out.draft.title == "已有标题", f"真实路径返回已与 before 合并（实际 {out.draft.model_dump()}）")


def case_join_style_prompt() -> None:
    cases: list[tuple[object, object, str | None, str]] = [
        (None, None, None, "双方为空 → None"),
        ("", "", None, "双空串 → None"),
        ("温柔一点", None, "温柔一点", "base 非空 + incoming 空 → base"),
        (None, "严谨一点", "严谨一点", "base 空 + incoming 非空 → incoming"),
        ("温柔一点", "严谨一点", "温柔一点、严谨一点", "base+incoming 拼接"),
        ("温柔一点、严谨一点", "温柔一点", "温柔一点、严谨一点", "重复片段去重保序"),
        ("温柔一点", "温柔一点", "温柔一点", "完全相同 → 不重复"),
        ("温柔一点", "温柔一点、", "温柔一点", "尾分隔符拆分后相等 → 不重复"),
    ]
    for base, incoming, expected, label in cases:
        actual = diffing.join_style_prompt(base, incoming)
        expect(actual == expected, f"join_style_prompt({base!r}, {incoming!r}) == {expected!r}（{label}，实际 {actual!r}）")

    merged = diffing.merge_draft(Draft(style_prompt="温柔一点"), Draft(style_prompt="严谨一点"))
    expect(merged.style_prompt == "温柔一点、严谨一点", f"merge_draft 走拼接而非覆盖（实际 {merged.style_prompt!r}）")
    dedup = diffing.merge_draft(Draft(style_prompt="温柔一点、严谨一点"), Draft(style_prompt="温柔一点"))
    expect(dedup.style_prompt == "温柔一点、严谨一点", f"merge_draft 二次补充同词不重复（实际 {dedup.style_prompt!r}）")


def case_needs_intro() -> None:
    expect(diffing.needs_intro(Draft(title="秋之韵志愿招募", style_prompt="温柔一点")), "details 空 + style 非空 → True")
    expect(diffing.needs_intro(Draft(title="帮我写一段活动介绍")), "details 空 + 请求词（帮我写）→ True")
    expect(diffing.needs_intro(Draft(title="润色一下这个任务")), "details 空 + 请求词（润色）→ True")
    expect(not diffing.needs_intro(Draft(title="秋之韵志愿招募", details="已有详情")), "details 非空 → False（即使有 style）")
    expect(not diffing.needs_intro(Draft(title="秋之韵志愿招募")), "details 空 + 无 style + 无请求词 → False")
    expect(not diffing.needs_intro(Draft(title="秋之韵志愿招募", details="   ", style_prompt="  ")), "details/style 仅空白 → False")


def case_review_intro_suggestion() -> None:
    # ① details 空 + style_prompt ⇒ 必须给完整介绍；入参 draft 不被写值、changes 不含 details
    draft = Draft(
        title="秋之韵志愿招募",
        time="明天下午两点",
        location="操场",
        quota=3,
        extra_tags={"工作内容": "搬桌椅"},
        style_prompt="温柔一点",
    )
    review = mock_fixtures.mock_review(draft)
    expect(review.polished is not None, "details 空 + style ⇒ polished 非 null")
    details = (review.polished.details or "").strip() if review.polished else ""
    expect(len(details) >= 20, f"polished.details 为完整介绍文案（实际 {details!r}）")
    expect("秋之韵志愿招募" in details, f"介绍文案含任务标题（实际 {details!r}）")
    expect(draft.details is None, f"审核不写回入参 draft.details（实际 {draft.details!r}）")
    expect(not any(c.field in ("details", "notes") for c in review.changes), f"介绍文案不进入 changes（实际 {[c.field for c in review.changes]}）")
    for marker in TRACE_MARKERS:
        expect(marker not in details, f"介绍文案不含「{marker}」（实际 {details!r}）")

    # ② details 空 + style 空 + 无请求词 ⇒ polished 必须 null
    no_intro = mock_fixtures.mock_review(Draft(title="秋之韵志愿招募", time="明天下午两点"))
    expect(no_intro.polished is None, f"无 style/无请求词/details 空 ⇒ polished is None（实际 {no_intro.polished!r}）")

    # ③ 请求词触发（title 含「帮我写」）即便无 style 也给介绍
    requested = mock_fixtures.mock_review(Draft(title="帮我写一段秋之韵活动介绍", quota=5))
    expect(requested.polished is not None and bool((requested.polished.details or "").strip()), "请求词触发介绍建议（无 style）")
    expect(not any(c.field in ("details", "notes") for c in requested.changes), "请求词介绍同样不进入 changes")


def case_no_accumulated_key_in_backend() -> None:
    """`grep "累计原文" backend/app` 必须 0 命中（payload 键已删除，留痕只在 DB 字段名）。"""
    app_dir = Path(BACKEND_DIR) / "app"
    expect(app_dir.is_dir(), f"backend/app 目录存在（实际 {app_dir}）")
    hits: list[str] = []
    scanned = 0
    for file_path in sorted(app_dir.rglob("*.py")):
        scanned += 1
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if "累计原文" in text:
            for line_number, line in enumerate(text.splitlines(), start=1):
                if "累计原文" in line:
                    hits.append(f"{file_path.relative_to(app_dir).as_posix()}:{line_number}")
    expect(
        not hits,
        f"扫描 backend/app {scanned} 个 .py 文件，「累计原文」0 命中（实际 {hits}）",
    )


# --------------------------------------------------------------------------- #
# 5) HTTP：extract full / incremental / 缺 base_draft / full 忽略 base
# --------------------------------------------------------------------------- #
def case_extract_http(token: str) -> None:
    full = api_ok(
        "POST", "/api/agent/extract", {"text": "明天下午两点在操场搬桌椅，3 个人"}, token=token,
        label="extract full",
    )
    expect(full.get("mock") is True, "extract full mock=true")
    expect(full["draft"].get("location") == "操场", f"full location=操场（实际 {full['draft'].get('location')}）")
    expect(full["draft"].get("quota") == 3, f"full quota=3（实际 {full['draft'].get('quota')}）")
    expect(isinstance(full.get("changes"), list) and full["changes"], "full changes 非空")
    expect(len(full["changes"]) == len(full.get("applied_texts") or []), "full changes 与 applied_texts 等长")
    expect(
        [c.get("field") for c in full["changes"]][:2] == ["time", "location"],
        f"changes 固定顺序从 time/location 开始（实际 {[c.get('field') for c in full['changes']]}）",
    )
    assert_no_trace_markers(full["draft"], "extract full")
    assert_changes_pure(full, "extract full")
    base = full["draft"]

    incremental = api_ok(
        "POST",
        "/api/agent/extract",
        {"text": "人数修改为 6 人", "base_draft": base, "mode": "incremental"},
        token=token,
        label="extract incremental",
    )
    draft = incremental["draft"]
    expect(incremental.get("mock") is True, "extract incremental mock=true")
    expect(draft.get("quota") == 6, f"增量合并 quota=6（实际 {draft.get('quota')}）")
    expect(draft.get("location") == "操场", f"增量保留 base.location（实际 {draft.get('location')}）")
    expect(draft.get("time") == base.get("time"), "增量保留 base.time")
    expect(draft.get("extra_tags") == base.get("extra_tags"), "增量保留 base.extra_tags")
    expect(len(incremental["changes"]) == 1, f"quota 3→6 只 1 条 change（实际 {len(incremental['changes'])}）")
    change = incremental["changes"][0]
    expect(change.get("field") == "quota" and change.get("old_value") == 3 and change.get("new_value") == 6, f"change 结构 3→6（实际 {change}）")
    expect(change.get("source") == "ai", "change source=ai")
    expect(incremental.get("applied_texts") == ["AI建议：将名额由「3」改为「6」"], f"applied_texts 逐字（实际 {incremental.get('applied_texts')}）")
    assert_no_trace_markers(draft, "extract incremental")
    assert_changes_pure(incremental, "extract incremental")

    api_err(
        "POST", "/api/agent/extract", 4001, {"text": "人数修改为 6 人", "mode": "incremental"},
        token=token, label="缺 base_draft 4001",
    )

    # R12-AC9：mode=full 忽略 base_draft
    full_again = api_ok(
        "POST",
        "/api/agent/extract",
        {"text": "人数修改为 6 人", "base_draft": base, "mode": "full"},
        token=token,
        label="extract full 忽略 base_draft",
    )
    expect(full_again["draft"].get("location") is None, f"full 忽略 base.location（实际 {full_again['draft'].get('location')}）")
    expect(full_again["draft"].get("quota") == 6, f"full quota=6（实际 {full_again['draft'].get('quota')}）")
    fields = [c.get("field") for c in full_again["changes"]]
    expect("quota" in fields, f"full changes 含 quota（实际 {fields}）")
    expect(len(full_again["changes"]) == len(full_again.get("applied_texts") or []), "full changes/applied_texts 等长")
    assert_no_trace_markers(full_again["draft"], "extract full 忽略 base")
    assert_changes_pure(full_again, "extract full 忽略 base")

    api_err("POST", "/api/agent/extract", 4001, {"text": "   "}, token=token, label="空文本 4001")
    api_err("POST", "/api/agent/extract", 4010, {"text": "秋之韵"}, expected_status=401, label="extract 未登录 401/4010")

    # R18-AC6 验收示例 2：style_prompt 叠加拼接 + 重复补充不重复（HTTP 增量链路）
    base_with_style = dict(base)
    base_with_style["style_prompt"] = "温柔一点"
    styled = api_ok(
        "POST",
        "/api/agent/extract",
        {"text": "措辞严谨一点", "base_draft": base_with_style, "mode": "incremental"},
        token=token,
        label="style 拼接（温柔一点 + 严谨一点）",
    )
    expect(
        styled["draft"].get("style_prompt") == "温柔一点、措辞严谨一点",
        f"增量 style_prompt 叠加拼接（实际 {styled['draft'].get('style_prompt')!r}）",
    )
    styled_again = api_ok(
        "POST",
        "/api/agent/extract",
        {"text": "措辞严谨一点", "base_draft": styled["draft"], "mode": "incremental"},
        token=token,
        label="style 重复补充去重",
    )
    expect(
        styled_again["draft"].get("style_prompt") == "温柔一点、措辞严谨一点",
        f"重复补充同一风格不重复拼接（实际 {styled_again['draft'].get('style_prompt')!r}）",
    )
    assert_no_trace_markers(styled_again["draft"], "style 拼接")


# --------------------------------------------------------------------------- #
# 6) HTTP：review（含介绍建议 + 纯值）
# --------------------------------------------------------------------------- #
def case_review_http(token: str) -> None:
    review = api_ok(
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
        label="review（time=下午）",
    )
    expect(review.get("mock") is True, "review mock=true")
    expect(review.get("polished") is not None, "review polished 保留")
    expect(bool(review.get("ambiguities")), "review ambiguities 保留")
    expect(review["ambiguities"][0].get("suggestion") == "14:00", f"suggestion 纯值 14:00（实际 {review['ambiguities'][0].get('suggestion')}）")
    time_changes = [c for c in review["changes"] if c.get("field") == "time"]
    expect(len(time_changes) == 1, f"review changes 含 time（实际 {[c.get('field') for c in review['changes']]}）")
    expect(time_changes[0].get("new_value") == "14:00", f"time new_value=14:00（实际 {time_changes[0].get('new_value')}）")
    expect(time_changes[0].get("old_value") == "下午", f"time old_value=下午（实际 {time_changes[0].get('old_value')}）")
    expect(not any(c.get("field") in ("details", "notes") for c in review["changes"]), "polished 整段不进入 changes")
    assert_changes_pure(review, "review")

    # B10：details 空 + style_prompt ⇒ polished.details 为完整介绍；changes 仍不含 details
    intro = api_ok(
        "POST",
        "/api/agent/review",
        {
            "draft": {
                "title": "秋之韵志愿招募",
                "time": "明天下午两点",
                "location": "操场",
                "quota": 3,
                "extra_tags": {"工作内容": "搬桌椅"},
                "style_prompt": "温柔一点",
            }
        },
        token=token,
        label="review（details 空 + style → 介绍建议）",
    )
    polished = intro.get("polished") or {}
    intro_details = (polished.get("details") or "").strip()
    expect(len(intro_details) >= 20, f"polished.details 为完整介绍文案（实际 {intro_details!r}）")
    expect("秋之韵志愿招募" in intro_details, f"介绍文案含任务标题（实际 {intro_details!r}）")
    expect(not any(c.get("field") in ("details", "notes") for c in intro["changes"]), f"介绍文案不进入 changes（实际 {[c.get('field') for c in intro['changes']]}）")
    for marker in TRACE_MARKERS:
        expect(marker not in intro_details, f"介绍文案不含「{marker}」（实际 {intro_details!r}）")
    expect(polished.get("details") == intro_details, "polished.details 未被改写")

    # details 空 + 无 style + 标题无请求词 ⇒ polished 必须 null
    no_style = api_ok(
        "POST", "/api/agent/review", {"draft": {"title": "秋之韵志愿招募", "time": "明天下午两点"}}, token=token,
        label="review（无 style、无请求词、无 details）",
    )
    expect(no_style.get("polished") is None, f"无 style/无请求词时 polished=null（实际 {no_style.get('polished')!r}）")

    api_err("POST", "/api/agent/review", 4001, {"draft": "not-an-object"}, token=token, label="review 非法 draft 4001")


# --------------------------------------------------------------------------- #
# 7) HTTP：stream/parse 三片链式（B7）与跨片更正
# --------------------------------------------------------------------------- #
def case_stream_chain_http(token: str) -> None:
    session_id = "t5-chain-3chunks"
    first = api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": session_id, "chunk": "明天下午两点", "is_final": False},
        token=token,
        label="chain 第 1 片（明天下午两点）",
    )
    expect(first["draft"].get("time") == "明天下午两点", f"第 1 片 time=明天下午两点（实际 {first['draft'].get('time')!r}）")
    expect(first["draft"].get("location") is None, f"第 1 片 location 为空（实际 {first['draft'].get('location')!r}）")
    first_fields = [c.get("field") for c in first["changes"]]
    expect("time" in first_fields, f"第 1 片 changes 含 time（实际 {first_fields}）")
    assert_no_trace_markers(first["draft"], "chain 第 1 片")
    assert_changes_pure(first, "chain 第 1 片")

    second = api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": session_id, "chunk": "在操场", "is_final": False},
        token=token,
        label="chain 第 2 片（在操场）",
    )
    second_fields = [c.get("field") for c in second["changes"]]
    expect(second["draft"].get("location") == "操场", f"第 2 片 location=操场（实际 {second['draft'].get('location')!r}）")
    expect(second["draft"].get("time") == "明天下午两点", "第 2 片保留 time")
    expect("time" not in second_fields, f"第 2 片 changes 不含 time（不重复产出，实际 {second_fields}）")
    expect(second_fields == ["location"], f"第 2 片 changes 仅 location（实际 {second_fields}）")
    assert_no_trace_markers(second["draft"], "chain 第 2 片")
    assert_changes_pure(second, "chain 第 2 片")

    third = api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": session_id, "chunk": "搬桌椅，3 个人", "is_final": True},
        token=token,
        label="chain 第 3 片（搬桌椅，3 个人）",
    )
    third_fields = [c.get("field") for c in third["changes"]]
    merged = third["draft"]
    expect(merged.get("time") == "明天下午两点", "第 3 片保留 time")
    expect(merged.get("location") == "操场", "第 3 片保留 location")
    expect(merged.get("quota") == 3, f"第 3 片 quota=3（实际 {merged.get('quota')!r}）")
    expect(merged.get("extra_tags") == {"工作内容": "搬桌椅"}, f"第 3 片 extra_tags 不重复（实际 {merged.get('extra_tags')!r}）")
    expect("time" not in third_fields and "location" not in third_fields, f"第 3 片 changes 不含 time/location（实际 {third_fields}）")
    expect(set(third_fields) == {"quota", "extra_tags.工作内容"}, f"第 3 片 changes 仅 quota+工作内容（实际 {third_fields}）")
    assert_no_trace_markers(merged, "chain 第 3 片")
    assert_changes_pure(third, "chain 第 3 片")

    # 对抗探针：空尾片（chunk="" + is_final=true）必须不报错、不清空、不产出 change
    empty_session = "t5-empty-final"
    api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": empty_session, "chunk": "明天下午两点", "is_final": False},
        token=token,
        label="空尾片·前置片",
    )
    empty_final = api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": empty_session, "chunk": "", "is_final": True},
        token=token,
        label="空尾片",
    )
    expect(empty_final["changes"] == [], f"空尾片不产出 change（实际 {empty_final['changes']}）")
    expect(empty_final["draft"].get("time") == "明天下午两点", "空尾片不清空已有草稿")
    expect(empty_final.get("mock") is True, "空尾片仍返回 mock=true")

    # 跨片更正（P2 行为保留）：新 session，教三 → 教四
    corr_session = "t5-chain-correction"
    api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": corr_session, "chunk": "明天下午两点在教三集合，", "is_final": False},
        token=token,
        label="correction 第 1 片",
    )
    corrected = api_ok(
        "POST",
        "/api/agent/stream/parse",
        {"session_id": corr_session, "chunk": "哎不对是教四。", "is_final": True},
        token=token,
        label="correction 第 2 片",
    )
    expect(corrected["draft"].get("location") == "教四", f"跨片更正 location=教四（实际 {corrected['draft'].get('location')!r}）")
    location_changes = [c for c in corrected["changes"] if c.get("field") == "location"]
    expect(len(location_changes) == 1, f"跨片更正 changes 含 1 条 location（实际 {[c.get('field') for c in corrected['changes']]}）")
    expect(
        location_changes[0].get("old_value") == "教三" and location_changes[0].get("new_value") == "教四",
        f"location 教三→教四（实际 {location_changes[0]}）",
    )
    assert_no_trace_markers(corrected["draft"], "correction 第 2 片")
    assert_changes_pure(corrected, "correction 第 2 片")

    api_err(
        "POST", "/api/agent/stream/parse", 4001, {"session_id": "   ", "chunk": "秋之韵"}, token=token,
        label="stream 空 session_id 4001",
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    # 纯函数矩阵（不依赖后端进程）
    case_pure_value_matrix()
    case_diff_and_texts()
    case_merge_and_mock()
    case_extract_stream_signature()
    case_stream_payload_three_keys()
    case_join_style_prompt()
    case_needs_intro()
    case_review_intro_suggestion()
    case_no_accumulated_key_in_backend()

    # HTTP 链路（后端 8040 + MAAS_MOCK=1）
    token = login("teacher01")
    case_extract_http(token)
    case_review_http(token)
    case_stream_chain_http(token)

    print(f"---- test_agent_incremental.py 全部通过：{_passed} 项断言（链式/拼接/介绍建议/纯值红线）----")
    return 0


if __name__ == "__main__":
    sys.exit(main())