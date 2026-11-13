"""一次性管理命令（契约 `C-AUTH-API@1`，owner = T2）。

用法：``python -m app.cli create-platform-admin --username <name> --display-name <name>``。
密码优先取环境变量 ``CTA_ADMIN_PASSWORD``，缺失时交互式 ``getpass``；成功后只输出
``created <username>``，绝不回显密码。
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from datetime import datetime

from app.db import SessionLocal, init_db
from app.models import User
from app.security import hash_password

MIN_PASSWORD_LENGTH = 8
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def create_platform_admin(username: str, display_name: str) -> int:
    """创建平台管理员账号，返回进程退出码。"""
    init_db()
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first() is not None:
            print(f"用户名已存在：{username}", file=sys.stderr)
            return 1
        password = os.getenv("CTA_ADMIN_PASSWORD") or getpass.getpass("请输入初始密码：")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"密码长度不能少于 {MIN_PASSWORD_LENGTH} 位", file=sys.stderr)
            return 1
        db.add(
            User(
                username=username,
                display_name=display_name,
                role="admin",
                org=None,
                credits=0,
                password_hash=hash_password(password),
                password_updated_at=datetime.now().strftime(_TS_FORMAT),
                status="active",
                platform_admin=1,
            )
        )
        db.commit()
        print(f"created {username}")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)
    admin = subparsers.add_parser("create-platform-admin", help="创建平台管理员账号")
    admin.add_argument("--username", required=True, help="登录用户名")
    admin.add_argument("--display-name", required=True, help="展示名")

    args = parser.parse_args(argv)
    if args.command == "create-platform-admin":
        return create_platform_admin(args.username.strip(), args.display_name.strip())
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())