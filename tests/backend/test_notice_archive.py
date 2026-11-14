#!/usr/bin/env python
"""通知归档（契约 `C-NOTICE-ARCHIVE@1`）。

覆盖：默认列表只含未归档、归档后移出并减少未读、归档箱可取且带 `archived_at`、
重复归档幂等、空数组 4001、不能归档他人通知。

隔离：导入 app 前使用临时 DATABASE_PATH / MAAS_MOCK / RUN_SCHEDULER，不触碰 backend/campus.db。
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-notice-archive-"))
_TEST_DB_PATH = _TMP_DIR / "notice.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app import db as app_db  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Notification, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402


def _cleanup_tmp_dir() -> None:
    try:
        app_db.engine.dispose()
    finally:
        shutil.rmtree(_TMP_DIR, ignore_errors=True)


atexit.register(_cleanup_tmp_dir)

if Path(app_db.engine.url.database).resolve() != _TEST_DB_PATH.resolve():
    pytest.skip("通知归档套件必须单文件运行", allow_module_level=True)

PASSWORD = "TestPass123!"


def _ensure_user(username: str, display_name: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                display_name=display_name,
                role="student",
                password_hash=hash_password(PASSWORD),
                status="active",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        return int(user.id)


def _session_headers(response) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()
    assert values.get(SESSION_COOKIE) and values.get(CSRF_COOKIE), "登录响应缺少会话 Cookie"
    return {
        "Cookie": f"{SESSION_COOKIE}={values[SESSION_COOKIE]}; {CSRF_COOKIE}={values[CSRF_COOKIE]}",
        CSRF_HEADER: values[CSRF_COOKIE],
    }


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    payload = response.json()
    assert payload.get("code") == 0, f"登录失败：{payload.get('msg')}"
    client.cookies.clear()
    return _session_headers(response)


def _add_notice(user_id: int, title: str, *, is_read: int = 0) -> int:
    with SessionLocal() as db:
        row = Notification(user_id=user_id, level="info", title=title, content=title, is_read=is_read)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)


@pytest.fixture()
def ctx():
    app_db.init_db()
    owner_id = _ensure_user("notice-owner", "归档本人")
    other_id = _ensure_user("notice-other", "归档他人")
    client = TestClient(app)
    headers = _login(client, "notice-owner")
    client.cookies.clear()
    first = _add_notice(owner_id, "未读通知一")
    second = _add_notice(owner_id, "未读通知二")
    read = _add_notice(owner_id, "已读通知", is_read=1)
    other = _add_notice(other_id, "他人通知")
    return {
        "client": client,
        "headers": headers,
        "owner_id": owner_id,
        "first": first,
        "second": second,
        "read": read,
        "other": other,
    }


def _list(ctx, *, archived: bool, headers=None):
    params = "?archived=true" if archived else ""
    response = ctx["client"].get(f"/api/notifications{params}", headers=headers or ctx["headers"])
    payload = response.json()
    assert payload.get("code") == 0, payload.get("msg")
    return payload["data"]


def _archive(ctx, ids, headers=None):
    response = ctx["client"].post(
        "/api/notifications/archive",
        json={"ids": ids},
        headers=headers or ctx["headers"],
    )
    return response.json()


def test_archive_moves_out_of_inbox_and_reduces_unread(ctx) -> None:
    inbox = _list(ctx, archived=False)
    assert inbox["unread"] == 2
    assert {item["id"] for item in inbox["items"]} == {ctx["first"], ctx["second"], ctx["read"]}

    result = _archive(ctx, [ctx["first"]])
    assert result["code"] == 0 and result["data"]["updated"] == 1

    after = _list(ctx, archived=False)
    assert after["unread"] == 1
    assert ctx["first"] not in {item["id"] for item in after["items"]}

    box = _list(ctx, archived=True)
    assert [item["id"] for item in box["items"]] == [ctx["first"]]
    assert box["items"][0]["archived"] == 1
    assert box["items"][0]["archived_at"]
    assert box["items"][0]["is_read"] == 0  # 归档不改已读


def test_archive_is_idempotent_and_rejects_empty(ctx) -> None:
    assert _archive(ctx, [ctx["second"]])["data"]["updated"] == 1
    again = _archive(ctx, [ctx["second"]])
    assert again["code"] == 0 and again["data"]["updated"] == 0

    empty = _archive(ctx, [])
    assert empty["code"] == 4001


def test_cannot_archive_other_users_notice(ctx) -> None:
    result = _archive(ctx, [ctx["other"]])
    assert result["code"] == 0 and result["data"]["updated"] == 0

    other_headers = _login(ctx["client"], "notice-other")
    other_inbox = _list(ctx, archived=False, headers=other_headers)
    other_items = {item["id"]: item for item in other_inbox["items"]}
    assert ctx["other"] in other_items
    assert other_items[ctx["other"]]["archived"] == 0