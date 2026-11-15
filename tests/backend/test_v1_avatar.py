#!/usr/bin/env python
"""头像接口后端回归（契约 `C-AVATAR-API@1` 修订版）。

覆盖：上传成功（统一 ``{code,msg,data}`` 包装 + 持久化 + 同值幂等）、清除
（``null`` 与空串）、非法前缀 / 不可解码 base64 / 超长一律 4001 且不改变原值、
缺 CSRF 4030、未登录 4010。全部通过真实 HTTP 验证，不做源码字符串检查。

隔离性：导入 ``app`` 之前把 ``DATABASE_PATH`` 指向 ``tempfile.mkdtemp`` 下的独立
SQLite，并强制 ``MAAS_MOCK=1`` / ``RUN_SCHEDULER=0``；每个用例清空业务表后重建
基线数据，不触碰 ``backend/campus.db``。

运行：``pytest tests/backend/test_v1_avatar.py -v``
"""

from __future__ import annotations

import base64
import os
import socket
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-avatar-"))
_TEST_DB_PATH = _TMP_DIR / "avatar.db"

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
    type = socket.SOCK_STREAM if type is None else type
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
    """受限沙箱只拦截 IPv4 回环（WinError 10051）时改用 IPv6 回环。"""
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
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER  # noqa: E402

PASSWORD = "Passw0rd!2024"
USERNAME = "avatar_user"

MSG_INVALID_AVATAR = "头像格式无效"
MSG_UNAUTHORIZED = "未登录或登录已过期"
MSG_CSRF = "CSRF 校验失败"

PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(
    b"\x89PNG\r\n\x1a\navatar-bytes"
).decode("ascii")
JPEG_DATA_URL = "data:image/jpeg;base64," + base64.b64encode(b"jpeg-bytes").decode("ascii")
WEBP_DATA_URL = "data:image/webp;base64," + base64.b64encode(b"webp-bytes").decode("ascii")

#: 契约上限：总长度 ≤ 280000 字符。
AVATAR_MAX_CHARS = 280_000


# --------------------------------------------------------------------------- #
# 基线数据与 HTTP 工具
# --------------------------------------------------------------------------- #
def _wipe_business_tables() -> None:
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            conn.execute(table.delete())


def _seed_user() -> int:
    db = SessionLocal()
    try:
        user = User(
            username=USERNAME,
            display_name="头像用户",
            password_hash=hash_password(PASSWORD),
            credits=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return int(user.id)
    finally:
        db.close()


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


def _login(client: TestClient) -> dict[str, Any]:
    return _ok(
        client.post("/api/auth/login", json={"username": USERNAME, "password": PASSWORD}),
        "登录",
    )


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    assert isinstance(token, str) and token, "登录后缺少 cta_csrf Cookie"
    return {CSRF_HEADER: token}


def _patch_avatar(client: TestClient, value: str | None, *, headers: dict[str, str] | None = None):
    return client.patch(
        "/api/auth/avatar",
        json={"avatar": value},
        headers=_csrf_headers(client) if headers is None else headers,
    )


def _current_avatar(client: TestClient) -> str | None:
    data = _ok(client.get("/api/auth/me"), "读取 me")
    return data["user"]["avatar"]


# --------------------------------------------------------------------------- #
# 夹具
# --------------------------------------------------------------------------- #
SKIP_REASON = (
    "当前运行沙箱禁止本地 loopback socketpair（WinError 10051），"
    "Starlette TestClient 无法创建事件循环；请在允许本地套接字的终端执行 pytest"
)


def _is_sandbox_network_error(exc: OSError) -> bool:
    return getattr(exc, "winerror", None) == 10051


@contextmanager
def _new_client() -> Iterator[TestClient]:
    """创建 TestClient；若运行沙箱禁止 loopback socketpair 则跳过当前用例。"""
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
    init_db()
    yield


@pytest.fixture()
def client(_prepare_database) -> Iterator[TestClient]:
    _wipe_business_tables()
    _seed_user()
    with _new_client() as test_client:
        yield test_client


# --------------------------------------------------------------------------- #
# 上传与清除
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("data_url", [PNG_DATA_URL, JPEG_DATA_URL, WEBP_DATA_URL])
def test_upload_avatar_wraps_ok_and_persists(client: TestClient, data_url: str):
    _login(client)

    payload = _body(_patch_avatar(client, data_url))
    assert set(payload) == {"code", "msg", "data"}, "必须沿用 {code,msg,data} 统一包装"
    assert payload["code"] == 0
    assert payload["data"]["avatar"] == data_url
    assert payload["data"]["username"] == USERNAME

    assert _current_avatar(client) == data_url, "上传后必须落库"

    # 同值重复 PATCH 结果一致（整体替换、幂等）。
    again = _body(_patch_avatar(client, data_url))
    assert again["code"] == 0 and again["data"]["avatar"] == data_url


def test_upload_replaces_previous_avatar(client: TestClient):
    _login(client)
    _ok(_patch_avatar(client, PNG_DATA_URL), "首次上传")
    _ok(_patch_avatar(client, WEBP_DATA_URL), "替换上传")
    assert _current_avatar(client) == WEBP_DATA_URL


@pytest.mark.parametrize("value", [None, ""])
def test_clear_avatar_with_null_or_empty(client: TestClient, value: str | None):
    _login(client)
    _ok(_patch_avatar(client, PNG_DATA_URL), "上传")
    data = _ok(_patch_avatar(client, value), "清除")
    assert data["avatar"] is None
    assert _current_avatar(client) is None


# --------------------------------------------------------------------------- #
# 4001 校验失败：不写库、不改变原值
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("value", "label"),
    [
        ("data:image/gif;base64," + base64.b64encode(b"gif").decode("ascii"), "非法前缀"),
        ("https://example.com/avatar.png", "非 data URL"),
        ("data:image/png;base64,not-base64!!", "base64 段不可解码"),
    ],
)
def test_invalid_avatar_rejected_without_change(client: TestClient, value: str, label: str):
    _login(client)
    _ok(_patch_avatar(client, PNG_DATA_URL), "上传基线")
    _err(_patch_avatar(client, value), 4001, MSG_INVALID_AVATAR, label=label)
    assert _current_avatar(client) == PNG_DATA_URL, f"{label}：失败不得改变原头像"


def test_oversized_avatar_rejected_without_change(client: TestClient):
    _login(client)
    _ok(_patch_avatar(client, PNG_DATA_URL), "上传基线")
    oversized = "data:image/png;base64," + "A" * AVATAR_MAX_CHARS
    assert len(oversized) > AVATAR_MAX_CHARS
    _err(_patch_avatar(client, oversized), 4001, MSG_INVALID_AVATAR, label="超长")
    assert _current_avatar(client) == PNG_DATA_URL, "超长失败不得改变原头像"


# --------------------------------------------------------------------------- #
# 鉴权与 CSRF
# --------------------------------------------------------------------------- #
def test_missing_csrf_rejected(client: TestClient):
    _login(client)
    _ok(_patch_avatar(client, PNG_DATA_URL), "上传基线")

    _err(
        _patch_avatar(client, WEBP_DATA_URL, headers={}),
        4030,
        MSG_CSRF,
        status=403,
        label="缺少 CSRF 头",
    )
    assert _current_avatar(client) == PNG_DATA_URL, "CSRF 失败不得改变原头像"


def test_unauthenticated_rejected(client: TestClient):
    response = client.patch("/api/auth/avatar", json={"avatar": PNG_DATA_URL})
    _err(response, 4010, MSG_UNAUTHORIZED, status=401, label="未登录")