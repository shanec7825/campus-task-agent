#!/usr/bin/env python
"""S4 AI 任务查询与文档上下文测试（契约 `C-AI-TASK-QUERY@1` / `C-AI-DOC-CONTEXT@1`）。

覆盖范围：

1. ``task_query_service.build_task_context`` 关键词命中优先，且上下文含 SOP 与验收要求；
2. 逾期 / 待验收意图命中对应任务，最新提交与验收结果进入上下文；
3. 无关键词命中时按截止时间退化为最近任务（保持旧行为）；
4. 活动 / 任务作用域只取作用域内任务；学生看不到他人与外组织任务；
5. mock 回答列出「参考资料」并带 ``kind="doc"`` citation，未开放资料不进入
   上下文、citation 或自动收藏；
6. 回答后 ``record_citations`` 失败不影响回答；``request_id`` 重放不重复收藏、不重复扣额度；
7. 旧 citation 缺少 ``kind`` / ``resource_id`` 时仍按 ``task`` 正常解析。

隔离性：导入 ``app`` 前设置临时 ``DATABASE_PATH``、``ORG_LIBRARY_UPLOAD_ROOT``、
``MAAS_MOCK=1``、``MAAS_API_KEY=''``、``RUN_SCHEDULER=0``；不触碰 ``backend/campus.db``
与 ``backend/uploads``，不产生真实模型调用。

可独立运行：``python -m pytest tests/backend/test_v1_ai_context.py -q``。
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = PROJECT_ROOT / "backend"

_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus-v1-ai-context-"))
_TEST_DB_PATH = _TMP_DIR / "ai_context.db"
_UPLOAD_ROOT = _TMP_DIR / "org-uploads"

os.environ["DATABASE_PATH"] = str(_TEST_DB_PATH)
os.environ["ORG_LIBRARY_UPLOAD_ROOT"] = str(_UPLOAD_ROOT)
os.environ["MAAS_MOCK"] = "1"
os.environ["MAAS_API_KEY"] = ""
os.environ["RUN_SCHEDULER"] = "0"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import LibraryRef, OrgMember, Organization, Task, TaskMember, TaskSubmission, User  # noqa: E402
from app.schemas import AiCitation, AiMessageOut  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import ai_service, kb_service, library_ref_service, task_query_service  # noqa: E402
from app.services.session_service import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE  # noqa: E402

PASSWORD = "TestPass123!"
DOC_TEXT = "秋季招聘现场布置需要准备物资清单与展位确认，提前一天完成场地检查。"
SECRET_CONTENT = "学生一私密成果内容仅审阅者可见"
SECRET_URL = "https://private.example/secret"
SECRET_FILE = "secret-submission.pdf"
SECRET_REASON = "学生一私密的退回原因"

EXPECTED_TASK_KEYS = {
    "task_id",
    "title",
    "activity_name",
    "status",
    "deadline",
    "location",
    "sop",
    "acceptance",
    "latest_submission",
    "review_result",
    "score",
}


@dataclass
class _Ctx:
    client: TestClient
    admin: dict[str, str]
    stu1: dict[str, str]
    stu2: dict[str, str]
    other_admin: dict[str, str]
    org_id: int
    other_org_id: int
    activity_id: int
    task_keyword: int
    task_overdue: int
    task_review: int
    task_plain: int
    task_none: int
    task_solo: int
    task_other: int
    task_secret: int
    open_resource_id: int
    closed_resource_id: int
    foreign_resource_id: int


# --------------------------------------------------------------------------- #
# HTTP / 数据辅助
# --------------------------------------------------------------------------- #
def _payload(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
) -> tuple[int, dict]:
    response = client.request(method, path, json=body, headers=headers or {})
    try:
        parsed = response.json()
    except ValueError:  # pragma: no cover - 非 JSON 说明发生未捕获异常
        raise AssertionError(f"{method} {path}：响应不是 JSON（HTTP {response.status_code}）") from None
    assert isinstance(parsed, dict), f"{method} {path}：响应体不是对象"
    return response.status_code, parsed


def _ok(
    client: TestClient,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    body: Any = None,
    label: str = "",
) -> dict:
    status, parsed = _payload(client, method, path, headers=headers, body=body)
    assert status == 200, f"{label}：期望 HTTP 200，实际 HTTP {status}（{parsed.get('msg')}）"
    assert parsed.get("code") == 0, (
        f"{label}：期望 code=0，实际 code={parsed.get('code')}（msg={parsed.get('msg')}）"
    )
    data = parsed.get("data")
    assert isinstance(data, dict), f"{label}：data 不是对象（{type(data).__name__}）"
    return data


def _session_headers(response) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in response.headers.get_list("set-cookie"):
        name, _, rest = raw.partition("=")
        if name.strip() in {SESSION_COOKIE, CSRF_COOKIE}:
            values[name.strip()] = rest.split(";", 1)[0].strip()
    session = values.get(SESSION_COOKIE)
    csrf = values.get(CSRF_COOKIE)
    assert session and csrf, "登录响应缺少会话 Cookie"
    return {"Cookie": f"{SESSION_COOKIE}={session}; {CSRF_COOKIE}={csrf}", CSRF_HEADER: csrf}


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    parsed = response.json()
    assert response.status_code == 200 and parsed.get("code") == 0, f"登录 {username} 失败"
    headers = _session_headers(response)
    client.cookies.clear()
    return headers


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


def _ensure_org(name: str, slug: str, roles: dict[int, str]) -> int:
    with SessionLocal() as db:
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if org is None:
            org = Organization(name=name, slug=slug, status="active")
            db.add(org)
            db.flush()
        for user_id, role in roles.items():
            row = (
                db.query(OrgMember)
                .filter(OrgMember.org_id == int(org.id), OrgMember.user_id == int(user_id))
                .first()
            )
            if row is None:
                db.add(OrgMember(org_id=int(org.id), user_id=int(user_id), role=role, status="active"))
            else:
                row.role = role
                row.status = "active"
        db.commit()
        db.refresh(org)
        return int(org.id)


def _user(username: str) -> User:
    with SessionLocal() as db:
        return db.query(User).filter(User.username == username).one()


def _create_task(client: TestClient, headers: dict[str, str], body: dict, label: str) -> int:
    created = _ok(client, "POST", "/api/tasks", headers=headers, body=body, label=label)
    return int(created["id"])


def _upload_resource(
    client: TestClient, headers: dict[str, str], org_id: int, title: str
) -> int:
    data = DOC_TEXT.encode("utf-8")
    body = {
        "org_id": org_id,
        "title": title,
        "summary": f"{title} 简介",
        "file": {
            "name": "material.txt",
            "mime": "text/plain",
            "size": len(data),
            "data_base64": base64.b64encode(data).decode("ascii"),
        },
    }
    created = _ok(client, "POST", "/api/org-resources", headers=headers, body=body, label=f"上传「{title}」")
    return int(created["id"])


def _open_resource(client: TestClient, headers: dict[str, str], resource_id: int) -> None:
    _ok(
        client,
        "PATCH",
        f"/api/org-resources/{resource_id}",
        headers=headers,
        body={"allow_student_ai": True},
        label=f"开启资料 {resource_id}",
    )


def _ref_resource_ids(username: str) -> list[int]:
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == username).one()
        rows = (
            db.query(LibraryRef)
            .filter(LibraryRef.owner_id == int(user.id))
            .order_by(LibraryRef.id.asc())
            .all()
        )
        return [int(row.resource_id) for row in rows]


def _chat(client: TestClient, headers: dict[str, str], body: dict, label: str) -> dict:
    return _ok(client, "POST", "/api/agent/chat", headers=headers, body=body, label=label)


@pytest.fixture(scope="module")
def ctx() -> _Ctx:
    with TestClient(app) as client:
        admin_id = _ensure_user("v1_ai_admin", "V1 AI 管理员")
        stu1_id = _ensure_user("v1_ai_stu1", "V1 AI 学生一")
        stu2_id = _ensure_user("v1_ai_stu2", "V1 AI 学生二")
        other_admin_id = _ensure_user("v1_ai_other_admin", "V1 AI 外组织管理员")

        org_id = _ensure_org(
            "V1 AI 组织", "v1-ai-org", roles={admin_id: "admin", stu1_id: "member", stu2_id: "member"}
        )
        other_org_id = _ensure_org("V1 AI 外组织", "v1-ai-other-org", roles={other_admin_id: "admin"})

        admin = _login(client, "v1_ai_admin")
        stu1 = _login(client, "v1_ai_stu1")
        stu2 = _login(client, "v1_ai_stu2")
        other_admin = _login(client, "v1_ai_other_admin")

        activity = _ok(
            client,
            "POST",
            "/api/activities",
            headers=admin,
            body={"title": "秋季招聘会", "org_id": org_id},
            label="创建活动",
        )
        activity_id = int(activity["id"])

        task_keyword = _create_task(
            client,
            admin,
            {
                "title": "秋季招聘现场布置展位确认",
                "activity_id": activity_id,
                "sop_guide": "提前一天确认展位与物资清单，并向场地负责人报备。",
                "deadline": "2099-01-01 10:00:00",
                "location": "体育馆东门",
                "extras": {
                    "acceptance": {
                        "modes": ["text", "link"],
                        "allowed_exts": [".pdf"],
                        "ai_precheck": True,
                    }
                },
            },
            "创建关键词任务",
        )
        task_overdue = _create_task(
            client,
            admin,
            {
                "title": "志愿者排班表整理",
                "activity_id": activity_id,
                "deadline": "2020-01-01 09:00:00",
            },
            "创建逾期任务",
        )
        task_review = _create_task(
            client,
            admin,
            {
                "title": "招聘海报设计",
                "activity_id": activity_id,
                "deadline": "2099-02-01 10:00:00",
            },
            "创建待验收任务",
        )
        task_plain = _create_task(
            client,
            admin,
            {
                "title": "场地清理与资料归档",
                "activity_id": activity_id,
                "deadline": "2099-03-01 10:00:00",
            },
            "创建普通任务",
        )
        task_none = _create_task(
            client,
            admin,
            {"title": "临时物资借还登记", "activity_id": activity_id},
            "创建无截止任务",
        )
        task_solo = _create_task(
            client, admin, {"title": "社团日常值班"}, "创建独立任务"
        )
        task_other = _create_task(
            client, other_admin, {"title": "外组织机密任务"}, "创建外组织任务"
        )
        task_secret = _create_task(
            client,
            admin,
            {
                "title": "私密成果核对",
                "activity_id": activity_id,
                "deadline": "2099-04-01 10:00:00",
            },
            "创建私密成果任务",
        )

        # 逾期任务进入进行中状态并保留过去的截止时间；待验收任务补一条提交与成员记录。
        with SessionLocal() as db:
            overdue_row = db.get(Task, task_overdue)
            assert overdue_row is not None
            overdue_row.status = "in_progress"
            db.add(
                TaskSubmission(
                    task_id=task_review,
                    user_id=stu1_id,
                    version=1,
                    content="海报初稿已完成，附设计说明。",
                    created_at="2026-01-02 10:00:00",
                )
            )
            db.add(
                TaskMember(
                    task_id=task_review,
                    user_id=stu1_id,
                    status="submitted",
                    submitted_at="2026-01-02 10:00:00",
                )
            )
            # 学生一的私密成果与退回原因：非审阅者不得在 AI 上下文中看到这些字段。
            db.add(
                TaskSubmission(
                    task_id=task_secret,
                    user_id=stu1_id,
                    version=1,
                    content=SECRET_CONTENT,
                    resource_url=SECRET_URL,
                    file_name=SECRET_FILE,
                    created_at="2026-01-03 10:00:00",
                )
            )
            db.add(
                TaskMember(
                    task_id=task_secret,
                    user_id=stu1_id,
                    status="rejected",
                    rejection_reason=SECRET_REASON,
                    submitted_at="2026-01-03 10:00:00",
                )
            )
            db.commit()

        open_resource_id = _upload_resource(client, admin, org_id, "招聘物资清单")
        _open_resource(client, admin, open_resource_id)
        closed_resource_id = _upload_resource(client, admin, org_id, "招聘内部排班表")
        foreign_resource_id = _upload_resource(client, other_admin, other_org_id, "外组织招聘资料")
        _open_resource(client, other_admin, foreign_resource_id)

        yield _Ctx(
            client=client,
            admin=admin,
            stu1=stu1,
            stu2=stu2,
            other_admin=other_admin,
            org_id=org_id,
            other_org_id=other_org_id,
            activity_id=activity_id,
            task_keyword=task_keyword,
            task_overdue=task_overdue,
            task_review=task_review,
            task_plain=task_plain,
            task_none=task_none,
            task_solo=task_solo,
            task_other=task_other,
            task_secret=task_secret,
            open_resource_id=open_resource_id,
            closed_resource_id=closed_resource_id,
            foreign_resource_id=foreign_resource_id,
        )


# --------------------------------------------------------------------------- #
# 任务查询打分
# --------------------------------------------------------------------------- #
def test_keyword_hits_rank_first_with_sop_and_acceptance(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        rows = task_query_service.build_task_context(
            db, _user("v1_ai_stu1"), "秋季招聘现场布置的 SOP 和验收要求是什么"
        )

    assert rows, "学生应能看到组织内开放任务"
    first = rows[0]
    assert first["task_id"] == ctx.task_keyword, f"关键词任务应排第一（实际 {first['title']}）"
    assert EXPECTED_TASK_KEYS <= set(first), f"上下文缺少契约字段：{EXPECTED_TASK_KEYS - set(first)}"
    assert first["sop"] and "物资清单" in first["sop"], "上下文必须包含任务 SOP"
    assert first["acceptance"] and "text" in first["acceptance"], "上下文必须包含验收要求"
    assert first["acceptance"] and ".pdf" in first["acceptance"]
    assert first["activity_name"] == "秋季招聘会"
    assert first["location"] == "体育馆东门"
    assert first["score"] > 0

    scores = [row["score"] for row in rows]
    assert scores == sorted(scores, reverse=True), "任务上下文必须按相关度降序"


def test_overdue_and_review_intents_rank_first(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        user = _user("v1_ai_stu1")
        overdue_rows = task_query_service.build_task_context(db, user, "我有哪些逾期任务")
        review_rows = task_query_service.build_task_context(db, user, "有哪些任务待验收")
        reviewer_rows = task_query_service.build_task_context(
            db, _user("v1_ai_admin"), "招聘海报设计"
        )

    assert overdue_rows and overdue_rows[0]["task_id"] == ctx.task_overdue, "逾期意图应优先命中逾期任务"
    assert overdue_rows[0]["deadline"] == "2020-01-01 09:00:00"

    assert review_rows, "待验收意图应有候选"
    first_review = review_rows[0]
    assert first_review["task_id"] == ctx.task_review, f"待验收任务应排第一（实际 {first_review['title']}）"
    assert first_review["latest_submission"] and "v1" in first_review["latest_submission"]
    # 提交人本人不是审阅者：review_result 只依据任务聚合状态（未同步提交态 → None）。
    assert first_review["review_result"] is None

    reviewer_view = next(row for row in reviewer_rows if row["task_id"] == ctx.task_review)
    assert reviewer_view["review_result"] == "待验收", "审阅者应看到成员待验收状态"


def test_fallback_orders_recent_tasks_by_deadline(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        rows = task_query_service.build_task_context(db, _user("v1_ai_stu1"), "你好")

    assert [row["task_id"] for row in rows] == [
        ctx.task_overdue,
        ctx.task_keyword,
        ctx.task_review,
        ctx.task_plain,
        ctx.task_secret,
        ctx.task_none,
    ], "无关键词命中时必须退化为按截止时间排列的最近任务（NULL 最后）"
    assert all(row["score"] == 0 for row in rows), "退化路径不加相关度分"


def test_scope_limits_task_context(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        user = _user("v1_ai_stu1")
        activity_rows = task_query_service.build_task_context(
            db, user, "你好", scope_type="activity", scope_id=ctx.activity_id
        )
        task_rows = task_query_service.build_task_context(
            db, user, "你好", scope_type="task", scope_id=ctx.task_keyword
        )

    activity_ids = {row["task_id"] for row in activity_rows}
    assert activity_ids == {
        ctx.task_keyword,
        ctx.task_overdue,
        ctx.task_review,
        ctx.task_plain,
        ctx.task_none,
        ctx.task_secret,
    }
    assert all(row["activity_id"] == ctx.activity_id for row in activity_rows)
    assert {row["task_id"] for row in task_rows} == activity_ids, "任务作用域应含同活动可见任务"
    assert ctx.task_solo not in activity_ids and ctx.task_other not in activity_ids


def test_student_cannot_see_others_tasks(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        rows = task_query_service.build_task_context(
            db, _user("v1_ai_stu2"), "外组织机密任务 秋季招聘现场布置"
        )
    ids = {row["task_id"] for row in rows}
    assert ctx.task_other not in ids, "学生不得看到外组织任务"
    assert ctx.task_solo not in ids, "学生不得看到他人独立任务"

    data = _chat(ctx.client, ctx.stu2, {"message": "外组织机密任务在哪"}, "学生查询他人任务")
    content = data["assistant_message"]["content"]
    citations = data["assistant_message"]["citations"]
    assert "外组织机密任务" not in content
    assert all(item["title"] != "外组织机密任务" for item in citations)


def test_non_reviewer_cannot_read_peer_submission(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        rows = task_query_service.build_task_context(
            db, _user("v1_ai_stu2"), "私密成果核对"
        )

    target = next(row for row in rows if row["task_id"] == ctx.task_secret)
    assert target["latest_submission"] is None, "非审阅者不应看到他人成果"
    assert target["review_result"] is None, "非审阅者不应看到他人退回原因"
    serialized = json.dumps(rows, ensure_ascii=False)
    for secret in (SECRET_CONTENT, SECRET_URL, SECRET_FILE, SECRET_REASON):
        assert secret not in serialized, f"非审阅者上下文泄露：{secret}"

    # 审阅者（发布者）在同一任务上仍能看到全部成员的最新成果与验收结果。
    with SessionLocal() as db:
        reviewer_rows = task_query_service.build_task_context(
            db, _user("v1_ai_admin"), "私密成果核对"
        )
    reviewer_view = next(row for row in reviewer_rows if row["task_id"] == ctx.task_secret)
    assert reviewer_view["latest_submission"] and SECRET_CONTENT in reviewer_view["latest_submission"]
    assert reviewer_view["latest_submission"] and SECRET_FILE in reviewer_view["latest_submission"]
    assert reviewer_view["review_result"] == f"验收未通过：{SECRET_REASON}"


# --------------------------------------------------------------------------- #
# 文档上下文与自动收藏
# --------------------------------------------------------------------------- #
def test_doc_context_citations_and_auto_refs(ctx: _Ctx) -> None:
    before = _ref_resource_ids("v1_ai_stu1")

    data = _chat(
        ctx.client,
        ctx.stu1,
        {"message": "秋季招聘现场布置需要哪些准备"},
        "文档上下文问答",
    )
    message = data["assistant_message"]
    assert message["mock"] is True, "测试必须走 mock 分支"
    content = message["content"]
    assert "参考资料" in content, "mock 回答命中资料时应列出参考资料"
    assert "招聘物资清单" in content, "回答应列出开放资料标题"

    citations = message["citations"]
    doc_items = [item for item in citations if item["kind"] == "doc"]
    assert doc_items, "文档命中必须产生 doc citation"
    assert doc_items[0]["title"] == "招聘物资清单"
    assert int(doc_items[0]["resource_id"]) == ctx.open_resource_id
    assert doc_items[0]["type"] == "doc"

    assert "招聘内部排班表" not in content, "未开放资料标题不得进入回答"
    titles = {item["title"] for item in citations}
    assert "招聘内部排班表" not in titles
    assert "外组织招聘资料" not in titles

    after = _ref_resource_ids("v1_ai_stu1")
    assert set(after) - set(before) == {ctx.open_resource_id}, "只应收藏实际引用的开放资料"
    assert ctx.closed_resource_id not in after and ctx.foreign_resource_id not in after


def test_with_docs_reserves_slots_for_doc_citations() -> None:
    task_citations = [
        AiCitation(type="task", id=index, title=f"任务{index}", kind="task")
        for index in range(1, 6)
    ]
    doc_item = ai_service._ContextItem(
        ref="D1", kind="doc", title="招聘物资清单", summary="片段", resource_id=99
    )

    answer, citations = ai_service._with_docs("任务回答", task_citations, [doc_item])

    assert len(citations) == ai_service.MAX_CITATIONS, "citations 总数仍受 MAX_CITATIONS 限制"
    assert citations[-1].kind == "doc" and citations[-1].resource_id == 99, (
        "任务来源满额时必须为 doc 预留槽位"
    )
    assert "参考资料" in answer and "招聘物资清单" in answer
    assert {item.title for item in citations if item.kind == "doc"} == {"招聘物资清单"}, (
        "正文列出的参考资料必须同时出现在 citations 中"
    )


def test_record_citations_failure_keeps_answer(ctx: _Ctx, monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_args, **_kwargs):
        raise RuntimeError("引用写入失败")

    monkeypatch.setattr(library_ref_service, "record_citations", _boom)

    data = _chat(
        ctx.client,
        ctx.stu1,
        {"message": "秋季招聘现场布置需要哪些准备"},
        "引用写入失败时问答",
    )
    message = data["assistant_message"]
    assert message["content"].strip(), "引用收藏失败不得影响回答内容"
    assert any(item["kind"] == "doc" for item in message["citations"])


def test_replay_keeps_answer_and_does_not_duplicate_refs(ctx: _Ctx) -> None:
    body = {
        "message": "秋季招聘现场布置需要哪些准备",
        "request_id": "v1-ai-context-replay-1",
    }
    with SessionLocal() as db:
        before_used = ai_service.get_usage(db, _user("v1_ai_stu2")).used
    before_refs = _ref_resource_ids("v1_ai_stu2")

    first = _chat(ctx.client, ctx.stu2, body, "首次问答")
    second = _chat(ctx.client, ctx.stu2, body, "重放问答")

    assert second["replayed"] is True
    assert second["assistant_message"]["content"] == first["assistant_message"]["content"]
    with SessionLocal() as db:
        after_used = ai_service.get_usage(db, _user("v1_ai_stu2")).used
    assert after_used == before_used + 1, "重放不得重复扣额度"

    after_refs = _ref_resource_ids("v1_ai_stu2")
    assert set(after_refs) - set(before_refs) == {ctx.open_resource_id}
    assert after_refs.count(ctx.open_resource_id) == 1, "重复引用只更新引用行，不新增"


# --------------------------------------------------------------------------- #
# 检索性能上限
# --------------------------------------------------------------------------- #
def test_empty_query_skips_per_task_tokenize(
    ctx: _Ctx, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}
    original = kb_service.tokenize

    def _counting(text, *args, **kwargs):
        calls["count"] += 1
        return original(text, *args, **kwargs)

    monkeypatch.setattr(kb_service, "tokenize", _counting)

    with SessionLocal() as db:
        rows = task_query_service.build_task_context(db, _user("v1_ai_stu2"), "!@#")

    assert calls["count"] == 1, f"无可分词关键词时只对问题分词一次（实际 {calls['count']} 次）"
    assert rows and all(row["score"] == 0 for row in rows)


def test_build_task_context_query_count_is_bounded(ctx: _Ctx) -> None:
    user = _user("v1_ai_stu2")
    counter = {"count": 0}

    def _count(conn, cursor, statement, parameters, context, executemany):
        counter["count"] += 1

    with SessionLocal() as db:
        event.listen(engine, "before_cursor_execute", _count)
        try:
            rows = task_query_service.build_task_context(
                db, user, "秋季招聘现场布置的 SOP"
            )
        finally:
            event.remove(engine, "before_cursor_execute", _count)

    assert rows
    assert counter["count"] < 40, f"任务上下文不得逐任务查询（实际 {counter['count']} 次 SQL）"


def test_scope_without_id_returns_empty(ctx: _Ctx) -> None:
    with SessionLocal() as db:
        user = _user("v1_ai_stu1")
        assert (
            task_query_service.build_task_context(
                db, user, "你好", scope_type="activity", scope_id=None
            )
            == []
        ), "活动作用域缺 scope_id 应返回空，而不是抛 TypeError"
        assert (
            task_query_service.build_task_context(
                db, user, "你好", scope_type="task", scope_id=None
            )
            == []
        )


# --------------------------------------------------------------------------- #
# 兼容性
# --------------------------------------------------------------------------- #
def test_legacy_citation_without_kind_still_parses() -> None:
    legacy = AiCitation.model_validate(
        {"type": "task", "id": 7, "title": "旧来源", "activity_id": None}
    )
    assert legacy.kind == "task"
    assert legacy.resource_id is None

    doc = AiCitation.model_validate(
        {"type": "doc", "id": 9, "title": "招聘物资清单", "kind": "doc", "resource_id": 9}
    )
    assert doc.kind == "doc" and doc.resource_id == 9

    message = AiMessageOut.model_validate(
        {
            "id": 1,
            "role": "assistant",
            "content": "旧回答",
            "citations": [{"type": "task", "id": 3, "title": "旧任务"}],
            "mock": True,
            "created_at": "2026-01-01 00:00:00",
        }
    )
    assert message.citations[0].kind == "task"
    assert message.citations[0].resource_id is None