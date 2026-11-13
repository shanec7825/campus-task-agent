"""阶段 2 隔离演示数据（仅本机浏览器走查，不进入真实库、不提交明文凭据）。

用法（仓库根）：
    DATABASE_PATH=outputs/phase2/demo.db python scripts/seed_phase2_demo.py

输出 `outputs/phase2/demo_secrets.json`（被 .gitignore 忽略）：
- 演示账号与测试口令；
- 一条组织邀请明文（一次性，供注册页验证）；
- 一条密码重置明文（一次性，供重置页验证）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv("DATABASE_PATH", "").strip()
if not DB_PATH:
    raise SystemExit("必须显式设置隔离 DATABASE_PATH，例如 outputs/phase2/demo.db")
if Path(DB_PATH).name == "campus.db":
    raise SystemExit("拒绝写入 backend/campus.db，请使用隔离数据库")

sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    Invitation,
    Organization,
    OrgMember,
    PasswordReset,
    Task,
    User,
)
from app.security import hash_password, hash_token, new_token  # noqa: E402

PASSWORD = "TestPass123!"


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        if db.scalar(select(User).where(User.username == "member01")) is not None:
            print("演示数据已存在，跳过")
            return

        def user(username: str, display: str, *, platform: bool = False, legacy: bool = False) -> User:
            row = User(
                username=username,
                display_name=display,
                role="publisher" if platform else "student",
                org=None,
                status="legacy_unclaimed" if legacy else "active",
                platform_admin=1 if platform else 0,
                password_hash=None if legacy else hash_password(PASSWORD),
                credits=0,
            )
            db.add(row)
            db.flush()
            return row

        platform = user("platform01", "平台管理员", platform=True)
        org_admin = user("orgadmin", "王老师")
        collab = user("collab", "李协作者")
        member = user("member01", "陈同学")
        outsider = user("outsider", "赵外院")
        legacy = user("teacher01", "旧演示账号", legacy=True)

        org_a = Organization(name="计算机学院团委", slug="cs-youth", status="active", created_at="2026-11-13 09:00:00")
        org_b = Organization(name="外国语学院团委", slug="fl-youth", status="active", created_at="2026-11-13 09:00:00")
        db.add_all([org_a, org_b])
        db.flush()

        db.add_all([
            OrgMember(org_id=org_a.id, user_id=org_admin.id, role="admin", title="团委书记", status="active", created_at="2026-11-13 09:10:00"),
            OrgMember(org_id=org_a.id, user_id=collab.id, role="collaborator", title="宣传委员", status="active", created_at="2026-11-13 09:10:00"),
            OrgMember(org_id=org_a.id, user_id=member.id, role="member", title="班长", status="active", created_at="2026-11-13 09:10:00"),
            OrgMember(org_id=org_b.id, user_id=outsider.id, role="member", title=None, status="active", created_at="2026-11-13 09:10:00"),
        ])

        activity_a = Activity(
            title="2026 迎新志愿活动", description="学院迎新两天的场地与人员安排。",
            location="东区体育馆", start_time="2026-11-20 08:00", deadline="2026-11-22 18:00",
            owner_id=org_admin.id, org="计算机学院团委", org_id=org_a.id,
            status="published", created_at="2026-11-12 09:00:00",
        )
        activity_b = Activity(
            title="外语角筹备", description="外院独立活动，不应被计算机学院成员读取。",
            location="文科楼 201", start_time="2026-11-21 14:00", deadline="2026-11-21 18:00",
            owner_id=outsider.id, org="外国语学院团委", org_id=org_b.id,
            status="published", created_at="2026-11-12 10:00:00",
        )
        db.add_all([activity_a, activity_b])
        db.flush()

        venue = Task(
            parent_id=None, activity_id=activity_a.id, org_id=org_a.id, title="场地准备",
            description="按点位图完成桌椅与签到区布置。", location="东区体育馆",
            deadline="2026-11-18 18:00", quota=10, volunteer_hours=2, status="in_progress",
            claim_type="open", publisher_id=collab.id, assignee_id=member.id,
            credit_reward=4, extras={}, created_at="2026-11-12 11:00:00",
        )
        db.add(venue)
        db.flush()
        db.add(Task(
            parent_id=venue.id, activity_id=activity_a.id, org_id=org_a.id, title="搬运桌椅",
            location="东区体育馆", deadline="2026-11-17 18:00", status="published",
            claim_type="open", publisher_id=collab.id, credit_reward=2, extras={},
            created_at="2026-11-12 11:10:00",
        ))
        db.add(Task(
            parent_id=None, activity_id=activity_b.id, org_id=org_b.id, title="外语角志愿者招募",
            description="外院公开任务。", location="文科楼 201", deadline="2026-11-20 18:00",
            quota=6, status="published", claim_type="open", publisher_id=outsider.id,
            credit_reward=3, extras={}, created_at="2026-11-12 12:00:00",
        ))

        invite_token = new_token(32)
        db.add(Invitation(
            org_id=org_a.id, role_cap="member", token_hash=hash_token(invite_token),
            expires_at="2026-12-31 23:59:59", max_uses=2, used_count=0,
            created_by=org_admin.id, created_at="2026-11-13 09:30:00",
        ))

        reset_token = new_token(32)
        db.add(PasswordReset(
            user_id=member.id, token_hash=hash_token(reset_token),
            expires_at="2026-12-31 23:59:59", used_at=None,
            created_by=org_admin.id, created_at="2026-11-13 09:40:00",
        ))

        db.commit()

        payload = {
            "base_password": PASSWORD,
            "accounts": {
                "platform01": "平台管理员（platform_admin）",
                "orgadmin": "计算机学院团委 管理员",
                "collab": "计算机学院团委 协作者",
                "member01": "计算机学院团委 成员",
                "outsider": "外国语学院团委 成员",
                "teacher01": "旧演示账号（不可登录）",
            },
            "org_a_activity_id": activity_a.id,
            "org_b_activity_id": activity_b.id,
            "org_a_venue_task_id": venue.id,
            "invite_token": invite_token,
            "reset_token": reset_token,
        }
        out = ROOT / "outputs" / "phase2" / "demo_secrets.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"演示数据已写入 {Path(DB_PATH).resolve()}")
        print(f"演示凭据已写入 {out}（本地忽略目录，不提交）")
    finally:
        db.close()


if __name__ == "__main__":
    main()