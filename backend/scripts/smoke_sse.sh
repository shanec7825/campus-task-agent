#!/usr/bin/env bash
# smoke_sse.sh — T4 自检脚本（`C-SSE@1`：SSE 连接注册表 + 分级催办调度）
#
# 覆盖计划 T4 的 7 条验收：
#   ① import 检查                     ② 多连接 + 跨线程 publish
#   ③ 未 bind_loop 时 publish 不抛异常 ④ 三级扫描（warning/urgent/overdue）
#   ⑤ 同 now 二次扫描新增 0            ⑥ 逾期扣分仅 1 行
#   ⑦ 缺失 / 非法 deadline 被跳过
# 额外覆盖：队列背压（丢弃最旧）、调度器 start/shutdown 幂等、通知模板文案、
#           扫描范围（终态任务不催办）、以及"催办模块不调用 LLM / 不直接写通知表"的静态检查。
#
# 用法：  bash backend/scripts/smoke_sse.sh   （可重复执行，使用临时 DATABASE_PATH，结束自动清理）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${BACKEND_DIR}"

if [ -x "${BACKEND_DIR}/.venv/Scripts/python.exe" ]; then
  PY="${BACKEND_DIR}/.venv/Scripts/python.exe"
elif [ -x "${BACKEND_DIR}/.venv/bin/python" ]; then
  PY="${BACKEND_DIR}/.venv/bin/python"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
else
  echo "[FAIL] 找不到 Python 解释器（期望 backend/.venv/Scripts/python.exe）" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
if command -v cygpath >/dev/null 2>&1; then
  TMP_WIN="$(cygpath -w "${TMP_DIR}")"
else
  TMP_WIN="${TMP_DIR}"
fi
export DATABASE_PATH="${TMP_WIN}/smoke_sse.db"
export MAAS_MOCK=1
export RUN_SCHEDULER=0

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

echo "=============================================================="
echo " T4 smoke_sse.sh"
echo " python      : ${PY}"
echo " backend     : ${BACKEND_DIR}"
echo " DATABASE_PATH: ${DATABASE_PATH} (临时库，结束删除)"
echo "=============================================================="

# --------------------------------------------------------------------------- #
echo
echo "---- [1/5] import 检查 --------------------------------------------------"
MAAS_MOCK=1 "${PY}" -c "from app.services.notification_hub import bind_loop, subscribe, unsubscribe, publish; from app.services.reminder_scheduler import start, shutdown, scan_and_remind; print('import ok')"

# --------------------------------------------------------------------------- #
echo
echo "---- [2/5] SSE 连接注册表：多连接 / 跨线程 / 背压 -------------------------"
"${PY}" - <<'PYEOF'
import asyncio
import threading

from app.services import notification_hub as hub

MAXSIZE = hub._QUEUE_MAXSIZE


async def main() -> None:
    hub.bind_loop(asyncio.get_running_loop())
    q1 = hub.subscribe(1)
    q2 = hub.subscribe(1)
    payload = {
        "id": 1,
        "user_id": 1,
        "task_id": 7,
        "level": "urgent",
        "title": "任务今天截止",
        "content": "《布置会场》今天 2026-11-11 18:00:00 截止，请尽快提交。",
        "is_read": 0,
        "created_at": "2026-11-11 10:00:00",
    }

    def worker() -> None:
        # 关键：从**另一线程**发布，验证 call_soon_threadsafe 路径
        hub.publish(1, payload)

    thread = threading.Thread(target=worker, name="publish-thread")
    thread.start()
    thread.join()

    got1 = await asyncio.wait_for(q1.get(), timeout=2)
    got2 = await asyncio.wait_for(q2.get(), timeout=2)
    assert got1 == payload, "连接 1 未收到完整事件"
    assert got2 == payload, "连接 2 未收到完整事件"
    assert hub.connection_count(1) == 2, f"在线连接数应为 2，实际 {hub.connection_count(1)}"
    print(f"[ok] 同一用户 2 条连接各收到 1 条事件；在线连接数={hub.connection_count(1)}")

    # 未订阅用户：不应影响其他连接
    hub.publish(999, {"id": 2})
    assert q1.empty() and q2.empty(), "向未订阅用户发布后，其他连接的队列不应收到数据"
    print("[ok] 向无订阅用户 publish 不产生任何投递")

    # 背压：队列满 → 丢弃最旧，保留最新
    q3 = hub.subscribe(3)
    total = MAXSIZE + 20
    for index in range(total):
        hub.publish(3, {"id": index})
    await asyncio.sleep(0.3)

    drained = []
    while not q3.empty():
        drained.append(q3.get_nowait())
    assert len(drained) == MAXSIZE, f"背压后队列长度应为 {MAXSIZE}，实际 {len(drained)}"
    assert drained[-1]["id"] == total - 1, "队列末尾应为最新事件"
    assert drained[0]["id"] == total - MAXSIZE, (
        f"应丢弃最旧的 20 条（首条 id 期望 {total - MAXSIZE}，实际 {drained[0]['id']}）"
    )
    print(f"[ok] 背压：投递 {total} 条，队列保留 {len(drained)} 条，最旧 {20} 条被丢弃")

    # 注销：幂等 + 空列表清理
    hub.unsubscribe(1, q1)
    hub.unsubscribe(1, q2)
    hub.unsubscribe(3, q3)
    hub.unsubscribe(1, q1)  # 重复注销必须静默
    assert hub.connection_count(1) == 0, "注销后用户 1 仍有残留连接"
    assert hub.connection_count(3) == 0, "注销后用户 3 仍有残留连接"
    assert hub.connection_count() == 0, "注销后仍有全局残留连接"
    print("[ok] unsubscribe 幂等，空列表已清理（全局在线连接数=0）")


asyncio.run(main())

# 循环外 subscribe 必须显式报错（防止队列绑定到错误 loop）
try:
    hub.subscribe(42)
except RuntimeError as exc:
    print(f"[ok] 事件循环外 subscribe 被拒绝：{exc}")
else:
    raise AssertionError("事件循环外 subscribe 未报错")
PYEOF

# --------------------------------------------------------------------------- #
echo
echo "---- [3/5] 未 bind_loop 的容错（独立进程，从不调用 bind_loop） ----------"
"${PY}" - <<'PYEOF'
from app.services import notification_hub as hub

assert hub._loop is None, "本进程不应绑定事件循环"
result = hub.publish(1, {"id": 1, "user_id": 1})
assert result is None, f"未 bind_loop 时 publish 应返回 None，实际 {result!r}"
print("[ok] 未 bind_loop 时 publish 返回 None 且未抛异常（静默丢弃）")
PYEOF

# --------------------------------------------------------------------------- #
echo
echo "---- [4/5] 分级催办调度：幂等启停 + 三级扫描 + 去重 + 扣分 + 脏数据 -----"
"${PY}" - <<'PYEOF'
import inspect
import os
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app.db import SessionLocal, init_db
from app.models import CreditLog, Notification, Task, User
import app.services.credit as credit_service

import app.services.notification_hub as hub
import app.services.notify_service as notify_service
import app.services.reminder_scheduler as rs


def check(cond: bool, message: str) -> None:
    if not cond:
        raise AssertionError(message)


# --------------------------------------------------------------------------- #
# 0) 与被并行实现的 T2 接口对接：检测是否仍为 NotImplementedError 桩
#    生产代码始终调用真实接口；这里仅在桩状态下注入**等价**的兼容实现，
#    让调度逻辑可以先被独立验证（T2 落地后本分支自动失效）。
# --------------------------------------------------------------------------- #
def is_stub(func) -> bool:
    try:
        return "NotImplementedError" in inspect.getsource(func)
    except (OSError, TypeError):  # pragma: no cover - 源码不可读时按已实现处理
        return False


stub_notify = is_stub(notify_service.create_notification)
stub_credit = is_stub(credit_service.adjust_credits)
print(f"[T2 对接] notify_service.create_notification 是否需要兼容桩注入: {stub_notify}")
print(f"[T2 对接] credit.adjust_credits 是否需要兼容桩注入: {stub_credit}")
if not stub_notify and not stub_credit:
    print("[T2 对接] T2 已交付真实实现，本轮扫描直接调用真实接口（无任何 monkeypatch）")

if stub_notify:
    def compat_create_notification(db, *, user_id, task_id, level, title, content):
        """等价实现：落库 + commit + refresh + hub.publish（与 C-NOTIFY@1 一致）。"""
        row = Notification(
            user_id=user_id, task_id=task_id, level=level, title=title, content=content, is_read=0
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        hub.publish(
            user_id,
            {
                "id": row.id,
                "user_id": row.user_id,
                "task_id": row.task_id,
                "level": row.level,
                "title": row.title,
                "content": row.content,
                "is_read": row.is_read,
                "created_at": row.created_at,
            },
        )
        return row

    notify_service.create_notification = compat_create_notification

if stub_credit:
    def compat_adjust_credits(db, user_id, task_id, delta, reason):
        """等价实现：同事务写 credit_logs + 更新 users.credits。"""
        user = db.get(User, user_id)
        if user is None:
            raise LookupError(f"credit.adjust_credits: 用户 {user_id} 不存在")
        db.add(CreditLog(user_id=user_id, task_id=task_id, delta=delta, reason=reason))
        user.credits = (user.credits or 0) + delta
        db.commit()
        db.refresh(user)
        return user.credits

    credit_service.adjust_credits = compat_adjust_credits

# --------------------------------------------------------------------------- #
# 1) 调度器 start / shutdown 幂等（间隔取 REMINDER_INTERVAL_SECONDS）
# --------------------------------------------------------------------------- #
os.environ["REMINDER_INTERVAL_SECONDS"] = "120"
rs.start()
rs.start()
scheduler = rs._scheduler
check(scheduler is not None and scheduler.running, "start() 后调度器未处于运行状态")
jobs = scheduler.get_jobs()
check(len(jobs) == 1, f"start() 两次后作业数应为 1，实际 {len(jobs)}")
check(jobs[0].id == "reminder_scan", f"作业 id 应为 reminder_scan，实际 {jobs[0].id}")
check(
    jobs[0].trigger.interval.total_seconds() == 120,
    f"扫描间隔未取 REMINDER_INTERVAL_SECONDS=120，实际 {jobs[0].trigger.interval}",
)
check(bool(jobs[0].coalesce) is True, "coalesce 应为 True")
check(jobs[0].max_instances == 1, "max_instances 应为 1")
print("[ok] start() 幂等：作业唯一 id=reminder_scan，间隔 120s，coalesce=True，max_instances=1")

rs.shutdown()
rs.shutdown()
check(rs._scheduler is None, "shutdown() 后调度器引用未清空")
print("[ok] shutdown() 幂等：调度器已停止且引用已清空")

# --------------------------------------------------------------------------- #
# 2) 造数：剩 2 天 / 剩 12 小时 / 已逾期 / 脏 deadline / 无 deadline / 终态
# --------------------------------------------------------------------------- #
init_db()
db = SessionLocal()

publisher = User(username="teacher01", display_name="王老师", role="publisher", credits=0)
assignee = User(username="student01", display_name="李同学", role="student", credits=100)
db.add_all([publisher, assignee])
db.commit()
db.refresh(publisher)
db.refresh(assignee)

FMT = rs.DEADLINE_FORMAT
NOW = datetime(2026, 3, 10, 12, 0, 0)


def make_task(title, deadline, status, assignee_id, rule=None):
    task = Task(
        title=title,
        description="",
        status=status,
        claim_type="open",
        publisher_id=publisher.id,
        assignee_id=assignee_id,
        deadline=deadline,
        extras={},
        credit_reward=20,
        reminder_rule=rule,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


warn_task = make_task(
    "布置秋之韵会场", (NOW + timedelta(days=2)).strftime(FMT), "claimed", assignee.id,
    {"days_before": 3, "day_of": True, "on_overdue": True},
)
urgent_task = make_task(
    "现场摄影", (NOW + timedelta(hours=12)).strftime(FMT), "in_progress", assignee.id, None
)
overdue_task = make_task(
    "彩排走位", (NOW - timedelta(hours=1)).strftime(FMT), "claimed", assignee.id, None
)
dirty_task = make_task("脏 deadline", "2026-13-45 99:99:99", "published", None, None)
no_deadline_task = make_task("无 deadline", None, "published", None, None)
verified_task = make_task(
    "已完成任务", (NOW - timedelta(days=3)).strftime(FMT), "verified", assignee.id, None
)
print(
    "[fixture] 任务 id: warning=%s urgent=%s overdue=%s dirty=%s no_deadline=%s verified=%s"
    % (warn_task.id, urgent_task.id, overdue_task.id, dirty_task.id, no_deadline_task.id, verified_task.id)
)

# --------------------------------------------------------------------------- #
# 3) 三次扫描
# --------------------------------------------------------------------------- #
first = rs.scan_and_remind(now=NOW)
second = rs.scan_and_remind(now=NOW)
third = rs.scan_and_remind(now=NOW + timedelta(minutes=1))
print(f"[scan] 第 1 次（now={NOW}）= {first} 条")
print(f"[scan] 第 2 次（同 now）        = {second} 条")
print(f"[scan] 第 3 次（now+1min）      = {third} 条")

# 说明：overdue 级别按 R5-AC4 必须通知「负责人 + 发布者」双方，
# 故首次扫描 4 行 = warning 1 + urgent 1 + overdue 2（3 个催办事件）。
check(first == 4, f"首次扫描应新增 4 条（warning 1 / urgent 1 / overdue 2），实际 {first}")
check(second == 0, f"同一 now 二次扫描应新增 0 条，实际 {second}")
check(third == 0, f"三次扫描应新增 0 条，实际 {third}")

# --------------------------------------------------------------------------- #
# 4) 按 level 分组 & 接收人校验
# --------------------------------------------------------------------------- #
group_rows = db.execute(
    select(Notification.level, func.count(Notification.id)).group_by(Notification.level).order_by(Notification.level)
).all()
print("[query] notifications 按 level 分组：")
for level, count in group_rows:
    print(f"        level={level:<8} count={count}")
by_level = {level: count for level, count in group_rows}
check(by_level.get("warning") == 1, f"warning 应为 1 条，实际 {by_level.get('warning')}")
check(by_level.get("urgent") == 1, f"urgent 应为 1 条，实际 {by_level.get('urgent')}")
check(by_level.get("overdue") == 2, f"overdue 应为 2 条（负责人+发布者），实际 {by_level.get('overdue')}")
check(by_level.get("info") is None, "不应产生 info 级别通知")

print("[query] 通知明细（id / user_id / task_id / level / title / content）：")
for row in db.execute(select(Notification).order_by(Notification.id)).scalars():
    print(
        f"        #{row.id} user={row.user_id} task={row.task_id} level={row.level:<8} "
        f"title={row.title} content={row.content}"
    )

warning_row = db.execute(select(Notification).where(Notification.level == "warning")).scalar_one()
check(warning_row.user_id == assignee.id, "warning 应发给负责人")
check(warning_row.task_id == warn_task.id, "warning 关联任务错误")
check(warning_row.title == "任务即将截止", f"warning 标题错误：{warning_row.title}")
check(
    warn_task.title in warning_row.content and "请及时推进" in warning_row.content,
    f"warning 文案未按模板填充：{warning_row.content}",
)

urgent_row = db.execute(select(Notification).where(Notification.level == "urgent")).scalar_one()
check(urgent_row.user_id == assignee.id, "urgent 应发给负责人")
check(urgent_row.task_id == urgent_task.id, "urgent 关联任务错误")
check(urgent_row.title == "任务今天截止", f"urgent 标题错误：{urgent_row.title}")
check(
    urgent_task.title in urgent_row.content and "请尽快提交" in urgent_row.content,
    f"urgent 文案未按模板填充：{urgent_row.content}",
)

overdue_rows = db.execute(
    select(Notification).where(Notification.level == "overdue").order_by(Notification.user_id)
).scalars().all()
check({row.user_id for row in overdue_rows} == {assignee.id, publisher.id},
      f"overdue 应同时通知负责人与发布者，实际接收人 {[row.user_id for row in overdue_rows]}")
check(all(row.task_id == overdue_task.id for row in overdue_rows), "overdue 关联任务错误")
check(all(row.title == "任务已逾期" for row in overdue_rows), "overdue 标题错误")
check(all("李同学" in row.content for row in overdue_rows), "overdue 文案缺少负责人姓名")
print("[ok] 四个级别的接收人 / 标题 / 文案模板均符合 2.2.6 表")

# --------------------------------------------------------------------------- #
# 5) 逾期副作用：状态置位 + 一次性扣分
# --------------------------------------------------------------------------- #
db.expire_all()
db.refresh(overdue_task)
check(overdue_task.status == "overdue", f"逾期任务状态应为 overdue，实际 {overdue_task.status}")

penalty_rows = db.execute(
    select(CreditLog).where(
        CreditLog.task_id == overdue_task.id, CreditLog.reason.like("逾期扣分%")
    )
).scalars().all()
print(f"[query] 逾期扣分流水条数 = {len(penalty_rows)}")
for row in penalty_rows:
    print(
        f"        #{row.id} user={row.user_id} task={row.task_id} delta={row.delta} reason={row.reason}"
    )
check(len(penalty_rows) == 1, f"逾期扣分应仅 1 行，实际 {len(penalty_rows)}")
check(penalty_rows[0].delta == -10, f"逾期扣分应为 -10，实际 {penalty_rows[0].delta}")
check(penalty_rows[0].user_id == assignee.id, "逾期扣分对象应为负责人")

db.refresh(assignee)
check(assignee.credits == 90, f"负责人积分应为 100-10=90，实际 {assignee.credits}")

# 第三次扫描后再次确认：扣分仍只有 1 行（幂等）
penalty_after = db.execute(
    select(func.count(CreditLog.id)).where(
        CreditLog.task_id == overdue_task.id, CreditLog.reason.like("逾期扣分%")
    )
).scalar_one()
check(penalty_after == 1, f"三次扫描后逾期扣分仍应为 1 行，实际 {penalty_after}")
print(f"[ok] 三次扫描后 credit_logs 逾期扣分行数 = {penalty_after}，负责人余额 = {assignee.credits}")

# --------------------------------------------------------------------------- #
# 6) 脏数据 / 扫描范围
# --------------------------------------------------------------------------- #
for skipped in (dirty_task, no_deadline_task, verified_task):
    count = db.execute(
        select(func.count(Notification.id)).where(Notification.task_id == skipped.id)
    ).scalar_one()
    check(count == 0, f"任务 {skipped.id}（{skipped.title}）不应产生通知，实际 {count} 条")
print("[ok] 非法/缺失 deadline 的任务被跳过且未抛异常；终态任务不在扫描范围")

check(db.execute(select(func.count(Notification.id))).scalar_one() == 4, "通知总数应为 4")

db.close()
print("[ok] 分级催办扫描全部断言通过")
PYEOF

# --------------------------------------------------------------------------- #
echo
echo "---- [5/5] 静态检查：不调用 LLM / 不直接写通知表 / 只用唯一入口 -----------"
if grep -nE "openai|llm_client" app/services/reminder_scheduler.py; then
  echo "[FAIL] reminder_scheduler.py 命中 LLM 相关符号（R5-AC6 禁止调用 LLM）" >&2
  exit 1
else
  echo "[ok] grep -nE \"openai|llm_client\" app/services/reminder_scheduler.py -> 无命中（不烧 Token）"
fi

if grep -n "Notification(" app/services/reminder_scheduler.py; then
  echo "[FAIL] reminder_scheduler.py 直接构造 Notification（必须经 notify_service）" >&2
  exit 1
else
  echo "[ok] reminder_scheduler.py 未直接 INSERT notifications，通知写入唯一入口为 notify_service.create_notification"
fi

if grep -n "create_notification\|adjust_credits" app/services/reminder_scheduler.py; then
  echo "[ok] 已确认调用真实 T2 接口（见上）"
else
  echo "[FAIL] 未找到 notify_service / credit 调用点" >&2
  exit 1
fi

echo
echo "=============================================================="
echo " ALL CHECKS PASSED  (临时数据库已清理)"
echo "=============================================================="