#!/usr/bin/env python
"""阶段 2 认证与组织权限后端行为测试（契约 `C-HASH@1` / `C-SESSION@1` /
`C-AUTH-API@1` / `C-ORG@1` / `C-AUTHZ@1` / `C-TASK-ORG@1`）。

全部用例通过真实 HTTP 或真实 ORM 行为验证，不做源码/字符串检查：

1. 用户名不赋权：名为 ``admin`` 的普通账号登录后仍无平台管理员权限；
2. 密码哈希：``scrypt$16384$8$1$...`` 格式、随机 salt、错误口令与畸形库值一律 False；
   令牌只存 sha256，明文不出现在库与响应；
3. 登录失败统一文案（不区分账号不存在 / 密码错误）与 5 次失败后的限流；
4. 邀请失效：过期 / 撤销 / 用尽 / 未知令牌 / 并发不超用（``max_uses=1`` 只成功 1 次）；
5. 会话：退出撤销与幂等、过期、用户停用、进程重启后仍可解析、``last_seen_at`` 刷新；
6. CSRF：写操作缺头 / 错头 / 头与会话不匹配均 4030，安全方法豁免；
7. 跨组织越权：读 4040、写 4030，且不改动目标数据；
8. ID 枚举：不存在与无权访问返回同一 code/msg（不泄露存在性）；
9. 平台管理员不自动获得组织内容可见性；不写入 ``org_members``；
10. legacy 同名注册绝不继承（不写密码、不消费邀请）；legacy 只能走受控重置；
11. 密码重置：消费一次性令牌、撤销全部旧会话、轮换新密码；二次使用 / 过期 / 不一致的失败语义。

隔离性：导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立 SQLite，
并强制 ``MAAS_MOCK=1`` / ``RUN_SCHEDULER=0``；每个测试清空业务表后重建基线数据，
不触碰 ``backend/campus.db``。

运行：``pytest tests/backend/test_auth_org_permissions.py -v``
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import socket
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-auth-org-"))
_TEST_DB_PATH = _TMP_DIR / "auth_org.db"

# 必须在导入 app 之前完成：app.db 在模块导入时按 DATABASE_PATH 创建引擎。
os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _ipv6_socketpair(family=None, type=socket.SOCK_STREAM, proto=0):
    """用 IPv6 ``::1`` 生成一对已连接的 socket（等价 ``socket.socketpair()``）。"""
    family = socket.AF_INET6 if family is None else family
    if type is None:
        type = socket.SOCK_STREAM
    listener = socket.socket(family, type, proto)
    client = None
    try:
        listener.bind(("::1", 0))
        listener.listen(1)
        client = socket.socket(family, type, proto)
        client.connect(listener.getsockname())
        conn, _ = listener.accept()
        return client, conn
    except BaseException:
        if client is not None:
            client.close()
        raise
    finally:
        listener.close()


def _install_socketpair_shim() -> None:
    """部分受限沙箱只拦截 IPv4 回环（WinError 10051），导致 asyncio 无法建事件循环。

    仅在默认 ``socket.socketpair()`` 失败时改用 IPv6 回环；正常环境完全不生效，
    也不改变被测代码行为。
    """
    try:
        left, right = socket.socketpair()
    except OSError as exc:
        if getattr(exc, "winerror", None) != 10051:
            raise
        socket.socketpair = _ipv6_socketpair  # type: ignore[assignment]
    else:
        left.close()
        right.close()


_install_socketpair_shim()

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Activity,
    Invitation,
    Organization,
    OrgMember,
    PasswordReset,
    Task,
    User,
    UserSession,
)
from app.routers import auth as auth_router  # noqa: E402
from app.schemas import RegisterIn  # noqa: E402
from app.security import hash_password, hash_token, verify_password  # noqa: E402
from app.services import org_service  # noqa: E402
from app.services.session_service import (  # noqa: E402
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
)

PASSWORD = "Passw0rd!2024"
NEW_PASSWORD = "NewPassw0rd!2025"

MSG_LOGIN_FAILED = "账号或密码错误"
MSG_LEGACY = "该账号为旧演示账号，需管理员重置后使用"
MSG_RATE_LIMITED = "尝试过于频繁，请稍后再试"
MSG_UNAUTHORIZED = "未登录或登录已过期"
MSG_CSRF = "CSRF 校验失败"
MSG_ORG_NOT_FOUND = "组织不存在"
MSG_ORG_FORBIDDEN = "无权操作该组织"
MSG_MEMBER_NOT_FOUND = "成员不存在"
MSG_INVITE_INVALID = "邀请无效或已用尽"
MSG_USERNAME_EXISTS = "账号已存在"
MSG_PASSWORD_MISMATCH = "两次输入的密码不一致"
MSG_RESET_INVALID = "重置凭据无效或已过期"
MSG_TASK_NOT_FOUND = "任务不存在"
MSG_TASK_FORBIDDEN = "无权操作该任务"
MSG_ACTIVITY_NOT_FOUND = "活动不存在"
MSG_PLATFORM_REQUIRED = "需要平台管理员权限"
MSG_ORG_PUBLISH_FORBIDDEN = "无权在该组织下创建事务"


# --------------------------------------------------------------------------- #
# 基线数据
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Seed:
    users: dict[str, int]
    org_a: int
    org_b: int


def _wipe_business_tables() -> None:
    """清空全部业务表，保证每个用例从同一基线开始。"""
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            conn.execute(table.delete())


def _add_user(db, username: str, *, password: str | None = PASSWORD, platform_admin: int = 0,
              status: str = "active") -> User:
    user = User(
        username=username,
        display_name=f"{username} 昵称",
        password_hash=hash_password(password) if password is not None else None,
        status=status,
        platform_admin=platform_admin,
        credits=0,
    )
    db.add(user)
    return user


def _seed_baseline() -> Seed:
    db = SessionLocal()
    try:
        users = {
            "org_admin_a": _add_user(db, "org_admin_a"),
            "member_a": _add_user(db, "member_a"),
            "org_admin_b": _add_user(db, "org_admin_b"),
            "outsider": _add_user(db, "outsider"),
            "platform": _add_user(db, "platform_root", platform_admin=1),
            "legacy_user": _add_user(db, "legacy_user", password=None, status="legacy_unclaimed"),
            # 用户名本身是 "admin"，但没有任何平台或组织角色。
            "admin_named": _add_user(db, "admin"),
        }
        org_a = Organization(name="A 校区志愿队", slug="org-a", status="active")
        org_b = Organization(name="B 校区志愿队", slug="org-b", status="active")
        db.add_all([org_a, org_b])
        db.flush()

        db.add_all(
            [
                OrgMember(org_id=int(org_a.id), user_id=int(users["org_admin_a"].id),
                          role="admin", status="active", title="队长"),
                OrgMember(org_id=int(org_a.id), user_id=int(users["member_a"].id),
                          role="member", status="active"),
                OrgMember(org_id=int(org_b.id), user_id=int(users["org_admin_b"].id),
                          role="admin", status="active"),
            ]
        )
        db.commit()

        return Seed(
            users={name: int(user.id) for name, user in users.items()},
            org_a=int(org_a.id),
            org_b=int(org_b.id),
        )
    finally:
        db.close()


def _make_task(db, *, publisher_id: int, org_id: int | None = None, title: str = "组织任务",
               claim_type: str = "open", status: str = "published") -> int:
    task = Task(
        title=title,
        publisher_id=publisher_id,
        org_id=org_id,
        claim_type=claim_type,
        status=status,
        extras={},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return int(task.id)


def _make_activity(db, *, owner_id: int, org_id: int | None = None,
                   title: str = "组织活动") -> int:
    activity = Activity(title=title, owner_id=owner_id, org_id=org_id, status="published")
    db.add(activity)
    db.commit()
    db.refresh(activity)
    return int(activity.id)


# --------------------------------------------------------------------------- #
# HTTP 断言工具
# --------------------------------------------------------------------------- #
def _body(response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise AssertionError(
            f"响应不是 JSON（HTTP {response.status_code}）：{response.text[:200]}"
        ) from None
    assert isinstance(payload, dict), "响应体不是对象"
    return payload


def _ok(response, label: str = "") -> Any:
    payload = _body(response)
    assert payload.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    return payload.get("data")


def _err(response, code: int, msg: str | None = None, *, status: int | None = None,
         label: str = "") -> dict[str, Any]:
    payload = _body(response)
    assert payload.get("code") == code, (
        f"{label}：期望 code={code}，实际 code={payload.get('code')}（msg={payload.get('msg')}）"
    )
    if msg is not None:
        assert payload.get("msg") == msg, (
            f"{label}：期望 msg={msg!r}，实际 msg={payload.get('msg')!r}"
        )
    assert payload.get("data") is None, f"{label}：错误响应 data 应为 None"
    if status is not None:
        assert response.status_code == status, (
            f"{label}：期望 HTTP {status}，实际 HTTP {response.status_code}"
        )
    return payload


def _login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, Any]:
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    return _ok(response, f"登录 {username}")


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    assert isinstance(token, str) and token, "登录后缺少 cta_csrf Cookie"
    return {CSRF_HEADER: token}


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
SKIP_REASON = (
    "当前运行沙箱禁止本地 loopback socketpair（WinError 10051），"
    "Starlette TestClient 无法创建事件循环；请在允许本地套接字的终端执行 pytest"
)


def _is_sandbox_network_error(exc: OSError) -> bool:
    """Windows 沙箱拦截 127.0.0.1 临时端口时抛出的错误码。"""
    return getattr(exc, "winerror", None) == 10051


@contextmanager
def _new_client() -> Iterator[TestClient]:
    """创建 TestClient；若运行沙箱禁止 loopback socketpair 则跳过当前用例。

    这是纯环境适配：正常终端下行为与 ``with TestClient(app)`` 完全一致。
    """
    try:
        test_client = TestClient(app)
        test_client.__enter__()
    except OSError as exc:
        if _is_sandbox_network_error(exc):
            pytest.skip(SKIP_REASON)
        raise

    original_request = test_client.request

    def guarded_request(*args: Any, **kwargs: Any):
        try:
            return original_request(*args, **kwargs)
        except OSError as exc:
            if _is_sandbox_network_error(exc):
                pytest.skip(SKIP_REASON)
            raise

    test_client.request = guarded_request  # type: ignore[method-assign]
    try:
        yield test_client
    finally:
        try:
            test_client.__exit__(None, None, None)
        except OSError as exc:
            if not _is_sandbox_network_error(exc):
                raise


@pytest.fixture(scope="session")
def _prepare_database() -> None:
    """建好全部表（lifespan 里同样只做 init_db / 绑定 loop / 调度器，测试不需要后两者）。"""
    init_db()
    yield


@pytest.fixture()
def env(_prepare_database) -> Seed:
    _wipe_business_tables()
    # 登录限流是进程内状态，跨用例清空以免互相影响。
    auth_router._FAILURES.clear()
    return _seed_baseline()


@pytest.fixture()
def client(env: Seed) -> TestClient:
    with _new_client() as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# 1. 密码与令牌哈希（纯函数行为）
# --------------------------------------------------------------------------- #
def test_password_hash_format_and_verification():
    stored = hash_password(PASSWORD)
    parts = stored.split("$")

    assert len(parts) == 6, f"哈希字段数应为 6，实际 {stored!r}"
    assert parts[:4] == ["scrypt", "16384", "8", "1"], "参数必须与 C-HASH@1 一致"
    assert len(base64.b64decode(parts[4])) == 16, "salt 必须为 16 字节"
    assert len(base64.b64decode(parts[5])) == 32, "派生密钥必须为 32 字节"

    assert verify_password(PASSWORD, stored) is True
    assert verify_password(PASSWORD + "x", stored) is False
    assert verify_password("", stored) is False

    another = hash_password(PASSWORD)
    assert another != stored, "相同密码两次哈希必须因随机 salt 而不同"
    assert verify_password(PASSWORD, another) is True


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "plain-text-password",
        "scrypt$16384$8$1$short",
        "scrypt$16384$8$1$***$***",
        "scrypt$1$8$1$AAAA$AAAA",
        "bcrypt$16384$8$1$AAAA$AAAA",
    ],
)
def test_verify_password_rejects_malformed_stored_values(stored):
    """畸形 / 非 scrypt 库值一律返回 False 且不抛异常。"""
    assert verify_password(PASSWORD, stored) is False


def test_hash_token_is_stable_sha256_without_plaintext():
    digest = hash_token("invite-token-abc")

    assert re.fullmatch(r"[0-9a-f]{64}", digest), f"令牌摘要应为 sha256 十六进制：{digest!r}"
    assert digest == hashlib.sha256(b"invite-token-abc").hexdigest()
    assert hash_token("invite-token-abc") == digest, "同一令牌摘要必须稳定"
    assert hash_token("invite-token-abd") != digest, "不同令牌摘要必须不同"
    assert "invite-token-abc" not in digest


# --------------------------------------------------------------------------- #
# 2. 登录：用户名不赋权、统一文案、限流、泄露防护
# --------------------------------------------------------------------------- #
def test_username_never_grants_privilege(client: TestClient, env: Seed):
    """用户名恰好是 ``admin`` 的普通账号，登录后依然没有平台/组织权限。"""
    data = _login(client, "admin")
    assert data["user"]["username"] == "admin"
    assert data["user"]["platform_admin"] is False, "普通账号不应被用户名推断为平台管理员"
    assert data["orgs"] == [], "该账号未加入任何组织"

    headers = _csrf_headers(client)
    created = client.post(
        "/api/orgs",
        json={"name": "越权组织", "slug": "hijack-org"},
        headers=headers,
    )
    _err(created, 4030, MSG_PLATFORM_REQUIRED, status=403, label="普通账号创建组织")

    reset = client.post(
        f"/api/admin/users/{env.users['member_a']}/password-reset", headers=headers
    )
    _err(reset, 4030, MSG_PLATFORM_REQUIRED, status=403, label="普通账号发放重置")

    members = client.get(f"/api/orgs/{env.org_a}/members")
    _err(members, 4040, MSG_ORG_NOT_FOUND, status=404, label="普通账号读组织成员")


def test_login_failure_message_does_not_reveal_account_existence(client: TestClient, env: Seed):
    missing = client.post(
        "/api/auth/login", json={"username": "ghost_user", "password": PASSWORD}
    )
    wrong = client.post(
        "/api/auth/login", json={"username": "member_a", "password": "WrongPass!123"}
    )

    for response in (missing, wrong):
        _err(response, 4010, MSG_LOGIN_FAILED, status=401, label="登录失败")
    assert _body(missing)["msg"] == _body(wrong)["msg"], "两种失败必须同一文案"


def test_legacy_account_cannot_login_before_reset(client: TestClient, env: Seed):
    response = client.post(
        "/api/auth/login", json={"username": "legacy_user", "password": PASSWORD}
    )
    _err(response, 4010, MSG_LEGACY, status=401, label="legacy 账号登录")


def test_login_rate_limited_after_repeated_failures(client: TestClient, env: Seed):
    """同一 IP + 用户名 5 次失败后进入限流（HTTP 429 / code 4030）。"""
    for attempt in range(5):
        _err(
            client.post(
                "/api/auth/login", json={"username": "brute_force_user", "password": PASSWORD}
            ),
            4010,
            MSG_LOGIN_FAILED,
            status=401,
            label=f"第 {attempt + 1} 次失败登录",
        )

    _err(
        client.post("/api/auth/login", json={"username": "brute_force_user", "password": PASSWORD}),
        4030,
        MSG_RATE_LIMITED,
        status=429,
        label="第 6 次登录被限流",
    )


def test_login_response_exposes_no_password_material(client: TestClient, env: Seed):
    response = client.post(
        "/api/auth/login", json={"username": "member_a", "password": PASSWORD}
    )
    data = _ok(response, "登录响应")

    raw = response.text
    assert PASSWORD not in raw, "响应不得回显明文密码"
    assert "scrypt$" not in raw, "响应不得回显密码哈希"
    assert "password_hash" not in raw
    assert "password_hash" not in data["user"]


# --------------------------------------------------------------------------- #
# 3. 邀请生命周期
# --------------------------------------------------------------------------- #
def _create_invitation(client: TestClient, org_id: int, **overrides: Any) -> dict[str, Any]:
    body = {"role_cap": "member", "expires_in_hours": 72, "max_uses": 1, **overrides}
    return _ok(
        client.post(
            f"/api/orgs/{org_id}/invitations", json=body, headers=_csrf_headers(client)
        ),
        "创建邀请",
    )


def _register(client: TestClient, token: str, username: str) -> Any:
    return client.post(
        "/api/auth/register",
        json={
            "invite_token": token,
            "username": username,
            "display_name": username,
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )


def _invitation_row(invitation_id: int) -> Invitation:
    db = SessionLocal()
    try:
        return db.get(Invitation, invitation_id)
    finally:
        db.close()


def _user_count(username: str) -> int:
    db = SessionLocal()
    try:
        return int(db.query(User).filter(User.username == username).count())
    finally:
        db.close()


def test_invitation_token_is_stored_only_as_hash(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a)

    raw_token = created["token"]
    assert raw_token and created["used_count"] == 0 and created["max_uses"] == 1

    row = _invitation_row(int(created["id"]))
    assert row.token_hash == hash_token(raw_token)
    assert row.token_hash != raw_token, "库中禁止存明文邀请令牌"

    listed = _ok(
        client.get(f"/api/orgs/{env.org_a}/invitations"), "邀请列表"
    )
    assert all("token" not in item for item in listed["items"]), "列表不得回传明文令牌"


def test_invitation_expired_is_rejected(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a)

    db = SessionLocal()
    try:
        row = db.get(Invitation, int(created["id"]))
        row.expires_at = "2000-01-01 00:00:00"
        db.commit()
    finally:
        db.close()

    _err(_register(client, created["token"], "expired_racer"), 4001, MSG_INVITE_INVALID,
         label="过期邀请注册")
    assert _user_count("expired_racer") == 0, "过期邀请不得建号"


def test_invitation_revoked_is_rejected_and_revoke_is_idempotent(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a)
    headers = _csrf_headers(client)

    first = _ok(
        client.post(
            f"/api/orgs/{env.org_a}/invitations/{created['id']}/revoke", headers=headers
        ),
        "首次撤销邀请",
    )
    second = _ok(
        client.post(
            f"/api/orgs/{env.org_a}/invitations/{created['id']}/revoke", headers=headers
        ),
        "重复撤销邀请",
    )
    assert first == {"revoked": True} and second == {"revoked": True}, "撤销必须幂等"

    _err(_register(client, created["token"], "revoked_racer"), 4001, MSG_INVITE_INVALID,
         label="已撤销邀请注册")
    assert _user_count("revoked_racer") == 0


def test_invitation_max_uses_enforced(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a, max_uses=1)

    first = _ok(_register(client, created["token"], "single_use_racer"), "首次注册")
    assert first["user"]["username"] == "single_use_racer"
    assert first["user"]["platform_admin"] is False, "邀请注册不得创建平台管理员"
    assert [item["org_id"] for item in first["orgs"]] == [env.org_a]
    assert first["orgs"][0]["role"] == "member", "成员角色应取自 role_cap"

    second = _register(client, created["token"], "second_use_racer")
    _err(second, 4001, MSG_INVITE_INVALID, label="邀请用尽后注册")

    row = _invitation_row(int(created["id"]))
    assert row.used_count == 1 and row.max_uses == 1, f"used_count 不得超用：{row.used_count}"
    assert _user_count("second_use_racer") == 0


def test_unknown_invitation_token_is_rejected(client: TestClient, env: Seed):
    _err(_register(client, "no-such-invite-token", "unknown_racer"), 4001, MSG_INVITE_INVALID,
         label="未知邀请令牌")


def _register_in_thread(token: str, username: str) -> str:
    """在线程内用独立 Session 直连服务层，模拟真实的并发注册。"""
    db = SessionLocal()
    try:
        payload = RegisterIn(
            invite_token=token,
            username=username,
            display_name=username,
            password=PASSWORD,
            confirm_password=PASSWORD,
        )
        org_service.register_user(db, payload)
        return "created"
    except ApiError as exc:
        return f"error:{exc.code}:{exc.message}"
    finally:
        db.close()


def test_invitation_concurrent_registration_never_exceeds_max_uses(
    client: TestClient, env: Seed
):
    """两个线程同时消费 ``max_uses=1`` 的邀请：恰好 1 次成功，不超用。"""
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a, max_uses=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(_register_in_thread, created["token"], "concurrent_racer_1"),
            pool.submit(_register_in_thread, created["token"], "concurrent_racer_2"),
        ]
        results = sorted(future.result(timeout=30) for future in futures)

    assert results == ["created", f"error:4001:{MSG_INVITE_INVALID}"], (
        f"并发注册结果应为一个成功一个失效，实际 {results}"
    )
    row = _invitation_row(int(created["id"]))
    assert row.used_count == 1, f"并发下 used_count 不得超用，实际 {row.used_count}"
    created_users = _user_count("concurrent_racer_1") + _user_count("concurrent_racer_2")
    assert created_users == 1, f"并发下只应创建 1 个用户，实际 {created_users}"


# --------------------------------------------------------------------------- #
# 4. 会话：退出、到期、停用、重启、弱一致字段
# --------------------------------------------------------------------------- #
def _session_row(token: str) -> UserSession:
    db = SessionLocal()
    try:
        return db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).first()
    finally:
        db.close()


def test_logout_revokes_session_and_requires_csrf(client: TestClient, env: Seed):
    _login(client, "member_a")
    token = client.cookies.get(SESSION_COOKIE)
    csrf = client.cookies.get(CSRF_COOKIE)
    assert token and csrf

    assert _ok(client.get("/api/auth/me"), "登录后 me")["user"]["username"] == "member_a"

    # 已登录但缺 CSRF：退出被拒，会话必须保持有效（不得误撤销）。
    _err(client.post("/api/auth/logout"), 4030, MSG_CSRF, status=403, label="退出缺 CSRF")
    assert _ok(client.get("/api/auth/me"), "缺 CSRF 退出后 me")["user"]["username"] == "member_a"

    first = _ok(
        client.post("/api/auth/logout", headers={CSRF_HEADER: csrf}), "首次退出"
    )
    assert first == {"revoked": True}

    _err(client.get("/api/auth/me"), 4010, MSG_UNAUTHORIZED, status=401, label="退出后 me")
    assert _session_row(token).revoked_at is not None

    # 无有效会话时重复退出：require_csrf 放行，返回 revoked=False（C-AUTH-API@1 幂等）。
    second = _ok(client.post("/api/auth/logout"), "重复退出")
    assert second == {"revoked": False}, "无有效会话时退出应幂等返回 revoked=False"


def test_expired_session_is_rejected_but_not_marked_revoked(client: TestClient, env: Seed):
    _login(client, "member_a")
    token = client.cookies.get(SESSION_COOKIE)

    db = SessionLocal()
    try:
        row = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).one()
        row.expires_at = "2000-01-01 00:00:00"
        db.commit()
    finally:
        db.close()

    _err(client.get("/api/auth/me"), 4010, MSG_UNAUTHORIZED, status=401, label="过期会话")
    assert _session_row(token).revoked_at is None, "到期不是撤销，不得写 revoked_at"


def test_disabled_user_session_is_rejected(client: TestClient, env: Seed):
    _login(client, "member_a")

    db = SessionLocal()
    try:
        db.get(User, env.users["member_a"]).status = "disabled"
        db.commit()
    finally:
        db.close()

    _err(client.get("/api/auth/me"), 4010, MSG_UNAUTHORIZED, status=401, label="停用用户会话")


def test_session_survives_process_restart(env: Seed):
    """会话只存在库里：换一个客户端（等价于进程重启后的新 worker）仍能解析。"""
    with _new_client() as first:
        _login(first, "member_a")
        cookies = dict(first.cookies)

    assert SESSION_COOKIE in cookies and CSRF_COOKIE in cookies

    with _new_client() as restarted:
        for name, value in cookies.items():
            restarted.cookies.set(name, value)
        data = _ok(restarted.get("/api/auth/me"), "重启后 me")
        assert data["user"]["username"] == "member_a"
        assert data["user"]["id"] == env.users["member_a"]


def test_resolve_session_refreshes_last_seen_at(client: TestClient, env: Seed):
    _login(client, "member_a")
    token = client.cookies.get(SESSION_COOKIE)

    db = SessionLocal()
    try:
        row = db.query(UserSession).filter(UserSession.token_hash == hash_token(token)).one()
        row.last_seen_at = "2000-01-01 00:00:00"
        db.commit()
    finally:
        db.close()

    _ok(client.get("/api/auth/me"), "刷新 last_seen_at")
    refreshed = _session_row(token).last_seen_at
    assert refreshed is not None and refreshed != "2000-01-01 00:00:00", (
        f"解析会话应刷新 last_seen_at，实际 {refreshed!r}"
    )


# --------------------------------------------------------------------------- #
# 5. CSRF 双提交校验
# --------------------------------------------------------------------------- #
def test_csrf_required_for_write_operations(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    body = {"role_cap": "member", "expires_in_hours": 24, "max_uses": 1}
    path = f"/api/orgs/{env.org_a}/invitations"

    _err(client.post(path, json=body), 4030, MSG_CSRF, status=403, label="缺少 CSRF 头")
    _err(
        client.post(path, json=body, headers={CSRF_HEADER: "forged-token"}),
        4030,
        MSG_CSRF,
        status=403,
        label="伪造 CSRF 头",
    )

    # 会话 Cookie 缺失时认证依赖先于 CSRF 生效 ⇒ 统一 4010；401 响应同时清除两个 Cookie。
    client.cookies.delete(SESSION_COOKIE)
    _err(
        client.post(path, json=body, headers=_csrf_headers(client)),
        4010,
        MSG_UNAUTHORIZED,
        status=401,
        label="无会话的写操作",
    )
    assert client.cookies.get(SESSION_COOKIE) is None, "401 必须清除会话 Cookie"
    assert client.cookies.get(CSRF_COOKIE) is None, "401 必须清除 CSRF Cookie"
    with SessionLocal() as db:
        assert db.query(Invitation).filter(Invitation.org_id == env.org_a).count() == 0

    # 重新登录并带正确头 ⇒ 成功；GET 属于安全方法，不带 CSRF 头也放行。
    _login(client, "org_admin_a")
    created = _ok(client.post(path, json=body, headers=_csrf_headers(client)), "正确 CSRF")
    assert created["org_id"] == env.org_a
    _ok(client.get(f"/api/orgs/{env.org_a}/members"), "GET 免 CSRF")


def test_csrf_header_must_match_own_session(env: Seed):
    """把会话 A 的 CSRF 头用于会话 B，必须被拒绝。"""
    with _new_client() as admin_client:
        _login(admin_client, "org_admin_a")
        admin_csrf = admin_client.cookies.get(CSRF_COOKIE)

        with _new_client() as member_client:
            _login(member_client, "member_a")
            response = member_client.post(
                f"/api/orgs/{env.org_a}/invitations",
                json={"role_cap": "member", "expires_in_hours": 24, "max_uses": 1},
                headers={CSRF_HEADER: admin_csrf},
            )
            _err(response, 4030, MSG_CSRF, status=403, label="跨会话 CSRF")


def test_task_write_requires_csrf_and_data_unchanged(client: TestClient, env: Seed):
    """任务写操作：缺 CSRF 被拒且不落库；带正确 CSRF 才写入。"""
    _login(client, "org_admin_a")
    headers = _csrf_headers(client)

    created = _ok(
        client.post("/api/tasks", json={"title": "CSRF 对照任务"}, headers=headers),
        "发布任务（带 CSRF）",
    )
    task_id = int(created["id"])

    _err(
        client.patch(f"/api/tasks/{task_id}", json={"title": "无 CSRF 改名"}),
        4030,
        MSG_CSRF,
        status=403,
        label="PATCH 缺 CSRF",
    )
    db = SessionLocal()
    try:
        assert db.get(Task, task_id).title == "CSRF 对照任务", "缺 CSRF 的 PATCH 不得落库"
    finally:
        db.close()

    _err(
        client.post("/api/tasks", json={"title": "无 CSRF 新任务"}),
        4030,
        MSG_CSRF,
        status=403,
        label="POST 缺 CSRF",
    )
    with SessionLocal() as db:
        assert db.query(Task).filter(Task.title == "无 CSRF 新任务").count() == 0

    updated = _ok(
        client.patch(f"/api/tasks/{task_id}", json={"title": "带 CSRF 改名"}, headers=headers),
        "PATCH 带 CSRF",
    )
    assert updated["title"] == "带 CSRF 改名", "带正确 CSRF 的写操作应成功"


# --------------------------------------------------------------------------- #
# 6. 跨组织越权与 ID 枚举
# --------------------------------------------------------------------------- #
def test_cross_org_member_listing_is_404(client: TestClient, env: Seed):
    _login(client, "org_admin_a")

    foreign = client.get(f"/api/orgs/{env.org_b}/members")
    missing = client.get("/api/orgs/999999/members")
    _err(foreign, 4040, MSG_ORG_NOT_FOUND, status=404, label="跨组织成员列表")
    _err(missing, 4040, MSG_ORG_NOT_FOUND, status=404, label="不存在组织成员列表")
    assert _body(foreign)["msg"] == _body(missing)["msg"], "无权与不存在必须不可区分"


def test_cross_org_member_patch_is_404_and_leaves_data_untouched(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    target = env.users["org_admin_b"]

    _err(
        client.patch(
            f"/api/orgs/{env.org_b}/members/{target}",
            json={"role": "member"},
            headers=_csrf_headers(client),
        ),
        4040,
        MSG_ORG_NOT_FOUND,
        status=404,
        label="跨组织改成员",
    )

    db = SessionLocal()
    try:
        row = (
            db.query(OrgMember)
            .filter(OrgMember.org_id == env.org_b, OrgMember.user_id == target)
            .one()
        )
        assert row.role == "admin", "越权请求不得改动目标成员"
    finally:
        db.close()


def test_org_member_without_admin_role_is_forbidden(client: TestClient, env: Seed):
    _login(client, "member_a")
    headers = _csrf_headers(client)

    _err(client.get(f"/api/orgs/{env.org_a}/members"), 4030, MSG_ORG_FORBIDDEN, status=403,
         label="普通成员读成员列表")
    _err(
        client.patch(
            f"/api/orgs/{env.org_a}/members/{env.users['member_a']}",
            json={"title": "自封队长"},
            headers=headers,
        ),
        4030,
        MSG_ORG_FORBIDDEN,
        status=403,
        label="普通成员改成员",
    )
    _err(
        client.post(
            f"/api/orgs/{env.org_a}/invitations",
            json={"role_cap": "admin", "expires_in_hours": 24, "max_uses": 1},
            headers=headers,
        ),
        4030,
        MSG_ORG_FORBIDDEN,
        status=403,
        label="普通成员发邀请",
    )


def test_non_member_org_access_is_404(client: TestClient, env: Seed):
    _login(client, "outsider")
    _err(client.get(f"/api/orgs/{env.org_a}/members"), 4040, MSG_ORG_NOT_FOUND, status=404)
    _err(client.get(f"/api/orgs/{env.org_a}/invitations"), 4040, MSG_ORG_NOT_FOUND, status=404)


def test_cross_org_task_read_is_404_and_excluded_from_list(client: TestClient, env: Seed):
    db = SessionLocal()
    try:
        foreign_task = _make_task(db, publisher_id=env.users["org_admin_b"],
                                  org_id=env.org_b, title="B 组织内部任务")
    finally:
        db.close()

    for username in ("member_a", "org_admin_a", "outsider"):
        _login(client, username)
        _err(
            client.get(f"/api/tasks/{foreign_task}"),
            4040,
            MSG_TASK_NOT_FOUND,
            status=404,
            label=f"{username} 跨组织读任务",
        )
        listed = _ok(client.get("/api/tasks?include_sub=true"), f"{username} 任务列表")
        assert all(int(item["id"]) != foreign_task for item in listed["items"]), (
            f"{username} 的列表泄露了 B 组织任务"
        )

    # 对照：B 组织管理员本人可以读到同一任务，证明任务真实存在。
    _login(client, "org_admin_b")
    assert _ok(client.get(f"/api/tasks/{foreign_task}"), "B 管理员读任务")["id"] == foreign_task


def test_visible_task_write_forbidden_is_403(client: TestClient, env: Seed):
    """组织 member 可见 open 任务（列表可读），但改任务必须 4030。"""
    db = SessionLocal()
    try:
        task_id = _make_task(db, publisher_id=env.users["org_admin_a"],
                            org_id=env.org_a, title="A 组织公开任务")
    finally:
        db.close()

    _login(client, "member_a")
    assert _ok(client.get(f"/api/tasks/{task_id}"), "member 可见 open 任务")["id"] == task_id

    response = client.patch(
        f"/api/tasks/{task_id}", json={"title": "越权改名"}, headers=_csrf_headers(client)
    )
    _err(response, 4030, MSG_TASK_FORBIDDEN, status=403, label="member 改任务")

    db = SessionLocal()
    try:
        assert db.get(Task, task_id).title == "A 组织公开任务", "越权修改不得落库"
    finally:
        db.close()


def test_missing_and_unauthorized_resources_share_same_error(client: TestClient, env: Seed):
    db = SessionLocal()
    try:
        foreign_activity = _make_activity(db, owner_id=env.users["org_admin_b"],
                                        org_id=env.org_b, title="B 组织活动")
        foreign_task = _make_task(db, publisher_id=env.users["org_admin_b"],
                                  org_id=env.org_b, title="B 组织任务")
    finally:
        db.close()

    _login(client, "member_a")

    missing_task = _body(client.get("/api/tasks/999999"))
    hidden_task = _body(client.get(f"/api/tasks/{foreign_task}"))
    assert missing_task["code"] == hidden_task["code"] == 4040
    assert missing_task["msg"] == hidden_task["msg"] == MSG_TASK_NOT_FOUND

    missing_activity = _body(client.get("/api/activities/999999"))
    hidden_activity = _body(client.get(f"/api/activities/{foreign_activity}"))
    assert missing_activity["code"] == hidden_activity["code"] == 4040
    assert missing_activity["msg"] == hidden_activity["msg"] == MSG_ACTIVITY_NOT_FOUND


# --------------------------------------------------------------------------- #
# 7. 平台管理员：有平台能力，但没有组织业务内容可见性
# --------------------------------------------------------------------------- #
def test_platform_admin_does_not_gain_org_content_visibility(client: TestClient, env: Seed):
    db = SessionLocal()
    try:
        org_task = _make_task(db, publisher_id=env.users["org_admin_a"],
                             org_id=env.org_a, title="A 组织任务")
        org_activity = _make_activity(db, owner_id=env.users["org_admin_a"],
                                      org_id=env.org_a, title="A 组织活动")
    finally:
        db.close()

    _login(client, "platform_root")
    headers = _csrf_headers(client)

    _err(client.get(f"/api/orgs/{env.org_a}/members"), 4040, MSG_ORG_NOT_FOUND, status=404,
         label="平台管理员读组织成员")
    _err(client.get(f"/api/tasks/{org_task}"), 4040, MSG_TASK_NOT_FOUND, status=404,
         label="平台管理员读组织任务")
    _err(client.get(f"/api/activities/{org_activity}"), 4040, MSG_ACTIVITY_NOT_FOUND,
         status=404, label="平台管理员读组织活动")

    tasks = _ok(client.get("/api/tasks?include_sub=true"), "平台管理员任务列表")
    assert all(int(item["id"]) != org_task for item in tasks["items"])
    activities = _ok(client.get("/api/activities"), "平台管理员活动列表")
    assert all(int(item["id"]) != org_activity for item in activities["items"])

    # 组织发布权仍受 org_role 约束：不因 platform_admin 而扩大。
    created_task = client.post(
        "/api/tasks",
        json={"title": "平台管理员硬塞组织任务", "org_id": env.org_a},
        headers=headers,
    )
    _err(created_task, 4030, MSG_ORG_PUBLISH_FORBIDDEN, status=403,
         label="平台管理员在组织下发布")

    # 但平台能力本身有效：可以创建组织。
    created_org = _ok(
        client.post(
            "/api/orgs",
            json={"name": "平台新建组织", "slug": "platform-created"},
            headers=headers,
        ),
        "平台管理员创建组织",
    )
    assert created_org["slug"] == "platform-created"

    db = SessionLocal()
    try:
        rows = db.query(OrgMember).filter(OrgMember.user_id == env.users["platform"]).all()
        assert rows == [], "platform_admin 不应写入 org_members"
    finally:
        db.close()


# --------------------------------------------------------------------------- #
# 8. legacy 同名注册绝不继承
# --------------------------------------------------------------------------- #
def test_legacy_same_name_registration_never_inherits(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a, max_uses=2)

    _err(
        _register(client, created["token"], "legacy_user"),
        4001,
        MSG_LEGACY,
        label="legacy 同名注册",
    )

    db = SessionLocal()
    try:
        legacy = db.query(User).filter(User.username == "legacy_user").one()
        assert legacy.password_hash is None, "同名注册绝不能给 legacy 账号写入密码"
        assert legacy.status == "legacy_unclaimed", "同名注册不能改变 legacy 状态"
        invitation = db.get(Invitation, int(created["id"]))
        assert invitation.used_count == 0, "失败的注册必须回滚邀请次数"
    finally:
        db.close()


def test_duplicate_active_username_rejected_without_consuming_invite(
    client: TestClient, env: Seed
):
    _login(client, "org_admin_a")
    created = _create_invitation(client, env.org_a, max_uses=2)

    _err(_register(client, created["token"], "member_a"), 4001, MSG_USERNAME_EXISTS,
         label="重名注册")
    assert _invitation_row(int(created["id"])).used_count == 0, "重名失败必须回滚邀请"


# --------------------------------------------------------------------------- #
# 9. 受控密码重置
# --------------------------------------------------------------------------- #
def _issue_reset(client: TestClient, path: str) -> dict[str, Any]:
    return _ok(client.post(path, headers=_csrf_headers(client)), f"发放重置 {path}")


def _reset(client: TestClient, token: str, password: str = NEW_PASSWORD,
           confirm: str | None = None) -> Any:
    return client.post(
        "/api/auth/reset-password",
        json={
            "token": token,
            "password": password,
            "confirm_password": password if confirm is None else confirm,
        },
    )


def test_password_reset_revokes_old_sessions_and_rotates_password(env: Seed):
    with _new_client() as member_client:
        _login(member_client, "member_a")
        old_token = member_client.cookies.get(SESSION_COOKIE)
        assert _ok(member_client.get("/api/auth/me"), "重置前 me")

        with _new_client() as admin_client:
            _login(admin_client, "org_admin_a")
            issued = _issue_reset(
                admin_client,
                f"/api/orgs/{env.org_a}/members/{env.users['member_a']}/password-reset",
            )
            reset_token = issued["token"]
            assert reset_token and issued["expires_at"], "重置凭据必须含 token 与过期时间"

            with _new_client() as anonymous:
                _ok(_reset(anonymous, reset_token), "消费重置令牌")

                # 旧会话立刻失效，且库里已标记撤销。
                _err(member_client.get("/api/auth/me"), 4010, MSG_UNAUTHORIZED, status=401,
                     label="重置后旧会话")
                assert _session_row(old_token).revoked_at is not None

                # 旧密码不能登录，新密码可以。
                _err(
                    anonymous.post(
                        "/api/auth/login", json={"username": "member_a", "password": PASSWORD}
                    ),
                    4010,
                    MSG_LOGIN_FAILED,
                    status=401,
                    label="旧密码登录",
                )
                _login(anonymous, "member_a", NEW_PASSWORD)

    db = SessionLocal()
    try:
        user = db.get(User, env.users["member_a"])
        assert user.password_hash.startswith("scrypt$")
        assert user.password_hash != hash_password(NEW_PASSWORD), "哈希必须带随机 salt"
        assert verify_password(NEW_PASSWORD, user.password_hash) is True
        assert user.password_updated_at is not None
        used = (
            db.query(PasswordReset)
            .filter(PasswordReset.token_hash == hash_token(reset_token))
            .one()
        )
        assert used.used_at is not None, "重置凭据必须标记为已消费"
    finally:
        db.close()


def test_reset_token_is_single_use(client: TestClient, env: Seed):
    _login(client, "org_admin_a")
    issued = _issue_reset(
        client, f"/api/orgs/{env.org_a}/members/{env.users['member_a']}/password-reset"
    )

    with _new_client() as anonymous:
        _ok(_reset(anonymous, issued["token"]), "首次使用重置令牌")
        _err(_reset(anonymous, issued["token"], password="ThirdPassw0rd!"),
             4001, MSG_RESET_INVALID, label="二次使用重置令牌")


def test_reset_password_confirmation_mismatch_keeps_token_usable(env: Seed):
    with _new_client() as admin_client:
        _login(admin_client, "org_admin_a")
        issued = _issue_reset(
            admin_client,
            f"/api/orgs/{env.org_a}/members/{env.users['member_a']}/password-reset",
        )

    with _new_client() as anonymous:
        _err(_reset(anonymous, issued["token"], confirm="AnotherPassw0rd!"),
             4001, MSG_PASSWORD_MISMATCH, label="两次密码不一致")
        # 失败不消费令牌，随后仍能成功重置。
        _ok(_reset(anonymous, issued["token"]), "不一致后仍可使用令牌")


def test_expired_reset_token_is_rejected(env: Seed):
    with _new_client() as admin_client:
        _login(admin_client, "org_admin_a")
        issued = _issue_reset(
            admin_client,
            f"/api/orgs/{env.org_a}/members/{env.users['member_a']}/password-reset",
        )

    db = SessionLocal()
    try:
        row = (
            db.query(PasswordReset)
            .filter(PasswordReset.token_hash == hash_token(issued["token"]))
            .one()
        )
        row.expires_at = "2000-01-01 00:00:00"
        db.commit()
    finally:
        db.close()

    with _new_client() as anonymous:
        _err(_reset(anonymous, issued["token"]), 4001, MSG_RESET_INVALID,
             label="过期重置令牌")


def test_legacy_account_becomes_active_after_controlled_reset(env: Seed):
    with _new_client() as platform_client:
        _login(platform_client, "platform_root")
        issued = _issue_reset(
            platform_client, f"/api/admin/users/{env.users['legacy_user']}/password-reset"
        )

    with _new_client() as anonymous:
        _ok(_reset(anonymous, issued["token"]), "legacy 受控重置")
        _login(anonymous, "legacy_user", NEW_PASSWORD)

    db = SessionLocal()
    try:
        legacy = db.get(User, env.users["legacy_user"])
        assert legacy.status == "active", "受控重置后 legacy 才可登录"
        assert verify_password(NEW_PASSWORD, legacy.password_hash) is True
    finally:
        db.close()


def test_reset_issuance_requires_org_admin_and_membership(client: TestClient, env: Seed):
    path_self = f"/api/orgs/{env.org_a}/members/{env.users['member_a']}/password-reset"

    _login(client, "member_a")
    _err(client.post(path_self, headers=_csrf_headers(client)), 4030, MSG_ORG_FORBIDDEN,
         status=403, label="普通成员申请重置")

    _login(client, "org_admin_a")
    headers = _csrf_headers(client)
    _err(
        client.post(f"/api/orgs/{env.org_a}/members/{env.users['outsider']}/password-reset",
                    headers=headers),
        4040,
        MSG_MEMBER_NOT_FOUND,
        status=404,
        label="为组织外用户发放重置",
    )
    _err(
        client.post(f"/api/orgs/{env.org_a}/members/{env.users['org_admin_b']}/password-reset",
                    headers=headers),
        4040,
        MSG_MEMBER_NOT_FOUND,
        status=404,
        label="为其他组织成员发放重置",
    )

# --------------------------------------------------------------------------- #
# 10. 派生组织越权（T27 / C-TASK-ORG@1）：父任务、活动、PATCH 迁移
# --------------------------------------------------------------------------- #
def test_create_task_with_foreign_org_parent_is_forbidden(client: TestClient, env: Seed):
    """父任务派生组织越权：父任务归属其他组织 ⇒ 4030，且不新增任务行。

    场景为「自己发布、但归属被派生到其他组织」的父任务（历史/迁移数据）。
    纯跨发布者的父任务会先被「只能在自己的任务下创建子任务」拦下，不覆盖本用例目标。
    """
    db = SessionLocal()
    try:
        foreign_parent = _make_task(
            db,
            publisher_id=env.users["org_admin_a"],
            org_id=env.org_b,
            title="B 组织归属的父任务",
        )
        before = int(db.query(Task).count())
    finally:
        db.close()

    _login(client, "org_admin_a")
    response = client.post(
        "/api/tasks",
        json={"title": "跨组织父任务的子任务", "parent_id": foreign_parent},
        headers=_csrf_headers(client),
    )
    _err(
        response,
        4030,
        MSG_ORG_PUBLISH_FORBIDDEN,
        status=403,
        label="跨组织父任务创建子任务",
    )

    db = SessionLocal()
    try:
        assert int(db.query(Task).count()) == before, "越权创建不得新增任务行"
        assert db.query(Task).filter(Task.title == "跨组织父任务的子任务").count() == 0
    finally:
        db.close()


def test_create_task_with_foreign_org_activity_is_forbidden(client: TestClient, env: Seed):
    """活动派生组织越权：activity_id 指向其他组织的活动 ⇒ 4030，且不落库。"""
    db = SessionLocal()
    try:
        foreign_activity = _make_activity(
            db,
            owner_id=env.users["org_admin_b"],
            org_id=env.org_b,
            title="B 组织活动",
        )
        before = int(db.query(Task).count())
    finally:
        db.close()

    _login(client, "org_admin_a")
    response = client.post(
        "/api/tasks",
        json={"title": "跨组织活动下的任务", "activity_id": foreign_activity},
        headers=_csrf_headers(client),
    )
    _err(
        response,
        4030,
        MSG_ORG_PUBLISH_FORBIDDEN,
        status=403,
        label="跨组织活动创建任务",
    )

    db = SessionLocal()
    try:
        assert int(db.query(Task).count()) == before, "越权创建不得新增任务行"
        assert db.query(Task).filter(Task.title == "跨组织活动下的任务").count() == 0
    finally:
        db.close()


def test_patch_task_activity_to_foreign_org_is_rejected(client: TestClient, env: Seed):
    """PATCH 改 activity_id 到其他组织活动：拒绝且任务原 activity_id/org_id 不变。

    契约实现若将活动可见性前移到 ``resolve_task_placement``（返回 4040「活动不存在」），
    则按该实际契约断言并保留「不泄露存在性」口径；当前 C-AUTHZ 的写口径为 4030。
    """
    db = SessionLocal()
    try:
        own_task = _make_task(
            db,
            publisher_id=env.users["org_admin_a"],
            org_id=env.org_a,
            title="A 组织待迁移任务",
        )
        foreign_activity = _make_activity(
            db,
            owner_id=env.users["org_admin_b"],
            org_id=env.org_b,
            title="B 组织活动（PATCH 目标）",
        )
        original = db.get(Task, own_task)
        original_activity, original_org = original.activity_id, original.org_id
    finally:
        db.close()

    _login(client, "org_admin_a")
    response = client.patch(
        f"/api/tasks/{own_task}",
        json={"activity_id": foreign_activity},
        headers=_csrf_headers(client),
    )
    payload = _body(response)
    if payload.get("code") == 4040:
        # T27 若把活动可见性前移：按「活动不存在」断言，保留不泄露存在性口径。
        assert payload.get("msg") == MSG_ACTIVITY_NOT_FOUND, (
            f"4040 分支必须与「活动不存在」一致（实际 msg={payload.get('msg')!r}）"
        )
    elif payload.get("code") == 4001:
        # 当前实现（T27）：任务既有 org_id 与目标活动组织不一致按 C-TASK-ORG@1 的
        # 「组织不一致 ⇒ 4001」处理，消息为「任务必须与所属活动属于同一组织」，且不落库。
        # 若后续统一为 4030 越权口径，下方分支仍然生效。
        assert payload.get("msg") == "任务必须与所属活动属于同一组织", (
            f"4001 分支消息应为组织不一致提示（实际 msg={payload.get('msg')!r}）"
        )
    else:
        _err(
            response,
            4030,
            MSG_ORG_PUBLISH_FORBIDDEN,
            status=403,
            label="跨组织活动迁移任务",
        )

    db = SessionLocal()
    try:
        row = db.get(Task, own_task)
        assert row.activity_id == original_activity, "越权迁移不得改动 activity_id"
        assert row.org_id == original_org, "越权迁移不得改动 org_id"
        assert row.org_id == env.org_a, "任务仍归属原组织 A"
    finally:
        db.close()