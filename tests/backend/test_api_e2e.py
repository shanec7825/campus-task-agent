#!/usr/bin/env python
"""T8-② REST 全流程 E2E 与错误码矩阵（契约 `C-AUTH@1` / `C-TASKS@1` / `C-APPLY@1` / `C-NOTIFY@1`）。

**P2：claim 语义变更（第二轮迭代 D1 作废）**
``POST /api/tasks/{id}/claim`` 仍是可调用别名，但语义已等同「报名」：
返回 ``ApplyOut``（``application.status="pending"`` + 最新 ``task``），**不再**直接置
``claimed``、不再写 ``assignee_id``。原 P1 的「认领即成为负责人」断言全部改写为
``apply → pending → 发布者 decide approve → claimed``。

覆盖（plan T8 `acceptance_and_local_checks` ③ + P1 全流程回归）：
1. 两个角色登录（teacher01 / student01，另有 student02 用于权限校验）；
2. 发布任务（含 ``extras`` / ``reminder_rule`` / ``credit_reward``）与详情回显；
3. 列表过滤：``status``（单值 / 逗号多值）、``scope=all|mine``、``include_sub``、
   排序 ``created_at DESC, id DESC``、派生字段 ``is_claimable`` / 4 个报名字段；
4. 报名（claim 别名）→ ``pending`` → 重复报名 4090 → 发布者审批 → ``claimed``
   → 进度（状态推进 + progress_logs）→ 提交 → 验收通过；
5. 验收通过后：余额 +20、流水 1 条、``credit_delta``/``credited_user_ids`` 正确、
   成员通知 ≥2 条、重复验收 4090（已 verified）且不新增流水；
6. 签到两次（第二次 4090）、非成员签到 4030、``checkin/me``；
7. ``credits/me`` 余额 == 流水之和；
8. 错误码矩阵：4010（无 token / 无效 token）、4030（发布者报名自己任务 / 非发布者修改 /
   验收 / 指派）、4020（前置依赖未完成）、4090（非法流转 / 重复报名 / 终态报名 / 终态取消）、
   4001（参数校验）、4040（指派不存在用户）；
9. 指派（assign）语义与通知、PATCH 的「显式 null 清空」语义、``/decompose``（mock）。

所有断言同时校验**响应体 code 与 data 结构**，不只看 HTTP 200。
运行前提：``T10_BASE_URL`` 指向 ``run_all.sh`` 启动的 8021 后端（临时库 + MAAS_MOCK=1）。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.getenv("T10_BASE_URL", "http://127.0.0.1:8010").rstrip("/")

# 任务标题：全部带 "T10 E2E" 前缀，便于在日志中定位
TITLE_MAIN = "T10 E2E 秋之韵保障任务"
TITLE_SELF_CLAIM = "T10 E2E 发布者自认领任务"
TITLE_DEP_PARENT = "T10 E2E 依赖父任务"
TITLE_DEP_FIRST = "T10 E2E 子任务一（布置场地）"
TITLE_DEP_SECOND = "T10 E2E 子任务二（活动执行）"

MAIN_EXTRAS = {"装备": "矿泉水", "联系人": "张三"}
MAIN_RULE = {"days_before": 2, "day_of": False, "on_overdue": True}

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
    """断言 ``HTTP 200 + code==0``，返回 ``data``。"""
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
    """断言错误响应：``code`` 与 HTTP 状态双校验，返回完整响应体。"""
    status, payload = http_json(method, path, body, token)
    expect(
        payload.get("code") == code,
        f"{label}：期望 code={code}，实际 HTTP {status} + code={payload.get('code')}（msg={payload.get('msg')}）",
    )
    expect(status == expected_status, f"{label}：期望 HTTP {expected_status}，实际 HTTP {status}")
    return payload


def login(username: str) -> tuple[str, dict]:
    data = api_ok("POST", "/api/auth/login", {"username": username}, label=f"登录 {username}")
    token = data.get("token")
    expect(isinstance(token, str) and bool(token), f"{username} 返回非空 token")
    user = data.get("user")
    expect(isinstance(user, dict) and user.get("username") == username, f"{username} 返回 user 对象")
    return token, user


def list_tasks(token: str, label: str = "", **params: object) -> list[dict]:
    query = "?" + urllib.parse.urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()}) if params else ""
    data = api_ok("GET", "/api/tasks" + query, token=token, label=label or f"任务列表 {params}")
    items = data.get("items")
    expect(isinstance(items, list), f"{label or '任务列表'}：items 为数组（实际 {type(items).__name__}）")
    return items


def find_task(items: list[dict], task_id: int) -> dict:
    for item in items:
        if item.get("id") == task_id:
            return item
    expect(False, f"列表中找到任务 id={task_id}（实际 ids={[i.get('id') for i in items]}）")
    return {}


def notifications(token: str, label: str = "") -> dict:
    data = api_ok("GET", "/api/notifications?limit=200", token=token, label=label or "通知列表")
    expect(isinstance(data.get("items"), list), "通知列表：items 为数组")
    expect(isinstance(data.get("unread"), int), "通知列表：unread 为整数")
    return data


def create_task(token: str, body: dict, label: str) -> dict:
    """发布任务并返回 ``TaskOut`` 字典。"""
    data = api_ok("POST", "/api/tasks", body, token=token, label=label)
    expect(isinstance(data.get("id"), int) and data["id"] > 0, f"{label}：返回 int id")
    return data


def apply_task(token: str, task_id: int, label: str) -> dict:
    """报名（A1）并返回 ``ApplyOut``；断言报名记录为 ``pending``。"""
    data = api_ok("POST", f"/api/tasks/{task_id}/apply", token=token, label=label)
    application = data.get("application")
    expect(isinstance(application, dict), f"{label}：返回 application 对象（实际 {type(application).__name__}）")
    expect(application.get("status") == "pending", f"{label}：报名状态 pending（实际 {application.get('status')}）")
    expect(application.get("task_id") == task_id, f"{label}：application.task_id 正确（实际 {application.get('task_id')}）")
    expect(isinstance(application.get("id"), int), f"{label}：返回 int application.id（实际 {application.get('id')!r}）")
    expect(isinstance(data.get("task"), dict), f"{label}：返回最新 task（实际 {type(data.get('task')).__name__}）")
    return data


def decide_application(
    token: str,
    application_id: int,
    approve: bool,
    label: str,
    reason: str | None = None,
) -> dict:
    """审批报名（A4）并返回 ``ApplyOut``。"""
    body: dict[str, object] = {"approve": approve}
    if reason is not None:
        body["reason"] = reason
    return api_ok(
        "POST", f"/api/applications/{application_id}/decide", body, token=token, label=label
    )


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def main() -> int:
    # ---- 1) 认证与角色 ----------------------------------------------------
    teacher_token, teacher = login("teacher01")
    teacher_id = teacher.get("id")
    expect(teacher.get("role") == "publisher", f"teacher01 角色 publisher（实际 {teacher.get('role')}）")
    expect(teacher.get("display_name") == "王老师", f"teacher01 展示名 王老师（实际 {teacher.get('display_name')}）")
    expect(teacher.get("credits") == 0, f"teacher01 初始积分 0（实际 {teacher.get('credits')}）")

    student_token, student = login("student01")
    student_id = student.get("id")
    expect(student.get("role") == "student", f"student01 角色 student（实际 {student.get('role')}）")
    expect(student.get("display_name") == "李同学", f"student01 展示名 李同学（实际 {student.get('display_name')}）")

    student2_token, student2 = login("student02")
    student2_id = student2.get("id")
    expect(student2_id != student_id, "student01 与 student02 为不同用户")

    me = api_ok("GET", "/api/auth/me", token=student_token, label="auth/me")
    expect(me.get("id") == student_id, f"auth/me 返回当前用户（实际 id={me.get('id')}）")

    # 记录积分基线（后续断言相对变化，避免与其它脚本的数据耦合）
    baseline_payload = api_ok("GET", "/api/credits/me", token=student_token, label="学生积分基线")
    baseline_credits = baseline_payload.get("credits")
    baseline_logs = len(baseline_payload.get("logs") or [])
    expect(isinstance(baseline_credits, int), f"积分基线为整数（实际 {baseline_credits!r}）")

    # ---- 2) 发布任务（extras / reminder_rule / credit_reward）-------------
    main_task = create_task(
        teacher_token,
        {
            "title": TITLE_MAIN,
            "description": "负责布置场地与物资发放，需要提前到场。",
            "location": "教四",
            "start_time": "明天下午两点",
            "quota": 5,
            "volunteer_hours": 3.5,
            "extras": MAIN_EXTRAS,
            "reminder_rule": MAIN_RULE,
            "credit_reward": 20,
            "sop_guide": "1. 集合签到\n2. 搬运桌椅\n3. 清点物资",
        },
        label="发布主任务",
    )
    main_id = main_task["id"]
    expect(main_task.get("status") == "published", f"发布后状态 published（实际 {main_task.get('status')}）")
    expect(main_task.get("publisher_id") == teacher_id, f"publisher_id 为当前用户（实际 {main_task.get('publisher_id')}）")
    expect(main_task.get("claim_type") == "open", f"默认 claim_type=open（实际 {main_task.get('claim_type')}）")
    expect(
        isinstance(main_task.get("extras"), dict) and main_task["extras"] == MAIN_EXTRAS,
        f"extras 原样回显 dict（实际 {main_task.get('extras')!r}）",
    )
    expect(
        isinstance(main_task.get("reminder_rule"), dict) and main_task["reminder_rule"] == MAIN_RULE,
        f"reminder_rule 原样回显 dict（实际 {main_task.get('reminder_rule')!r}）",
    )
    expect(main_task.get("credit_reward") == 20, f"credit_reward 回显 20（实际 {main_task.get('credit_reward')}）")
    expect(main_task.get("quota") == 5 and main_task.get("volunteer_hours") == 3.5, "quota / volunteer_hours 回显正确")
    expect(main_task.get("deadline") is None, f"未提供 deadline 时回显 null（实际 {main_task.get('deadline')!r}）")

    detail = api_ok("GET", f"/api/tasks/{main_id}", token=teacher_token, label="主任务详情")
    expect(detail.get("extras") == MAIN_EXTRAS and detail.get("reminder_rule") == MAIN_RULE, "详情接口回显 extras / reminder_rule")
    expect(detail.get("children") == [], f"主任务无子任务（实际 {detail.get('children')!r}）")
    expect(detail.get("progress") == [], f"主任务无进度记录（实际 {detail.get('progress')!r}）")
    expect(detail.get("is_claimable") is False, "发布者视角 is_claimable=false（不能认领自己的任务）")

    # ---- 3) 列表过滤 ------------------------------------------------------
    published_items = list_tasks(teacher_token, label="列表(status=published)", status="published")
    expect(main_id in [i["id"] for i in published_items], "status=published 过滤包含新任务")
    verified_items = list_tasks(teacher_token, label="列表(status=verified)", status="verified")
    expect(main_id not in [i["id"] for i in verified_items], "status=verified 过滤不含未验收任务")

    multi_items = list_tasks(teacher_token, label="列表(status=published,verified)", status="published,verified")
    expect(main_id in [i["id"] for i in multi_items], "status 逗号多值按 IN 处理（含 published 任务）")

    all_items = list_tasks(teacher_token, label="列表(全量)")
    expect(isinstance(all_items, list) and all_items, "全量列表非空")
    ordering = [(item.get("created_at"), item.get("id")) for item in all_items]
    expect(ordering == sorted(ordering, reverse=True), "列表按 created_at DESC, id DESC 排序")
    expect(all(item.get("parent_id") is None for item in all_items), "include_sub 默认 false，只返回主任务")

    student_mine = list_tasks(student_token, label="列表(学生 scope=mine)", scope="mine")
    expect(main_id not in [i["id"] for i in student_mine], "scope=mine 未认领时不含该任务")
    teacher_mine = list_tasks(teacher_token, label="列表(教师 scope=mine)", scope="mine")
    expect(main_id in [i["id"] for i in teacher_mine], "scope=mine 发布者视角包含自己发布的任务")

    student_all = list_tasks(student_token, label="列表(学生全量)")
    expect(find_task(student_all, main_id).get("is_claimable") is True, "学生视角 is_claimable=true")
    expect(find_task(teacher_mine, main_id).get("is_claimable") is False, "发布者视角 is_claimable=false")

    # ---- 4) 报名 / 审批 / 进度 / 提交（P2：claim 语义变更）-----------------
    # P2：claim 不再直接认领，而是等价于 apply（返回 ApplyOut），必须由发布者审批后才 claimed。
    applied = api_ok("POST", f"/api/tasks/{main_id}/claim", token=student_token, label="claim 别名报名")
    application = applied.get("application") or {}
    expect(isinstance(application, dict) and application.get("status") == "pending",
           f"claim 别名返回 pending 报名（实际 {application.get('status')}）")
    expect(isinstance(applied.get("task"), dict), "claim 别名返回最新 task 对象")
    expect(applied["task"].get("status") == "published",
           f"报名后任务仍 published（实际 {applied['task'].get('status')}）")
    expect(applied["task"].get("assignee_id") is None,
           f"报名后 assignee_id 仍为空（实际 {applied['task'].get('assignee_id')}）")
    expect(applied["task"].get("applied_count") == 1,
           f"报名后 applied_count=1（实际 {applied['task'].get('applied_count')}）")
    expect(applied["task"].get("approved_count") == 0,
           f"报名后 approved_count=0（实际 {applied['task'].get('approved_count')}）")
    expect(applied["task"].get("my_application_status") == "pending",
           f"报名后 my_application_status=pending（实际 {applied['task'].get('my_application_status')}）")
    main_application_id = application.get("id")
    expect(isinstance(main_application_id, int), f"报名返回 int application.id（实际 {main_application_id!r}）")

    api_err("POST", f"/api/tasks/{main_id}/claim", 4090, token=student_token, label="重复报名 4090")
    api_err("POST", f"/api/tasks/{main_id}/apply", 4090, token=student_token, label="重复报名（apply）4090")

    approved = decide_application(teacher_token, main_application_id, True, "发布者通过报名")
    approved_app = approved.get("application") or {}
    approved_task = approved.get("task") or {}
    expect(approved_app.get("status") == "approved",
           f"审批后报名状态 approved（实际 {approved_app.get('status')}）")
    expect(approved_app.get("decided_at") is not None, "审批后写 decided_at")
    expect(approved_task.get("status") == "claimed",
           f"审批后任务状态 claimed（实际 {approved_task.get('status')}）")
    expect(approved_task.get("assignee_id") == student_id,
           f"审批后 assignee_id 为首位成员（实际 {approved_task.get('assignee_id')}）")
    expect(approved_task.get("assignee_name") == "李同学",
           f"审批后 assignee_name 回显 李同学（实际 {approved_task.get('assignee_name')}）")
    expect(approved_task.get("assignee_names") == ["李同学"],
           f"审批后 assignee_names=[李同学]（实际 {approved_task.get('assignee_names')}）")
    expect(approved_task.get("approved_count") == 1,
           f"审批后 approved_count=1（实际 {approved_task.get('approved_count')}）")

    after_claim = api_ok("GET", f"/api/tasks/{main_id}", token=student_token, label="报名后详情")
    expect(after_claim.get("my_application_status") == "approved",
           f"成员视角 my_application_status=approved（实际 {after_claim.get('my_application_status')}）")
    expect(after_claim.get("is_claimable") is False, "已通过成员不再可报名（is_claimable=false）")

    publisher_notify = notifications(teacher_token, "发布者通知（报名后）")
    expect(
        any(n.get("task_id") == main_id and n.get("level") == "info" for n in publisher_notify["items"]),
        "报名后发布者收到 info 通知",
    )

    progress = api_ok("POST", f"/api/tasks/{main_id}/progress", {"content": "已招募 3 名志愿者"}, token=student_token, label="提交进度")
    expect(isinstance(progress.get("id"), int), f"进度返回 int id（实际 {progress.get('id')!r}）")
    expect(progress.get("task_id") == main_id, "进度关联任务 id 正确")
    expect(progress.get("user_name") == "李同学", f"进度回显 user_name（实际 {progress.get('user_name')}）")

    after_progress = api_ok("GET", f"/api/tasks/{main_id}", token=student_token, label="进度后详情")
    expect(after_progress.get("status") == "in_progress", f"首次进度自动推进 in_progress（实际 {after_progress.get('status')}）")
    expect(len(after_progress.get("progress") or []) == 1, f"progress_logs 记录 1 条（实际 {len(after_progress.get('progress') or [])}）")
    expect(
        (after_progress.get("progress") or [{}])[0].get("content") == "已招募 3 名志愿者",
        "进度内容原样落库",
    )

    api_err(
        "POST",
        f"/api/tasks/{main_id}/progress",
        4030,
        {"content": "越权进度"},
        token=student2_token,
        label="非负责人提交进度 4030",
    )

    submitted = api_ok("POST", f"/api/tasks/{main_id}/submit", token=student_token, label="提交完成")
    expect(submitted.get("status") == "submitted", f"提交后状态 submitted（实际 {submitted.get('status')}）")

    submit_notify = notifications(teacher_token, "发布者通知（提交后）")
    expect(
        any(n.get("task_id") == main_id and "验收" in (n.get("title") or "") for n in submit_notify["items"]),
        "提交后发布者收到待验收通知",
    )

    # ---- 5) 验收通过 / 幂等 / 积分 / 通知 ---------------------------------
    verified = api_ok("POST", f"/api/tasks/{main_id}/verify", {"pass": True}, token=teacher_token, label="验收通过")
    expect(isinstance(verified.get("task"), dict), "验收返回 task 对象")
    expect(verified["task"].get("status") == "verified", f"验收后状态 verified（实际 {verified['task'].get('status')}）")
    expect(verified.get("credit_delta") == 20, f"验收加分 credit_delta=20（实际 {verified.get('credit_delta')}）")
    expect(
        verified.get("credited_user_ids") == [student_id],
        f"credited_user_ids 仅含 student01（实际 {verified.get('credited_user_ids')}）",
    )
    expect(verified["task"].get("approved_count") == 1, "验收后 approved_count 仍为 1")

    credits_after = api_ok("GET", "/api/credits/me", token=student_token, label="验收后积分")
    expect(
        credits_after.get("credits") == baseline_credits + 20,
        f"负责人余额 +20（基线 {baseline_credits} → 实际 {credits_after.get('credits')}）",
    )
    bonus_logs = [log for log in credits_after.get("logs") or [] if log.get("task_id") == main_id]
    expect(len(bonus_logs) == 1, f"本任务积分流水 1 条（实际 {len(bonus_logs)}）")
    expect(bonus_logs[0].get("delta") == 20, f"流水 delta=20（实际 {bonus_logs[0].get('delta')}）")
    expect("任务完成奖励" in (bonus_logs[0].get("reason") or ""), f"流水原因含「任务完成奖励」（实际 {bonus_logs[0].get('reason')}）")
    expect(
        len(credits_after.get("logs") or []) == baseline_logs + 1,
        f"流水总条数 +1（基线 {baseline_logs} → 实际 {len(credits_after.get('logs') or [])}）",
    )

    student_notify = notifications(student_token, "负责人通知（验收后）")
    main_notifies = [n for n in student_notify["items"] if n.get("task_id") == main_id]
    expect(len(main_notifies) >= 2, f"负责人本任务通知 ≥2 条（实际 {len(main_notifies)}）")
    expect(
        any("验收通过" in (n.get("title") or "") for n in main_notifies),
        "负责人收到验收通过通知",
    )
    expect(all(isinstance(n.get("level"), str) and n.get("level") in {"info", "warning", "urgent", "overdue"} for n in main_notifies), "通知 level 取值合法")

    # P2：任务已 verified，重复验收被状态机拒绝（T2 验收 f：4090 且不新增流水）
    api_err("POST", f"/api/tasks/{main_id}/verify", 4090, {"pass": True}, token=teacher_token, label="重复验收 4090（已 verified）")

    credits_repeat = api_ok("GET", "/api/credits/me", token=student_token, label="重复验收后积分")
    expect(credits_repeat.get("credits") == baseline_credits + 20, "重复验收不重复加分")
    expect(
        len(credits_repeat.get("logs") or []) == baseline_logs + 1,
        "重复验收不新增积分流水",
    )

    # ---- 6) 签到 ---------------------------------------------------------
    checkin = api_ok("POST", "/api/checkin", {"task_id": main_id}, token=student_token, label="签到")
    expect(isinstance(checkin.get("id"), int), "签到返回 int id")
    expect(checkin.get("task_id") == main_id, "签到 task_id 正确")
    expect(checkin.get("user_id") == student_id, "签到 user_id 为当前用户")
    expect(checkin.get("task_title") == TITLE_MAIN, f"签到回显 task_title（实际 {checkin.get('task_title')}）")
    expect(isinstance(checkin.get("checkin_time"), str) and checkin["checkin_time"], "签到时间非空")

    api_err("POST", "/api/checkin", 4090, {"task_id": main_id}, token=student_token, label="重复签到 4090")
    api_err("POST", "/api/checkin", 4030, {"task_id": main_id}, token=student2_token, label="非负责人签到 4030")
    api_err("POST", "/api/checkin", 4040, {"task_id": 999999}, token=student_token, label="签到不存在任务 4040")

    my_checkins = api_ok("GET", "/api/checkin/me", token=student_token, label="我的签到")
    expect(isinstance(my_checkins.get("items"), list) and my_checkins["items"], "签到记录非空")
    expect(any(item.get("task_id") == main_id for item in my_checkins["items"]), "checkin/me 包含本任务的签到")

    # ---- 7) 积分账实一致 -------------------------------------------------
    credits_me = api_ok("GET", "/api/credits/me", token=student_token, label="我的积分")
    log_sum = sum(int(log.get("delta") or 0) for log in credits_me.get("logs") or [])
    expect(
        credits_me.get("credits") == log_sum,
        f"余额 == 流水之和（{credits_me.get('credits')} vs {log_sum}）",
    )

    # ---- 8) 认证失败 -----------------------------------------------------
    api_err("GET", "/api/tasks", 4010, expected_status=401, label="无 token 访问 401/4010")
    api_err("GET", "/api/credits/me", 4010, token="invalid-token", expected_status=401, label="无效 token 401/4010")

    # ---- 9) 非法流转（4090）----------------------------------------------
    api_err("POST", f"/api/tasks/{main_id}/submit", 4090, token=student_token, label="verified 再提交 4090")
    # P2：verified（终态）不允许再报名；student02 未报名过，命中的是「状态不允许报名」
    api_err("POST", f"/api/tasks/{main_id}/apply", 4090, token=student2_token, label="verified 任务报名 4090")
    api_err(
        "PATCH",
        f"/api/tasks/{main_id}",
        4090,
        {"status": "cancelled"},
        token=teacher_token,
        label="verified 取消 4090",
    )

    # ---- 10) 发布者自认领（4030）与 assign --------------------------------
    self_claim_task = create_task(
        teacher_token,
        {"title": TITLE_SELF_CLAIM, "description": "发布者自认领用例"},
        label="发布自认领任务",
    )
    self_id = self_claim_task["id"]
    api_err("POST", f"/api/tasks/{self_id}/apply", 4030, token=teacher_token, label="发布者报名自己任务 4030")
    api_err("POST", f"/api/tasks/{self_id}/claim", 4030, token=teacher_token, label="发布者 claim 自己任务 4030")

    api_err(
        "PATCH",
        f"/api/tasks/{main_id}",
        4030,
        {"title": "越权改名"},
        token=student_token,
        label="非发布者修改任务 4030",
    )
    api_err(
        "POST",
        f"/api/tasks/{main_id}/verify",
        4030,
        {"pass": True},
        token=student_token,
        label="非发布者验收 4030",
    )
    api_err(
        "POST",
        f"/api/tasks/{self_id}/assign",
        4030,
        {"user_id": student_id},
        token=student_token,
        label="非发布者指派 4030",
    )

    assigned = api_ok(
        "POST",
        f"/api/tasks/{self_id}/assign",
        {"user_id": student2_id},
        token=teacher_token,
        label="发布者指派",
    )
    expect(assigned.get("assignee_id") == student2_id, f"指派后 assignee_id 正确（实际 {assigned.get('assignee_id')}）")
    expect(assigned.get("status") == "claimed", f"指派后状态 claimed（实际 {assigned.get('status')}）")
    expect(assigned.get("claim_type") == "assign", f"指派后 claim_type=assign（实际 {assigned.get('claim_type')}）")

    assigned_notify = notifications(student2_token, "被指派人通知")
    expect(
        any(n.get("task_id") == self_id and n.get("level") == "info" for n in assigned_notify["items"]),
        "被指派人收到 info 通知",
    )
    api_err(
        "POST",
        f"/api/tasks/{self_id}/assign",
        4040,
        {"user_id": 999999},
        token=teacher_token,
        label="指派不存在用户 4040",
    )

    # PATCH 语义：显式提供才修改，extras 原样落库
    patched = api_ok(
        "PATCH",
        f"/api/tasks/{self_id}",
        {"description": None, "extras": {"备注": "补录"}},
        token=teacher_token,
        label="PATCH 修改任务",
    )
    expect(patched.get("description") is None, "PATCH 显式 null 清空 description")
    expect(patched.get("extras") == {"备注": "补录"}, f"PATCH 更新 extras（实际 {patched.get('extras')!r}）")
    expect(patched.get("title") == TITLE_SELF_CLAIM, "PATCH 未提供的字段保持原值")

    # ---- 11) 前置依赖未完成（4020）---------------------------------------
    dep_parent = create_task(teacher_token, {"title": TITLE_DEP_PARENT}, label="发布依赖父任务")
    dep_first = create_task(
        teacher_token,
        {"title": TITLE_DEP_FIRST, "parent_id": dep_parent["id"], "quota": 3},
        label="发布子任务一",
    )
    dep_second = create_task(
        teacher_token,
        {"title": TITLE_DEP_SECOND, "parent_id": dep_parent["id"], "depends_on": dep_first["id"], "quota": 4},
        label="发布子任务二（依赖子任务一）",
    )
    expect(dep_second.get("depends_on") == dep_first["id"], "子任务二 depends_on 指向子任务一")
    expect(dep_second.get("parent_id") == dep_parent["id"], "子任务 parent_id 指向父任务")

    api_err(
        "POST",
        "/api/tasks",
        4030,
        {"parent_id": dep_parent["id"], "title": "T10 E2E 越权子任务"},
        token=student_token,
        label="非父任务发布者创建子任务 4030",
    )

    dep_applied = apply_task(student_token, dep_first["id"], "报名子任务一")
    expect(dep_applied["task"].get("status") == "published", "子任务一报名后仍 published（待审批）")
    dep_approved = decide_application(
        teacher_token, dep_applied["application"]["id"], True, "通过子任务一报名"
    )
    expect(dep_approved["task"].get("status") == "claimed", "子任务一审批后 claimed（前置未完成但无依赖）")

    dependency_error = api_err(
        "POST",
        f"/api/tasks/{dep_second['id']}/apply",
        4020,
        token=student_token,
        label="依赖未完成报名 4020",
    )
    expect(
        TITLE_DEP_FIRST in (dependency_error.get("msg") or ""),
        f"4020 消息含前置任务标题（实际 {dependency_error.get('msg')}）",
    )

    sub_items = list_tasks(student_token, label="列表(include_sub=true)", include_sub=True)
    second_view = find_task(sub_items, dep_second["id"])
    expect(second_view.get("is_claimable") is False, "前置未完成时 is_claimable=false（前端置灰依据）")
    first_view = find_task(sub_items, dep_first["id"])
    expect(first_view.get("is_claimable") is False, "已被认领的子任务 is_claimable=false")

    # ---- 12) 发布参数校验（4001）-----------------------------------------
    api_err("POST", "/api/tasks", 4001, {"title": "   "}, token=teacher_token, label="标题空白 4001")
    api_err("POST", "/api/tasks", 4001, {"title": "T10 E2E 非法配额", "quota": 0}, token=teacher_token, label="quota<1 4001")
    api_err(
        "POST",
        "/api/tasks",
        4001,
        {"title": "T10 E2E 非法奖励", "credit_reward": -1},
        token=teacher_token,
        label="credit_reward<0 4001",
    )

    # ---- 13) 拆解（mock）-------------------------------------------------
    decompose = api_ok("POST", f"/api/tasks/{main_id}/decompose", token=teacher_token, label="拆解建议")
    expect(decompose.get("mock") is True, f"mock 模式拆解返回 mock=true（实际 {decompose.get('mock')}）")
    suggestions = decompose.get("suggested_sub_tasks")
    expect(isinstance(suggestions, list) and len(suggestions) == 3, f"秋之韵任务返回 3 条拆解建议（实际 {len(suggestions or [])}）")
    expect([s.get("depends_on") for s in suggestions] == [None, 0, 1], f"拆解依赖索引 null,0,1（实际 {[s.get('depends_on') for s in suggestions]}）")
    expect(all(s.get("sop_guide") for s in suggestions), "每条建议都有 sop_guide")
    api_err("POST", f"/api/tasks/{main_id}/decompose", 4030, token=student_token, label="非发布者拆解 4030")

    print(f"---- test_api_e2e.py 全部通过：{_passed} 项断言 ----")
    return 0


if __name__ == "__main__":
    sys.exit(main())