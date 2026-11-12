#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# T2 后端核心 REST 全流程回归脚本（契约 C-AUTH@1 / C-TASKS@1 / C-NOTIFY@1）
#
# 覆盖：登录建号 → 发布（含 extras/reminder_rule）→ 列表过滤 → 详情 → 认领
#       → 进度 → 提交 → 验收加分 → 积分/流水对账 → 签到 → 通知与已读 → SSE
#       以及错误码用例（4001 / 4010 / 4020 / 4030 / 4040 / 4090）。
#
# 用法（先启动后端；脚本本身可重复执行，每次发布新任务，不依赖历史数据）：
#   DATABASE_PATH=/tmp/t2.db MAAS_MOCK=1 RUN_SCHEDULER=0 \
#     .venv/Scripts/python.exe -m uvicorn app.main:app --port 8002 &
#   BASE_URL=http://127.0.0.1:8002 bash scripts/smoke_core.sh
#
# 退出码：0 = 全部用例通过；1 = 存在失败用例。
# ---------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PY="${PY:-$BACKEND_DIR/.venv/Scripts/python.exe}"
if [ ! -x "$PY" ]; then
  PY="python"
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:8002}"
export BASE_URL

cd "$BACKEND_DIR"

echo "== smoke_core: BASE_URL=$BASE_URL PY=$PY =="
"$PY" - <<'PY'
"""T2 全流程回归断言（内嵌于 smoke_core.sh，避免依赖 curl / jq）。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

try:  # Windows 终端编码兜底
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8002").rstrip("/")
FAILURES: list[str] = []
PASSED = 0


def check(name: str, condition: bool, detail: object = "") -> None:
    """记录一条断言结果。"""
    global PASSED
    if condition:
        PASSED += 1
        print(f"[PASS] {name}")
    else:
        FAILURES.append(name)
        print(f"[FAIL] {name} -> {detail}")


def call(method: str, path: str, body: object = None, token: str | None = None):
    """发起一次 HTTP 请求，返回 (http_status, json_body)。"""
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}


def login(username: str):
    """登录并返回 (token, user)。"""
    status, body = call("POST", "/api/auth/login", {"username": username})
    check(f"登录 {username} 成功", status == 200 and body.get("code") == 0, body)
    data = body.get("data") or {}
    return data.get("token"), data.get("user") or {}


def credits_snapshot(token: str):
    """取积分基线 (余额, 流水条数)，使脚本可重复执行。"""
    _, body = call("GET", "/api/credits/me", None, token)
    data = body.get("data") or {}
    return int(data.get("credits") or 0), len(data.get("logs") or [])


# --------------------------------------------------------------------------- #
# 0. 健康检查（不鉴权）
# --------------------------------------------------------------------------- #
status, body = call("GET", "/api/health")
check("GET /api/health 返回 200 且 code=0", status == 200 and body.get("code") == 0, body)
check(
    "health.tables 含 8 张表",
    len((body.get("data") or {}).get("tables") or []) == 8,
    body.get("data"),
)

# --------------------------------------------------------------------------- #
# 1. 登录建号（首登自动创建，角色规则）
# --------------------------------------------------------------------------- #
teacher_token, teacher = login("teacher01")
student_token, student = login("student01")
student2_token, student2 = login("student02")

check("teacher01 角色为 publisher", teacher.get("role") == "publisher", teacher)
check("teacher01 展示名为王老师", teacher.get("display_name") == "王老师", teacher)
check("student01 角色为 student", student.get("role") == "student", student)
check("student01 展示名为李同学", student.get("display_name") == "李同学", student)

# 积分基线（脚本可重复执行：断言一律用相对增量）
student_base_credits, student_base_logs = credits_snapshot(student_token)
student2_base_credits, student2_base_logs = credits_snapshot(student2_token)

status, body = call("GET", "/api/auth/me", None, student_token)
check("GET /api/auth/me 返回当前用户", status == 200 and (body.get("data") or {}).get("id") == student.get("id"), body)

# --------------------------------------------------------------------------- #
# 2. 未登录 → HTTP 401 + code=4010（唯一 401 例外之外的接口）
# --------------------------------------------------------------------------- #
status, body = call("GET", "/api/tasks")
check("无 token 访问 /api/tasks → HTTP 401 + code 4010", status == 401 and body.get("code") == 4010, (status, body))

status, body = call("GET", "/api/tasks", None, "invalid-token")
check("无效 token → HTTP 401 + code 4010", status == 401 and body.get("code") == 4010, (status, body))

# --------------------------------------------------------------------------- #
# 3. 发布任务（含 extras / reminder_rule）
# --------------------------------------------------------------------------- #
suffix = uuid.uuid4().hex[:8]
main_task_body = {
    "title": f"秋之韵志愿招募-{suffix}",
    "description": "布置晚会场地，搬桌椅与摄影",
    "location": "教四",
    "start_time": "2026-11-12 14:00:00",
    "deadline": "2026-11-20 18:00:00",
    "quota": 5,
    "volunteer_hours": 3.5,
    "claim_type": "open",
    "sop_guide": "1. 集合签到\n2. 搬桌椅\n3. 收尾清场",
    "style_note": "措辞严谨一点",
    "extras": {"工作内容": "搬桌椅", "联系人": "王老师"},
    "reminder_rule": {"days_before": 2, "day_of": True, "on_overdue": True},
    "credit_reward": 20,
}
status, body = call("POST", "/api/tasks", main_task_body, teacher_token)
check("发布任务成功", status == 200 and body.get("code") == 0, body)
main_task = body.get("data") or {}
main_task_id = main_task.get("id")
check("发布后状态为 published", main_task.get("status") == "published", main_task.get("status"))
check("publisher_id 取当前用户", main_task.get("publisher_id") == teacher.get("id"), main_task)
check("extras 原样落库", (main_task.get("extras") or {}).get("工作内容") == "搬桌椅", main_task.get("extras"))
check(
    "reminder_rule 原样落库",
    (main_task.get("reminder_rule") or {}).get("days_before") == 2,
    main_task.get("reminder_rule"),
)
check("sop_guide 落库", "搬桌椅" in (main_task.get("sop_guide") or ""), main_task.get("sop_guide"))

# 子任务：同批依赖 + 4020 用例
status, body = call(
    "POST",
    "/api/tasks",
    {"parent_id": main_task_id, "title": f"布置场地-{suffix}", "quota": 2, "credit_reward": 10},
    teacher_token,
)
sub1 = body.get("data") or {}
sub1_id = sub1.get("id")
check("发布子任务 1 成功", status == 200 and bool(sub1_id), body)

status, body = call(
    "POST",
    "/api/tasks",
    {
        "parent_id": main_task_id,
        "title": f"收尾清场-{suffix}",
        "quota": 2,
        "depends_on": sub1_id,
        "credit_reward": 10,
    },
    teacher_token,
)
sub2 = body.get("data") or {}
sub2_id = sub2.get("id")
check("发布子任务 2（依赖子任务 1）成功", status == 200 and bool(sub2_id), body)

status, body = call("POST", f"/api/tasks/{sub2_id}/claim", None, student_token)
check("前置依赖未完成认领 → 4020", status == 200 and body.get("code") == 4020, (status, body))

# 依赖必须是同一父任务 → 4001
# 这里发布一条 parent_id=main_task_id 的子任务，却依赖 parent_id=None 的顶层主任务
status, body = call(
    "POST",
    "/api/tasks",
    {"parent_id": main_task_id, "title": f"非法依赖-{suffix}", "depends_on": main_task_id},
    teacher_token,
)
check("依赖任务不同父任务 → 4001", status == 200 and body.get("code") == 4001, (status, body))

# 空白标题 → 4001
status, body = call("POST", "/api/tasks", {"title": "   "}, teacher_token)
check("空白标题发布 → 4001", status == 200 and body.get("code") == 4001, (status, body))

# quota < 1 → 4001
status, body = call("POST", "/api/tasks", {"title": f"人数非法-{suffix}", "quota": 0}, teacher_token)
check("quota < 1 → 4001", status == 200 and body.get("code") == 4001, (status, body))

# --------------------------------------------------------------------------- #
# 4. 列表过滤（status / scope / include_sub）与 is_claimable
# --------------------------------------------------------------------------- #
status, body = call("GET", "/api/tasks?status=published&scope=all", None, student_token)
items = (body.get("data") or {}).get("items") or []
main_item = next((item for item in items if item.get("id") == main_task_id), None)
check("列表按 status 过滤命中主任务", status == 200 and main_item is not None, body.get("code"))
check("学生视角主任务 is_claimable=True", bool(main_item and main_item.get("is_claimable")), main_item)
check(
    "include_sub 默认 false 只返回主任务",
    all(item.get("parent_id") is None for item in items),
    [item.get("parent_id") for item in items],
)

status, body = call("GET", "/api/tasks?include_sub=true&scope=all", None, student_token)
all_ids = {item.get("id") for item in (body.get("data") or {}).get("items") or []}
check("include_sub=true 返回子任务", {sub1_id, sub2_id}.issubset(all_ids), sorted(all_ids))

status, body = call("GET", f"/api/tasks?status=published,in_progress&scope=all", None, student_token)
check("逗号分隔 status 按 IN 处理", status == 200 and body.get("code") == 0, body.get("code"))

# 发布者视角：自己的任务不可认领
status, body = call("GET", f"/api/tasks?status=published", None, teacher_token)
teacher_item = next((i for i in (body.get("data") or {}).get("items") or [] if i.get("id") == main_task_id), None)
check("发布者视角自己任务 is_claimable=False", bool(teacher_item) and not teacher_item.get("is_claimable"), teacher_item)

# 详情：children + progress + sop_guide
status, body = call("GET", f"/api/tasks/{main_task_id}", None, student_token)
detail = body.get("data") or {}
check("详情返回 children 2 条", len(detail.get("children") or []) == 2, detail.get("children"))
check("详情含 sop_guide", "搬桌椅" in (detail.get("sop_guide") or ""), detail.get("sop_guide"))
check("详情 progress 初始为空", detail.get("progress") == [], detail.get("progress"))
check("详情含发布者名称", detail.get("publisher_name") == "王老师", detail.get("publisher_name"))

status, body = call("GET", "/api/tasks/99999999", None, student_token)
check("不存在的任务 → 4040", status == 200 and body.get("code") == 4040, (status, body))

# --------------------------------------------------------------------------- #
# 5. 认领 / 进度 / 提交 / 验收
# --------------------------------------------------------------------------- #
status, body = call("POST", f"/api/tasks/{main_task_id}/claim", None, teacher_token)
check("发布者认领自己的任务 → 4030", status == 200 and body.get("code") == 4030, (status, body))

status, body = call("POST", "/api/tasks/99999999/claim", None, student_token)
check("认领不存在的任务 → 4040", status == 200 and body.get("code") == 4040, (status, body))

status, body = call("POST", f"/api/tasks/{main_task_id}/claim", None, student_token)
claimed = body.get("data") or {}
check("学生认领成功", status == 200 and body.get("code") == 0, body)
check("认领后 assignee 与状态正确", claimed.get("assignee_id") == student.get("id") and claimed.get("status") == "claimed", claimed)

status, body = call("POST", f"/api/tasks/{main_task_id}/claim", None, student2_token)
check("重复认领 → 4090", status == 200 and body.get("code") == 4090, (status, body))

status, body = call("POST", f"/api/tasks/{main_task_id}/progress", {"content": "已搬运一半桌椅"}, student_token)
check("负责人提交进度成功", status == 200 and body.get("code") == 0, body)
check("进度记录含 user_name", (body.get("data") or {}).get("user_name") == "李同学", body.get("data"))

status, body = call("POST", f"/api/tasks/{main_task_id}/progress", {"content": "非负责人写进度"}, student2_token)
check("非负责人提交进度 → 4030", status == 200 and body.get("code") == 4030, (status, body))

status, body = call("GET", f"/api/tasks/{main_task_id}", None, teacher_token)
check("首次进度提交自动推进为 in_progress", (body.get("data") or {}).get("status") == "in_progress", body.get("data"))

status, body = call("POST", f"/api/tasks/{main_task_id}/submit", None, student_token)
check("提交完成成功", status == 200 and (body.get("data") or {}).get("status") == "submitted", body)

status, body = call("POST", f"/api/tasks/{main_task_id}/submit", None, student_token)
check("重复提交（非法流转）→ 4090", status == 200 and body.get("code") == 4090, (status, body))

status, body = call("POST", f"/api/tasks/{main_task_id}/verify", {"pass": True}, student_token)
check("非发布者验收 → 4030", status == 200 and body.get("code") == 4030, (status, body))

status, body = call("POST", f"/api/tasks/{main_task_id}/verify", {"pass": True}, teacher_token)
verified = body.get("data") or {}
check("发布者验收通过", status == 200 and body.get("code") == 0, body)
check("credit_delta == 20", verified.get("credit_delta") == 20, verified.get("credit_delta"))
check("验收后状态 verified", (verified.get("task") or {}).get("status") == "verified", verified.get("task"))

status, body = call("POST", f"/api/tasks/{main_task_id}/verify", {"pass": True}, teacher_token)
check("重复验收幂等：credit_delta == 0", status == 200 and body.get("code") == 0 and (body.get("data") or {}).get("credit_delta") == 0, body)

status, body = call("POST", f"/api/tasks/{sub1_id}/verify", {"pass": True}, teacher_token)
check("published 任务直接验收（非法流转）→ 4090", status == 200 and body.get("code") == 4090, (status, body))

# --------------------------------------------------------------------------- #
# 6. 积分：余额 == 流水之和
# --------------------------------------------------------------------------- #
status, body = call("GET", "/api/credits/me", None, student_token)
credits_me = body.get("data") or {}
logs = credits_me.get("logs") or []
delta_sum = sum(int(log.get("delta") or 0) for log in logs)
check(
    "积分余额相对基线 +20",
    int(credits_me.get("credits") or 0) == student_base_credits + 20,
    (credits_me.get("credits"), student_base_credits),
)
check("积分流水相对基线 +1 条", len(logs) == student_base_logs + 1, (len(logs), student_base_logs))
check("余额等于流水之和", int(credits_me.get("credits") or 0) == delta_sum, (credits_me.get("credits"), delta_sum))
check(
    "流水原因以「任务完成奖励」开头",
    bool(logs) and str(logs[0].get("reason", "")).startswith("任务完成奖励"),
    logs[0] if logs else None,
)

# --------------------------------------------------------------------------- #
# 7. 签到（每人每任务一次）
# --------------------------------------------------------------------------- #
status, body = call("POST", "/api/checkin", {"task_id": main_task_id}, student_token)
check("首次签到成功", status == 200 and body.get("code") == 0, body)
check("签到含 task_title", bool((body.get("data") or {}).get("task_title")), body.get("data"))

status, body = call("POST", "/api/checkin", {"task_id": main_task_id}, student_token)
check("重复签到 → 4090", status == 200 and body.get("code") == 4090, (status, body))

status, body = call("POST", "/api/checkin", {"task_id": main_task_id}, student2_token)
check("非负责人签到 → 4030", status == 200 and body.get("code") == 4030, (status, body))

status, body = call("POST", "/api/checkin", {"task_id": 99999999}, student_token)
check("签到不存在的任务 → 4040", status == 200 and body.get("code") == 4040, (status, body))

status, body = call("GET", "/api/checkin/me", None, student_token)
checkins = (body.get("data") or {}).get("items") or []
check("我的签到记录 >= 1 且含 task_title", len(checkins) >= 1 and bool(checkins[0].get("task_title")), checkins)

# --------------------------------------------------------------------------- #
# 8. 通知：列表 / 未读 / 标记已读
# --------------------------------------------------------------------------- #
status, body = call("GET", "/api/notifications", None, student_token)
student_notifications = body.get("data") or {}
student_items = student_notifications.get("items") or []
check("学生通知 >= 2 条", len(student_items) >= 2, len(student_items))
check("学生未读数 >= 2", int(student_notifications.get("unread") or 0) >= 2, student_notifications.get("unread"))
check(
    "通知含「认领成功」与「验收通过」",
    {"认领成功", "验收通过，积分到账"}.issubset({item.get("title") for item in student_items}),
    [item.get("title") for item in student_items],
)
check(
    "通知字段完整（id/user_id/level/is_read/created_at）",
    all(
        item.get("id") is not None
        and item.get("user_id") == student.get("id")
        and item.get("level")
        and item.get("is_read") in (0, 1)
        and item.get("created_at")
        for item in student_items
    ),
    student_items[:1],
)

status, body = call("GET", "/api/notifications?unread_only=true&limit=10", None, teacher_token)
teacher_notifications = body.get("data") or {}
check("教师未读通知 >= 3（认领/提交/验收/签到）", int(teacher_notifications.get("unread") or 0) >= 3, teacher_notifications.get("unread"))

read_ids = [item.get("id") for item in student_items]
status, body = call("POST", "/api/notifications/read", {"ids": read_ids}, student_token)
check("标记已读返回 updated>=1", status == 200 and int((body.get("data") or {}).get("updated") or 0) >= 1, body)

status, body = call("GET", "/api/notifications", None, student_token)
check("标记已读后 unread 归零", int((body.get("data") or {}).get("unread") or 0) == 0, body.get("data"))

status, body = call("POST", "/api/notifications/read", {"ids": []}, student_token)
check("空 ids 标记已读 → updated=0", status == 200 and (body.get("data") or {}).get("updated") == 0, body)

# 他人的通知不能被标记
status, body = call(
    "POST",
    "/api/notifications/read",
    {"ids": [item.get("id") for item in (teacher_notifications.get("items") or [])]},
    student_token,
)
check("标记他人通知 → updated=0（越权静默忽略）", status == 200 and (body.get("data") or {}).get("updated") == 0, body)

# --------------------------------------------------------------------------- #
# 9. 验收驳回分支
# --------------------------------------------------------------------------- #
status, body = call("POST", f"/api/tasks/{sub1_id}/claim", None, student2_token)
check("student02 认领子任务 1", status == 200 and body.get("code") == 0, body)
call("POST", f"/api/tasks/{sub1_id}/progress", {"content": "已布置一半"}, student2_token)
call("POST", f"/api/tasks/{sub1_id}/submit", None, student2_token)

status, body = call(
    "POST",
    f"/api/tasks/{sub1_id}/verify",
    {"pass": False, "reason": "桌椅摆放不整齐"},
    teacher_token,
)
check("验收驳回成功", status == 200 and (body.get("data") or {}).get("credit_delta") == 0, body)
check("驳回后状态回到 in_progress", (body.get("data") or {}).get("task", {}).get("status") == "in_progress", body.get("data"))

status, body = call("GET", "/api/notifications?unread_only=true", None, student2_token)
warning_titles = {item.get("title") for item in (body.get("data") or {}).get("items") or []}
check("驳回后负责人收到「验收未通过」warning", "验收未通过" in warning_titles, warning_titles)

status, body = call("GET", "/api/credits/me", None, student2_token)
student2_credits = body.get("data") or {}
check(
    "驳回不加分（余额与流水均停在基线）",
    int(student2_credits.get("credits") or 0) == student2_base_credits
    and len(student2_credits.get("logs") or []) == student2_base_logs,
    student2_credits,
)

# 前置依赖已 completed 才能认领：sub1 仍未 verified，sub2 依然 4020
status, body = call("POST", f"/api/tasks/{sub2_id}/claim", None, student_token)
check("依赖仍未完成时认领 sub2 → 4020", status == 200 and body.get("code") == 4020, body)

# --------------------------------------------------------------------------- #
# 10. PATCH 语义：省略不修改 / extras={} 清空 / extras=null 不修改
# --------------------------------------------------------------------------- #
status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"title": f"收尾清场-改名-{suffix}"}, teacher_token)
patched = body.get("data") or {}
check("PATCH 标题成功", status == 200 and str(patched.get("title", "")).startswith("收尾清场-改名"), patched.get("title"))
check("PATCH 省略 extras 不修改", (patched.get("extras") or {}) == {}, patched.get("extras"))

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"extras": {"备注": "临时"}}, teacher_token)
check("PATCH 写入 extras", (body.get("data") or {}).get("extras") == {"备注": "临时"}, (body.get("data") or {}).get("extras"))

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"extras": {}}, teacher_token)
check("PATCH extras={} 清空对象", (body.get("data") or {}).get("extras") == {}, (body.get("data") or {}).get("extras"))

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"extras": None, "deadline": None}, teacher_token)
check("PATCH extras=null 视为不修改", (body.get("data") or {}).get("extras") == {}, (body.get("data") or {}).get("extras"))
check("PATCH deadline=null 清空该列", (body.get("data") or {}).get("deadline") is None, (body.get("data") or {}).get("deadline"))

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"title": ""}, teacher_token)
check("PATCH 空标题 → 4001", status == 200 and body.get("code") == 4001, (status, body))

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"title": "越权改名"}, student_token)
check("非发布者 PATCH → 4030", status == 200 and body.get("code") == 4030, (status, body))

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"status": "cancelled"}, teacher_token)
check("PATCH 取消任务成功", status == 200 and (body.get("data") or {}).get("status") == "cancelled", body)

status, body = call("PATCH", f"/api/tasks/{sub2_id}", {"status": "cancelled"}, teacher_token)
check("终态再次取消 → 4090", status == 200 and body.get("code") == 4090, (status, body))

status, body = call("PATCH", "/api/tasks/99999999", {"title": "x"}, teacher_token)
check("PATCH 不存在的任务 → 4040", status == 200 and body.get("code") == 4040, (status, body))

# --------------------------------------------------------------------------- #
# 11. 指派 + 拆分建议（decompose 依赖 T3，T3 未就绪时应给出 5001 而非崩溃）
# --------------------------------------------------------------------------- #
status, body = call(
    "POST",
    "/api/tasks",
    {"title": f"指派任务-{suffix}", "claim_type": "open", "deadline": "2026-12-01 12:00:00"},
    teacher_token,
)
assign_target_id = (body.get("data") or {}).get("id")
status, body = call("POST", f"/api/tasks/{assign_target_id}/assign", {"user_id": student.get("id")}, teacher_token)
assigned = body.get("data") or {}
check("指派成功并置 claimed", status == 200 and assigned.get("status") == "claimed" and assigned.get("assignee_id") == student.get("id"), assigned)
check("指派后 claim_type=assign", assigned.get("claim_type") == "assign", assigned.get("claim_type"))

status, body = call("POST", f"/api/tasks/{assign_target_id}/assign", {"user_id": 99999999}, teacher_token)
check("指派不存在的用户 → 4040", status == 200 and body.get("code") == 4040, (status, body))

status, body = call("POST", f"/api/tasks/{main_task_id}/decompose", None, teacher_token)
check(
    "decompose 正常返回或明确 5001（T3 未就绪时）",
    status == 200 and (body.get("code") == 0 or body.get("code") in (5001, 5002, 5003)),
    (status, body),
)
if body.get("code") == 0:
    decompose_data = body.get("data") or {}
    check("decompose 返回 mock 标记且不落库", isinstance(decompose_data.get("mock"), bool), decompose_data)

status, body = call("POST", f"/api/tasks/{main_task_id}/decompose", None, student_token)
check("非发布者 decompose → 4030", status == 200 and body.get("code") == 4030, (status, body))

# --------------------------------------------------------------------------- #
# 12. SSE：token 查询参数鉴权 + 事件流首帧
# --------------------------------------------------------------------------- #
def probe_sse(token: str | None):
    """读取 SSE 首帧后立即断开，返回 (http_status, content_type, first_line)。"""
    query = f"?token={urllib.parse.quote(token)}" if token else ""
    request = urllib.request.Request(
        BASE + "/api/notifications/stream" + query,
        headers={"Accept": "text/event-stream", "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.headers.get("Content-Type", ""), response.readline().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # 网络/超时
        return None, "", str(exc)


sse_status, sse_type, sse_first = probe_sse(student_token)
check("SSE 连接返回 200 + text/event-stream", sse_status == 200 and "text/event-stream" in (sse_type or ""), (sse_status, sse_type, sse_first))
check("SSE 首帧为心跳注释行", sse_first.startswith(": ping"), repr(sse_first))

sse_status, sse_type, sse_first = probe_sse(None)
check("SSE 无 token → HTTP 401 + code 4010", sse_status == 401 and ":4010" in (sse_first or ""), (sse_status, sse_first))

sse_status, sse_type, sse_first = probe_sse("bad-token")
check("SSE 无效 token → HTTP 401 + code 4010", sse_status == 401 and ":4010" in (sse_first or ""), (sse_status, sse_first))

# --------------------------------------------------------------------------- #
# 汇总
# --------------------------------------------------------------------------- #
print("")
print(f"== smoke_core 结果：通过 {PASSED} 项，失败 {len(FAILURES)} 项 ==")
if FAILURES:
    for name in FAILURES:
        print(f"  - FAILED: {name}")
    sys.exit(1)
print("== smoke_core 全部用例通过 ==")
PY

echo "== smoke_core done =="