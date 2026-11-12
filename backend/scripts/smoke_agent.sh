#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# T3 后端 Agent 层冒烟回归（可重复执行）
#
# 覆盖：
#   1) Prompt 逐字落地断言（"提炼助手" / "审核助手"）
#   2) plan 2.2.7 mock 规则表逐条单元断言（不联网、确定性）
#   3) extract / review / stream/parse 三接口 + 无 token 401
#   4) stream/parse 两片合并：location=教四、corrections 保留 old_value=教三、
#      parse_sessions 仅 1 行
#   5) kb/similar：top1 >= 0.6、降序、<= 3 条、threshold=0.6
#
# 运行：bash scripts/smoke_agent.sh
# 环境：MAAS_MOCK=1 + 临时 DATABASE_PATH + RUN_SCHEDULER=0，端口默认 8003
#      （可用 PORT=xxxx 覆盖；脚本结束会关闭进程并删除全部临时文件）
# ---------------------------------------------------------------------------
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY=".venv/Scripts/python.exe"
if [ ! -x "$PY" ]; then
  PY=".venv/bin/python"
fi
if [ ! -x "$PY" ]; then
  echo "找不到 .venv 解释器（期望 backend/.venv）" >&2
  exit 1
fi

# 临时脚本放在系统临时目录，需显式把 backend 加入 sys.path（原生 Windows 路径）
ROOT_PY="$("$PY" -c 'import os; print(os.getcwd().replace(os.sep, "/"))')"
export PYTHONPATH="${ROOT_PY}"

PORT="${PORT:-8003}"
BASE="http://127.0.0.1:${PORT}"
# token 在服务器就绪后确定：优先真实登录（T2 交付后），否则回退到 boot.py 注入的 token
TOKEN=""
FALLBACK_TOKEN="smoke-token"
SESSION_ID="smoke-stream-1"

# Windows 原生 python 不认 MSYS 的 /tmp 路径，故用 tempfile 生成原生临时目录
TMP_DIR="$("$PY" -c 'import tempfile, os; print(tempfile.mkdtemp(prefix="smoke_agent_").replace(os.sep, "/"))')"
DB="$TMP_DIR/smoke_agent.db"
SERVER_PID=""

cleanup() {
  if [ -n "${SERVER_PID}" ]; then
    kill "${SERVER_PID}" 2>/dev/null || true
    case "$(uname -s)" in
      MINGW*|MSYS*|CYGWIN*) taskkill //F //PID "${SERVER_PID}" >/dev/null 2>&1 || true ;;
    esac
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
  if [ -n "${TMP_DIR}" ]; then
    rm -rf "${TMP_DIR}"
  fi
}
trap cleanup EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

# ---------------------------------------------------------------------------
# 1) Prompt 逐字落地断言
# ---------------------------------------------------------------------------
MAAS_MOCK=1 "$PY" - <<'PY'
from app.agents.prompts import EXTRACTOR_SYSTEM_PROMPT as A, REVIEWER_SYSTEM_PROMPT as B

assert "提炼助手" in A, "EXTRACTOR_SYSTEM_PROMPT 缺少'提炼助手'"
assert "审核助手" in B, "REVIEWER_SYSTEM_PROMPT 缺少'审核助手'"
assert "{CURRENT_TIME}" in A, "EXTRACTOR_SYSTEM_PROMPT 缺少 {CURRENT_TIME} 占位符"
assert "{CURRENT_TIME}" not in A.replace("{CURRENT_TIME}", "2026-01-01 10:00 星期四")
print("prompts ok")
PY
pass "prompts 逐字断言（含 {CURRENT_TIME} 占位）"

# ---------------------------------------------------------------------------
# 2) mock 规则表逐条断言（确定性、无网络）
# ---------------------------------------------------------------------------
cat > "${TMP_DIR}/unit_mock.py" <<'PY'
# -*- coding: utf-8 -*-
"""plan 2.2.7 mock 规则表逐条断言（同一 (text, is_final) 必须恒定）。"""
from app.agents.mock_fixtures import mock_extract as m, mock_review
from app.schemas import Draft

count = 0


def check(cond, msg):
    global count
    assert cond, "FAIL: " + msg
    count += 1
    print("  PASS", msg)


# 秋之韵文案（plan T3 验收 ③）
text = "下周三下午在操场办秋之韵，需要3个搬桌椅的2个摄影的，奖励20积分，措辞严谨一点"
r = m(text)
check("秋之韵" in (r.draft.title or ""), "含'秋之韵' -> title 含秋之韵")
check(r.draft.location == "操场", "location=操场")
check(r.draft.quota == 3, "quota 解析 3（'3个搬桌椅'）")
check(r.style_prompt == "措辞严谨一点" and r.draft.style_prompt == r.style_prompt, "style_prompt 与 draft 一致")
check("措辞严谨" not in (r.draft.details or ""), "风格短语已从 details 剥离")
check(any("几点" in u for u in r.unresolved), "unresolved 含'几点'")
check(bool(r.spans), "spans 非空")
check(r.mock is True, "mock=True")
check(r.draft.extra_tags.get("工作内容") == "搬桌椅、摄影", "extra_tags 追加搬桌椅、摄影")

# 教三 -> 教四 更正 + 时间 + 人数
text2 = "帮我发个任务，明天下午两点，地点教三，5个人搬桌椅，哎不对是教四"
r2 = m(text2)
check(r2.draft.location == "教四", "更正后 location=教四")
check(bool(r2.corrections) and r2.corrections[0].old_value == "教三"
      and r2.corrections[0].new_value == "教四", "corrections: 教三 -> 教四")
check(r2.corrections[0].reason == "用户的更正原话：哎不对是教四", "corrections.reason 为更正原话")
check(r2.draft.time == "明天下午两点", "time 可解析为'明天下午两点'")
check(r2.draft.quota == 5, "quota=5（'5个人搬桌椅'）")

# 仅时段 -> unresolved
r3 = m("下午在操场搬桌椅")
check(r3.draft.time == "下午", "仅时段 -> time=下午")
check(any("几点" in u for u in r3.unresolved), "仅时段 -> unresolved 含'几点'")

# 奖励积分不写入 draft
check(r.draft.notes is None, "奖励积分不写入 draft")
check(any("奖励积分为 20" in u for u in r.unresolved), "奖励积分登记 unresolved")
check(m("多带一点水").draft.time is None, "非时间语境的'一点'不误判为时间")

# 确定性
check(m(text).model_dump() == r.model_dump(), "同一 (text, is_final) 输出恒定")

# review mock
rv = mock_review(Draft(title="秋之韵志愿招募", time="下午", details="在操场搬桌椅",
                       notes=None, style_prompt="措辞严谨一点"))
check(rv.mock is True, "review mock=True")
check(rv.polished is not None and rv.polished.details.startswith("（已按风格要求润色）")
      and rv.polished.details.endswith("。"), "有 style_prompt -> polished 改写")
check(rv.polished.notes == "", "polished.notes 缺省补空串")
check(bool(rv.ambiguities) and "几点" in rv.ambiguities[0].question, "time 不明 -> ambiguities")
check(len(rv.suggested_sub_tasks) == 3
      and [s.depends_on for s in rv.suggested_sub_tasks] == [None, 0, 1],
      "秋之韵 -> 3 条子任务（depends_on null,0,1）")
check(all(len(s.sop_guide.splitlines()) >= 3 for s in rv.suggested_sub_tasks), "sop_guide 各 >= 3 步")

rv2 = mock_review(Draft(title="小型签到任务", time="明天下午两点", details=None, style_prompt=None))
check(rv2.polished is None, "无 style_prompt -> polished=null")
check(rv2.suggested_sub_tasks == [], "体量小 -> 空数组")

# llm_client：mock 判定唯一来源 + mock 下不得构造 OpenAI 客户端（plan T3 要点 3）
import os

from app.agents.llm_client import LLMError, chat_json, is_mock_mode
from app.agents.reviewer import normalize_polished

os.environ["MAAS_MOCK"] = "1"
os.environ.pop("MAAS_API_KEY", None)
check(is_mock_mode() is True, "MAAS_MOCK=1 -> mock 模式")

os.environ.pop("MAAS_MOCK", None)
os.environ["MAAS_API_KEY"] = ""
check(is_mock_mode() is True, "MAAS_API_KEY 为空 -> mock 模式")

try:
    chat_json("system", "{}")
except LLMError as exc:
    check(exc.code == 5001, "mock 模式下 chat_json 抛 LLMError(5001)，不联网")
else:
    raise AssertionError("mock 模式下不得调用真实 LLM")

os.environ["MAAS_API_KEY"] = "test-key"
os.environ["MAAS_MOCK"] = "0"
check(is_mock_mode() is False, "有 key 且 MAAS_MOCK=0 -> 真实模式")
os.environ["MAAS_MOCK"] = "1"

# reviewer polished 归一化（决策 D4）
check(normalize_polished({"details": "x"}, True).notes == "", "polished 仅 details -> notes 补空串")
check(normalize_polished({"notes": "y"}, True).details == "", "polished 仅 notes -> details 补空串")
check(normalize_polished({}, True) is None, "polished 两字段都缺 -> null")
check(normalize_polished({"details": "x"}, False) is None, "无 style_prompt -> polished=null")

print("mock unit assertions: %d passed" % count)
PY
MAAS_MOCK=1 "$PY" "${TMP_DIR}/unit_mock.py"
pass "mock 规则表逐条断言"

# ---------------------------------------------------------------------------
# 3) 启动后端（临时 DB / mock / 无调度器）
# ---------------------------------------------------------------------------
cat > "${TMP_DIR}/boot.py" <<'PY'
# -*- coding: utf-8 -*-
"""冒烟启动器：预置演示用户 + token + 两条相似任务，然后启动 uvicorn。

T2 的 /api/auth/login 尚未交付时也能验证 T3 三个接口（token 直接写入
deps.TOKENS，与真实登录同源，不绕过鉴权依赖）。
"""
import os

os.environ.setdefault("MAAS_MOCK", "1")
os.environ.setdefault("RUN_SCHEDULER", "0")

from app.db import SessionLocal, init_db
from app.deps import TOKENS
from app.models import KbEntry, Task, User
from app.services import kb_service

init_db()
db = SessionLocal()

user = db.query(User).filter(User.username == "student01").first()
if user is None:
    user = User(username="student01", display_name="演示学生", role="student",
                org="信息学院", credits=0)
    db.add(user)
    db.commit()
    db.refresh(user)
TOKENS["smoke-token"] = user.id

# 两条相似任务（q=秋之韵 时 similarity >= 0.6）+ 一条不相似任务（验证阈值过滤）
for title in ("秋之韵晚会", "秋之韵晚会", "数学建模竞赛"):
    exists = db.query(Task).filter(Task.title == title).count()
    if title == "秋之韵晚会" and exists >= 2:
        continue
    if title != "秋之韵晚会" and exists >= 1:
        continue
    task = Task(title=title, description=None, publisher_id=user.id, status="published",
                claim_type="open", extras={})
    db.add(task)
    db.commit()
    db.refresh(task)
    kb_service.index_task(db, task)

# 打印打分过程（delivery_evidence：jaccard / contain）
for entry in db.query(KbEntry).all():
    stats = kb_service.score_pair("秋之韵", entry)
    print("KB-scoring task_id=%s jaccard=%s contain=%s similarity=%s"
          % (entry.task_id, stats["jaccard"], stats["contain"], stats["similarity"]), flush=True)

db.close()

import uvicorn

uvicorn.run("app.main:app", host="127.0.0.1",
            port=int(os.environ.get("SMOKE_PORT", "8003")), log_level="warning")
PY

SMOKE_PORT="${PORT}" DATABASE_PATH="${DB}" MAAS_MOCK=1 RUN_SCHEDULER=0 \
  "$PY" "${TMP_DIR}/boot.py" > "${TMP_DIR}/server.log" 2>&1 &
SERVER_PID=$!

READY=0
for _ in $(seq 1 60); do
  if curl -sf "${BASE}/api/health" > /dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 0.5
done
if [ "${READY}" -ne 1 ]; then
  echo "--- server.log ---" >&2
  cat "${TMP_DIR}/server.log" >&2 || true
  fail "后端在 30s 内未就绪（端口 ${PORT}）"
fi
pass "uvicorn 就绪（端口 ${PORT}，mock 模式）"

# 优先走真实登录（T2 的 /api/auth/login 交付后）；未交付时回退 boot.py 注入的 token
curl -sS -X POST "${BASE}/api/auth/login" -H "Content-Type: application/json" \
  -d '{"username":"student01"}' -o "${TMP_DIR}/login.json" || true
TOKEN="$("$PY" -c 'import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8")).get("data") or {}
except Exception:
    data = {}
print(data.get("token") or "")' "${TMP_DIR}/login.json")"
if [ -n "${TOKEN}" ]; then
  pass "真实登录成功（POST /api/auth/login -> token）"
else
  TOKEN="${FALLBACK_TOKEN}"
  pass "登录接口不可用，回退预置 token（T2 未交付时的自包含模式）"
fi

# ---------------------------------------------------------------------------
# 4) 断言器（运行时生成的临时文件）
# ---------------------------------------------------------------------------
cat > "${TMP_DIR}/checks.py" <<'PY'
# -*- coding: utf-8 -*-
"""HTTP 响应断言器（case, path[, extra]）。"""
import json
import sqlite3
import sys


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


case = sys.argv[1]
path = sys.argv[2]

if case == "extract":
    body = load(path)
    assert body["code"] == 0, body
    data = body["data"]
    draft = data["draft"]
    assert "秋之韵" in (draft["title"] or ""), draft["title"]
    assert draft["location"] == "操场", draft["location"]
    assert draft["quota"] == 3, draft["quota"]
    assert "措辞严谨" in (data["style_prompt"] or ""), data["style_prompt"]
    assert data["style_prompt"] == draft["style_prompt"], "顶层与 draft.style_prompt 必须一致"
    assert any("几点" in item for item in data["unresolved"]), data["unresolved"]
    assert data["spans"], "spans 不能为空"
    assert data["mock"] is True, data["mock"]
    print("extract: title=%s location=%s quota=%s style=%s unresolved=%s spans=%d mock=%s"
          % (draft["title"], draft["location"], draft["quota"], data["style_prompt"],
             data["unresolved"], len(data["spans"]), data["mock"]))

elif case == "correction":
    body = load(path)
    data = body["data"]
    assert data["draft"]["location"] == "教四", data["draft"]["location"]
    assert data["corrections"] and data["corrections"][0]["old_value"] == "教三", data["corrections"]
    assert data["draft"]["quota"] == 5, data["draft"]["quota"]
    assert data["draft"]["time"] == "明天下午两点", data["draft"]["time"]
    assert data["mock"] is True
    print("correction: location=%s old_value=%s quota=%s time=%s"
          % (data["draft"]["location"], data["corrections"][0]["old_value"],
             data["draft"]["quota"], data["draft"]["time"]))

elif case == "review":
    body = load(path)
    data = body["data"]
    assert data["polished"] is not None, data["polished"]
    assert data["polished"]["notes"] == "", data["polished"]
    assert data["polished"]["details"].startswith("（已按风格要求润色）"), data["polished"]
    assert data["ambiguities"] and data["ambiguities"][0]["field"] == "time", data["ambiguities"]
    assert len(data["suggested_sub_tasks"]) == 3, data["suggested_sub_tasks"]
    assert data["mock"] is True
    print("review: polished=%s ambiguities=%d sub_tasks=%d mock=%s"
          % (data["polished"]["details"], len(data["ambiguities"]),
             len(data["suggested_sub_tasks"]), data["mock"]))

elif case == "stream1":
    body = load(path)
    data = body["data"]
    assert data["draft"]["time"] == "明天下午两点", data["draft"]
    assert data["draft"]["location"] == "教三", data["draft"]
    assert data["mock"] is True
    print("stream#1: time=%s location=%s spans=%d"
          % (data["draft"]["time"], data["draft"]["location"], len(data["spans"])))

elif case == "stream2":
    body = load(path)
    data = body["data"]
    draft = data["draft"]
    assert draft["location"] == "教四", draft
    assert draft["time"] == "明天下午两点", draft
    assert draft["quota"] is None, draft  # 两片文本均未提人数，不得凭空编造
    assert data["corrections"] and data["corrections"][0]["old_value"] == "教三", data["corrections"]
    assert data["corrections"][0]["new_value"] == "教四", data["corrections"]
    assert data["spans"], "spans 不能为空"
    assert data["mock"] is True
    print("stream#2: location=%s corrections=%s quota=%s spans=%d"
          % (draft["location"], data["corrections"][0], draft["quota"], len(data["spans"])))

elif case == "session_rows":
    session_id = sys.argv[3]
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute(
            "select session_id, accumulated_text, draft from parse_sessions where session_id=?",
            (session_id,),
        ).fetchall()
    finally:
        connection.close()
    assert len(rows) == 1, "parse_sessions 应仅有 1 行，实际 %d" % len(rows)
    draft = json.loads(rows[0][2]) if isinstance(rows[0][2], str) else rows[0][2]
    assert draft["location"] == "教四", draft
    print("parse_sessions: rows=1 accumulated=%r draft.location=%s"
          % (rows[0][1], draft["location"]))

elif case == "kb":
    body = load(path)
    print("kb response:", json.dumps(body, ensure_ascii=False))
    data = body["data"]
    items = data["items"]
    assert data["threshold"] == 0.6, data["threshold"]
    assert items, "items 不能为空"
    assert len(items) <= 3, len(items)
    similarities = [item["similarity"] for item in items]
    assert similarities == sorted(similarities, reverse=True), similarities
    assert items[0]["similarity"] >= 0.6, similarities
    for item in items:
        assert set(item.keys()) == {"task_id", "title", "summary", "similarity", "created_at"}, item
        assert item["similarity"] >= 0.6, item
    print("kb/similar: threshold=%s items=%d similarities=%s top1_title=%s"
          % (data["threshold"], len(items), similarities, items[0]["title"]))

elif case == "code4001":
    body = load(path)
    assert body["code"] == 4001, body
    print("4001: msg=%s" % body["msg"])

else:
    raise SystemExit("unknown case: %s" % case)
PY

# 请求体（UTF-8 文件，避免命令行编码问题）
cat > "${TMP_DIR}/req_extract.json" <<'JSON'
{"text":"下周三下午在操场办秋之韵，需要3个搬桌椅的2个摄影的，奖励20积分，措辞严谨一点"}
JSON
cat > "${TMP_DIR}/req_correction.json" <<'JSON'
{"text":"帮我发个任务，明天下午两点，地点教三，5个人搬桌椅，哎不对是教四"}
JSON
cat > "${TMP_DIR}/req_review.json" <<'JSON'
{"draft":{"title":"秋之韵志愿招募","time":"下午","location":"操场","details":"在操场搬桌椅","quota":3,"extra_tags":{"工作内容":"搬桌椅"},"style_prompt":"措辞严谨一点"}}
JSON
cat > "${TMP_DIR}/req_stream1.json" <<'JSON'
{"session_id":"smoke-stream-1","chunk":"明天下午两点，地点教三，","is_final":false}
JSON
cat > "${TMP_DIR}/req_stream2.json" <<'JSON'
{"session_id":"smoke-stream-1","chunk":"哎不对是教四。","is_final":true}
JSON

AUTH=(-H "Authorization: Bearer ${TOKEN}")
JSON_HEADER=(-H "Content-Type: application/json")

# ---------------------------------------------------------------------------
# 5) 未带 token：三接口必须 401
# ---------------------------------------------------------------------------
for endpoint in "agent/extract" "agent/review" "agent/stream/parse"; do
  case "${endpoint}" in
    agent/extract) body="${TMP_DIR}/req_extract.json" ;;
    agent/review) body="${TMP_DIR}/req_review.json" ;;
    *) body="${TMP_DIR}/req_stream1.json" ;;
  esac
  http_code="$(curl -s -o /dev/null -w "%{http_code}" -X POST "${BASE}/api/${endpoint}" \
    "${JSON_HEADER[@]}" --data-binary @"${body}")"
  [ "${http_code}" = "401" ] || fail "未带 token 访问 ${endpoint} 期望 401，实际 ${http_code}"
  pass "未带 token -> 401（${endpoint}）"
done

# ---------------------------------------------------------------------------
# 6) 参数校验：空文本 / 超长文本 / 空 session_id -> 4001（plan 2.2.7）
# ---------------------------------------------------------------------------
cat > "${TMP_DIR}/req_empty.json" <<'JSON'
{"text":""}
JSON
"$PY" -c 'import json, sys; open(sys.argv[1], "w", encoding="utf-8").write(json.dumps({"text": "任" * 4001}, ensure_ascii=False))' \
  "${TMP_DIR}/req_long.json"
cat > "${TMP_DIR}/req_stream_empty.json" <<'JSON'
{"session_id":"","chunk":"x","is_final":false}
JSON

for case_name in "extract_empty:agent/extract:req_empty.json" \
                 "extract_long:agent/extract:req_long.json" \
                 "stream_empty:agent/stream/parse:req_stream_empty.json"; do
  IFS=':' read -r label endpoint request_file <<< "${case_name}"
  curl -sS -X POST "${BASE}/api/${endpoint}" "${AUTH[@]}" "${JSON_HEADER[@]}" \
    --data-binary @"${TMP_DIR}/${request_file}" -o "${TMP_DIR}/res_${label}.json"
  "$PY" "${TMP_DIR}/checks.py" code4001 "${TMP_DIR}/res_${label}.json"
  pass "参数校验 -> 4001（${label}）"
done

# ---------------------------------------------------------------------------
# 7) extract（秋之韵文案 / 教三 -> 教四）
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE}/api/agent/extract" "${AUTH[@]}" "${JSON_HEADER[@]}" \
  --data-binary @"${TMP_DIR}/req_extract.json" -o "${TMP_DIR}/res_extract.json"
"$PY" "${TMP_DIR}/checks.py" extract "${TMP_DIR}/res_extract.json"
pass "POST /api/agent/extract"

curl -sS -X POST "${BASE}/api/agent/extract" "${AUTH[@]}" "${JSON_HEADER[@]}" \
  --data-binary @"${TMP_DIR}/req_correction.json" -o "${TMP_DIR}/res_correction.json"
"$PY" "${TMP_DIR}/checks.py" correction "${TMP_DIR}/res_correction.json"
pass "POST /api/agent/extract（教三 -> 教四）"

# ---------------------------------------------------------------------------
# 8) review
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE}/api/agent/review" "${AUTH[@]}" "${JSON_HEADER[@]}" \
  --data-binary @"${TMP_DIR}/req_review.json" -o "${TMP_DIR}/res_review.json"
"$PY" "${TMP_DIR}/checks.py" review "${TMP_DIR}/res_review.json"
pass "POST /api/agent/review"

# ---------------------------------------------------------------------------
# 9) stream/parse：连发两片
# ---------------------------------------------------------------------------
curl -sS -X POST "${BASE}/api/agent/stream/parse" "${AUTH[@]}" "${JSON_HEADER[@]}" \
  --data-binary @"${TMP_DIR}/req_stream1.json" -o "${TMP_DIR}/res_stream1.json"
"$PY" "${TMP_DIR}/checks.py" stream1 "${TMP_DIR}/res_stream1.json"

curl -sS -X POST "${BASE}/api/agent/stream/parse" "${AUTH[@]}" "${JSON_HEADER[@]}" \
  --data-binary @"${TMP_DIR}/req_stream2.json" -o "${TMP_DIR}/res_stream2.json"
"$PY" "${TMP_DIR}/checks.py" stream2 "${TMP_DIR}/res_stream2.json"
pass "POST /api/agent/stream/parse（两片合并）"

"$PY" "${TMP_DIR}/checks.py" session_rows "${DB}" "${SESSION_ID}"
pass "parse_sessions 仅 1 行（session_id=${SESSION_ID}）"

# ---------------------------------------------------------------------------
# 10) kb/similar
# ---------------------------------------------------------------------------
# q=秋之韵 的预编码形式（避免 Windows 上 curl 传中文参数的编码差异）
Q_YUE="%E7%A7%8B%E4%B9%8B%E9%9F%B5"
echo "--- kb scoring (from server.log) ---"
grep "KB-scoring" "${TMP_DIR}/server.log" || true

curl -sS "${BASE}/api/kb/similar?q=${Q_YUE}" "${AUTH[@]}" -o "${TMP_DIR}/res_kb.json"
"$PY" "${TMP_DIR}/checks.py" kb "${TMP_DIR}/res_kb.json"
pass "GET /api/kb/similar"

http_code="$(curl -s -o /dev/null -w "%{http_code}" "${BASE}/api/kb/similar?q=${Q_YUE}")"
[ "${http_code}" = "401" ] || fail "未带 token 访问 kb/similar 期望 401，实际 ${http_code}"
pass "未带 token -> 401（kb/similar）"

# ---------------------------------------------------------------------------
# 11) 知识库打分过程（取自启动日志）
# ---------------------------------------------------------------------------
echo "--- kb scoring (from server.log) ---"
grep "KB-scoring" "${TMP_DIR}/server.log" || true

echo
echo "ALL SMOKE CHECKS PASSED (port=${PORT}, db in temp dir)"