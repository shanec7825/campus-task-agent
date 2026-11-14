#!/usr/bin/env python
"""AIW-12 问答额度原子预留与并发回归（契约 `C-AI-RESERVATION@2`）。

覆盖：

1. 最后 1 份额度下多线程并发 ``POST /api/agent/chat``：恰好 1 次成功、其余 4290，
   账本当天占用数不超过上限且没有残留 pending；
2. 模型失败删除 pending 预留、不扣额度，随后可继续成功问答；
3. 相同 ``request_id`` 重放既有结果，不重复计费；
4. 10 分钟前遗留的 pending 预留被清理，5 分钟内的 pending 仍占额度（4290）；
5. 跨日边界只统计服务端当天，昨天的 settled 行不计入今日额度。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``（``tempfile.mkdtemp``）、
``MAAS_MOCK=1``、``MAAS_API_KEY=''``、``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``。
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-aiw12-quota-concurrency-"))
_TEST_DB_PATH = _TMP_DIR / "aiw12.db"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"
os.environ["AI_DAILY_QUOTA"] = "50"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.agents import llm_client  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AiUsageLedger, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import ai_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
ERR_QUOTA = 4290
STATUS_PENDING = "pending"
STATUS_SETTLED = "settled"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _ensure_user(username: str, display_name: str) -> int:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(username=username, display_name=display_name, role="student", credits=0)
            db.add(user)
        user.password_hash = hash_password(PASSWORD)
        user.status = "active"
        db.commit()
        db.refresh(user)
        return int(user.id)


def _session_headers(response) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()
    session = values.get(SESSION_COOKIE)
    csrf = values.get(CSRF_COOKIE)
    assert session and csrf, "登录响应缺少会话 Cookie"
    return {
        "Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}",
        CSRF_HEADER: csrf,
    }


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    payload = response.json()
    assert response.status_code == 200 and payload.get("code") == 0, (
        f"登录 {username} 失败：HTTP {response.status_code} / code={payload.get('code')}"
    )
    headers = _session_headers(response)
    client.cookies.clear()
    return headers


def _clear_ledger(user_id: int) -> None:
    with SessionLocal() as db:
        db.query(AiUsageLedger).filter(AiUsageLedger.user_id == user_id).delete()
        db.commit()


def _chat(client: TestClient, headers: dict[str, str], message: str, request_id: str) -> dict:
    response = client.post(
        "/api/agent/chat",
        json={"message": message, "request_id": request_id},
        headers=headers,
    )
    payload = response.json()
    assert isinstance(payload, dict), f"响应不是对象（HTTP {response.status_code}）"
    return payload


def _ledger_rows(user_id: int, *, today_only: bool = True) -> list[AiUsageLedger]:
    with SessionLocal() as db:
        query = db.query(AiUsageLedger).filter(
            AiUsageLedger.user_id == user_id,
            AiUsageLedger.status.in_((STATUS_PENDING, STATUS_SETTLED)),
        )
        if today_only:
            today = datetime.now().strftime("%Y-%m-%d")
            query = query.filter(AiUsageLedger.created_at.like(f"{today}%"))
        return list(query.order_by(AiUsageLedger.id.asc()).all())


def _insert_ledger(
    user_id: int,
    *,
    request_id: str,
    status: str,
    created_at: str,
) -> int:
    with SessionLocal() as db:
        row = AiUsageLedger(
            user_id=user_id,
            request_id=request_id,
            operation="chat",
            status=status,
            units=1,
            created_at=created_at,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)


def _text_time(delta: timedelta) -> str:
    return (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")


def test_concurrent_last_quota_unit_only_one_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    user_id = _ensure_user("aiw12_race", "并发争用用户")
    headers = _login(client, "aiw12_race")
    _clear_ledger(user_id)

    workers = 6
    barrier = threading.Barrier(workers)
    lock = threading.Lock()
    codes: list[int] = []

    def _run(index: int) -> None:
        local = TestClient(app)
        try:
            barrier.wait(timeout=10)
            payload = _chat(local, headers, f"并发争用 {index}", f"aiw12-race-{index}")
            with lock:
                codes.append(int(payload.get("code")))
        finally:
            local.close()

    threads = [threading.Thread(target=_run, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads), "并发请求未在超时内结束"

    assert len(codes) == workers, f"应收到 {workers} 个响应，实际 {len(codes)}：{codes}"
    assert codes.count(0) == 1, f"最后 1 份额度应恰好 1 次成功，实际成功 {codes.count(0)}：{codes}"
    assert codes.count(ERR_QUOTA) == workers - 1, f"其余请求应全部 4290：{codes}"
    assert set(codes) <= {0, ERR_QUOTA}, f"不应出现其他错误码：{codes}"

    rows = _ledger_rows(user_id)
    assert len(rows) == 1, f"账本当天占用数应等于上限 1，实际 {len(rows)}"
    assert sum(row.units for row in rows) == 1, "账本单位总数不得超限"
    assert all(row.status == STATUS_SETTLED for row in rows), "成功请求不得残留 pending 预留"


def test_model_failure_releases_reservation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    user_id = _ensure_user("aiw12_failure", "模型失败用户")
    headers = _login(client, "aiw12_failure")
    _clear_ledger(user_id)

    def _boom(_items, _question):
        raise ApiError(5001, "模拟模型失败")

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: False)
    monkeypatch.setattr(ai_service, "_real_answer", _boom)

    failed = _chat(client, headers, "模型失败", "aiw12-fail")
    assert failed.get("code") == 5001, f"模型失败应返回 5001，实际 {failed.get('code')}"
    assert _ledger_rows(user_id) == [], "模型失败必须删除 pending 预留、不扣额度"

    monkeypatch.setattr(llm_client, "is_mock_mode", lambda: True)
    succeeded = _chat(client, headers, "失败后重试", "aiw12-fail-retry")
    assert succeeded.get("code") == 0, f"释放额度后应能继续问答：{succeeded.get('code')}"
    rows = _ledger_rows(user_id)
    assert len(rows) == 1 and rows[0].status == STATUS_SETTLED


def test_same_request_id_replays_without_extra_charge(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "2")
    user_id = _ensure_user("aiw12_replay", "幂等重放用户")
    headers = _login(client, "aiw12_replay")
    _clear_ledger(user_id)

    first = _chat(client, headers, "我有哪些任务？", "aiw12-replay-1")
    assert first.get("code") == 0, f"首次问答应成功：{first.get('code')}"
    assert first["data"]["replayed"] is False

    second = _chat(client, headers, "我有哪些任务？", "aiw12-replay-1")
    assert second.get("code") == 0, f"同键重放应成功：{second.get('code')}"
    assert second["data"]["replayed"] is True
    assert second["data"]["assistant_message"]["id"] == first["data"]["assistant_message"]["id"]

    rows = _ledger_rows(user_id)
    assert len(rows) == 1, f"同键重放不得重复写账本，实际 {len(rows)} 行"
    assert rows[0].status == STATUS_SETTLED


def test_stale_pending_reservation_is_cleaned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    user_id = _ensure_user("aiw12_stale", "超时预留用户")
    headers = _login(client, "aiw12_stale")
    _clear_ledger(user_id)

    _insert_ledger(
        user_id,
        request_id="aiw12-stale-old",
        status=STATUS_PENDING,
        created_at=_text_time(timedelta(minutes=11)),
    )

    payload = _chat(client, headers, "超时恢复后提问", "aiw12-stale-new")
    assert payload.get("code") == 0, f"超时 pending 应被清理后允许生成：{payload.get('code')}"
    rows = _ledger_rows(user_id)
    assert len(rows) == 1, f"应只剩本次结算行，实际 {len(rows)} 行"
    assert rows[0].status == STATUS_SETTLED
    assert rows[0].request_id == "aiw12-stale-new", "旧 pending 行应被清理，保留本次请求的结算行"


def test_recent_pending_still_occupies_quota(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    user_id = _ensure_user("aiw12_recent_pending", "执行中预留用户")
    headers = _login(client, "aiw12_recent_pending")
    _clear_ledger(user_id)

    recent_id = _insert_ledger(
        user_id,
        request_id="aiw12-recent-pending",
        status=STATUS_PENDING,
        created_at=_text_time(timedelta(minutes=5)),
    )

    payload = _chat(client, headers, "执行中的预留", "aiw12-recent-new")
    assert payload.get("code") == ERR_QUOTA, f"5 分钟内的 pending 仍应占额度：{payload.get('code')}"
    rows = _ledger_rows(user_id)
    assert len(rows) == 1 and int(rows[0].id) == recent_id, "未超时的 pending 行不得被清理"


def test_daily_boundary_only_counts_today(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_DAILY_QUOTA", "1")
    user_id = _ensure_user("aiw12_daily", "跨日边界用户")
    headers = _login(client, "aiw12_daily")
    _clear_ledger(user_id)

    _insert_ledger(
        user_id,
        request_id="aiw12-yesterday",
        status=STATUS_SETTLED,
        created_at=_text_time(timedelta(days=1)),
    )

    first = _chat(client, headers, "今天第一次", "aiw12-today-1")
    assert first.get("code") == 0, f"昨天的 settled 不应占用今天额度：{first.get('code')}"

    second = _chat(client, headers, "今天第二次", "aiw12-today-2")
    assert second.get("code") == ERR_QUOTA, f"今天额度用完后应 4290：{second.get('code')}"

    rows = _ledger_rows(user_id)
    assert len(rows) == 1 and rows[0].request_id == "aiw12-today-1"

    usage = client.get("/api/agent/usage", headers=headers)
    usage_payload = usage.json()
    assert usage_payload.get("code") == 0
    assert usage_payload["data"]["used"] == 1
    assert usage_payload["data"]["remaining"] == 0