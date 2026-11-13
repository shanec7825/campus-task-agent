"""阶段 1 隔离演示数据（仅用于本机走查截图，不进入真实库）。

用法（仓库根）：
    set DATABASE_PATH=outputs/phase1-ia/demo.db
    python scripts/seed_phase1_demo.py

脚本强制要求显式 DATABASE_PATH，且拒绝 backend/campus.db；重复运行会跳过已存在的
同名活动/任务，不删除任何既有行。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv("DATABASE_PATH", "").strip()
if not DB_PATH:
    raise SystemExit("必须显式设置隔离 DATABASE_PATH，例如 outputs/phase1-ia/demo.db")
if Path(DB_PATH).name == "campus.db":
    raise SystemExit("拒绝写入 backend/campus.db，请使用隔离数据库")

sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Activity, Notification, Task, TaskApplication, TaskMember, User  # noqa: E402

USERS = [
    ("teacher01", "王老师", "publisher", "计算机学院团委"),
    ("student01", "李同学", "student", "计算机学院团委"),
    ("student02", "张同学", "student", "计算机学院团委"),
    ("student03", "陈同学", "student", "计算机学院团委"),
]


def get_user(db, username: str) -> User:
    row = db.scalar(select(User).where(User.username == username))
    if row is None:
        raise SystemExit(f"缺少演示用户 {username}，请先通过登录接口或脚本创建")
    return row


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        for username, display_name, role, org in USERS:
            if db.scalar(select(User).where(User.username == username)) is None:
                db.add(User(username=username, display_name=display_name, role=role, org=org))
        db.commit()

        teacher = get_user(db, "teacher01")
        s1 = get_user(db, "student01")
        s2 = get_user(db, "student02")
        s3 = get_user(db, "student03")

        if db.scalar(select(Activity).where(Activity.title == "2026 迎新志愿活动")) is None:
            activity = Activity(
                title="2026 迎新志愿活动",
                description="新生报到两天的场地、人员与收尾工作，按任务分块推进。",
                location="东区体育馆与北门广场",
                start_time="2026-11-20 08:00",
                deadline="2026-11-22 18:00",
                owner_id=teacher.id,
                org="计算机学院团委",
                status="published",
                created_at="2026-11-10 09:00:00",
            )
            db.add(activity)
            db.flush()

            def add_task(title, *, parent=None, deadline="2026-11-20 18:00", status="published",
                         assignee=None, location="东区体育馆", quota=None, credit=4,
                         description=None, reward=0):
                task = Task(
                    parent_id=parent.id if parent else None,
                    activity_id=activity.id,
                    title=title,
                    description=description,
                    location=location,
                    deadline=deadline,
                    quota=quota,
                    volunteer_hours=2,
                    status=status,
                    claim_type="open",
                    publisher_id=teacher.id,
                    assignee_id=assignee.id if assignee else None,
                    credit_reward=credit or reward,
                    extras={},
                    created_at="2026-11-10 10:00:00",
                )
                db.add(task)
                db.flush()
                return task

            venue = add_task(
                "场地准备",
                deadline="2026-11-18 18:00",
                status="in_progress",
                assignee=s1,
                description="按点位图完成桌椅与签到区布置。",
            )
            move = add_task("搬运桌椅", parent=venue, deadline="2026-11-16 18:00",
                            status="verified", assignee=s1)
            sign = add_task("布置签到处", parent=venue, deadline="2026-11-17 18:00",
                            status="verified", assignee=s2)

            staff = add_task(
                "人员安排",
                deadline="2026-11-19 18:00",
                status="published",
                description="确定志愿者名单并完成排班通知。",
                quota=30,
            )
            recruit = add_task("招募志愿者", parent=staff, deadline="2026-11-15 20:00",
                               status="submitted", assignee=s3)
            roster = add_task("排班通知", parent=staff, deadline="2026-11-19 12:00",
                              status="published", assignee=s1)

            wrap = add_task(
                "活动收尾",
                deadline="2026-11-22 17:00",
                status="published",
                description="清理现场并归还借用物资。",
            )
            add_task("清理场地", parent=wrap, deadline="2026-11-22 16:00", status="published")
            add_task("归还物资", parent=wrap, deadline="2026-11-22 17:00", status="published")

            # 报名与执行记录
            def approve(task, user, member_status="not_started"):
                db.add(TaskApplication(task_id=task.id, user_id=user.id, status="approved",
                                       created_at="2026-11-11 09:00:00",
                                       decided_at="2026-11-11 10:00:00", decided_by=teacher.id))
                db.add(TaskMember(task_id=task.id, user_id=user.id, status=member_status,
                                  submitted_at="2026-11-12 20:00:00" if member_status == "submitted" else None,
                                  verified_at="2026-11-13 09:00:00" if member_status == "verified" else None,
                                  updated_at="2026-11-13 09:00:00"))

            approve(venue, s1, "in_progress")
            approve(move, s1, "verified")
            approve(sign, s2, "verified")
            approve(recruit, s3, "submitted")
            approve(roster, s1, "not_started")

            # 人员安排：两条待审批报名
            for user in (s1, s2):
                db.add(TaskApplication(task_id=staff.id, user_id=user.id, status="pending",
                                       created_at="2026-11-12 19:00:00"))

            # 活动 B：下层已完成、待负责人确认
            review_activity = Activity(
                title="校园环保周",
                description="三个收尾任务已完成现场工作，等待负责人统一验收。",
                location="教学楼 A 区",
                start_time="2026-11-18 08:00",
                deadline="2026-11-24 18:00",
                owner_id=teacher.id,
                org="计算机学院团委",
                status="published",
                created_at="2026-11-11 09:00:00",
            )
            db.add(review_activity)
            db.flush()

            clean = Task(
                parent_id=None, activity_id=review_activity.id, title="垃圾分类宣传",
                description="摊位宣传与问卷回收。", location="食堂门口", deadline="2026-11-23 18:00",
                quota=12, volunteer_hours=2, status="published", claim_type="open",
                publisher_id=teacher.id, credit_reward=4, extras={},
                created_at="2026-11-11 10:00:00",
            )
            db.add(clean)
            db.flush()
            for child_title in ("设计宣传板", "发放问卷"):
                child = Task(
                    parent_id=clean.id, activity_id=review_activity.id, title=child_title,
                    location="食堂门口", deadline="2026-11-23 17:00", status="verified",
                    claim_type="open", publisher_id=teacher.id, credit_reward=2, extras={},
                    created_at="2026-11-11 11:00:00",
                )
                db.add(child)
                db.flush()
                db.add(TaskApplication(task_id=child.id, user_id=s1.id, status="approved",
                                       created_at="2026-11-12 09:00:00",
                                       decided_at="2026-11-12 10:00:00", decided_by=teacher.id))
                db.add(TaskMember(task_id=child.id, user_id=s1.id, status="verified",
                                  submitted_at="2026-11-12 20:00:00",
                                  verified_at="2026-11-13 09:00:00",
                                  updated_at="2026-11-13 09:00:00"))

        # 独立任务
        if db.scalar(select(Task).where(Task.title == "图书馆旧书整理")) is None:
            db.add(Task(
                parent_id=None, activity_id=None, title="图书馆旧书整理",
                description="按索书号上架并登记破损书目。", location="图书馆三层",
                deadline="2026-11-14 18:00", quota=5, volunteer_hours=3,
                status="published", claim_type="open", publisher_id=teacher.id,
                credit_reward=3, extras={}, created_at="2026-11-09 10:00:00",
            ))

        # 未读通知
        if db.scalar(select(Notification).where(Notification.user_id == teacher.id)) is None:
            db.add(Notification(user_id=teacher.id, task_id=None, level="warning",
                                title="有 2 条报名待审批", content="「人员安排」有新的志愿者报名。",
                                is_read=0, dedupe_key="demo-apply-staff",
                                created_at="2026-11-12 19:10:00"))
            db.add(Notification(user_id=teacher.id, task_id=None, level="info",
                                title="「招募志愿者」已提交", content="陈同学提交了完成说明，等待验收。",
                                is_read=0, dedupe_key="demo-submit-recruit",
                                created_at="2026-11-12 20:10:00"))

        db.commit()
        print(f"演示数据已写入 {Path(DB_PATH).resolve()}")
    finally:
        db.close()


if __name__ == "__main__":
    main()