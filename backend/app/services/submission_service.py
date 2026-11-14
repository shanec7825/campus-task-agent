"""成果版本与预审服务（契约 `C-SUBMISSION@1` / `C-PRECHECK-EVIDENCE@2`）。

边界：

* 每次成员从 ``in_progress|rejected`` 进入 ``submitted`` 时新增一条版本；
* 版本号由服务层在事务内计算，旧版本保留；
* 预审只写 ``submission_prechecks``，不改变任务、成员、积分或通知；
* 预审摘要绑定任务/活动要求与引用资料版本，任一变化后旧预审过期；
* 规则预审决定 ``verdict``，模型建议只作补充；模型失败写 ``ai_error``，不冒充通过。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents import llm_client, prompts
from app.errors import ApiError
from app.models import Activity, SubmissionPrecheck, Task, TaskSubmission, User
from app.schemas import (
    ACCEPTANCE_KEY,
    PrecheckItem,
    PrecheckOut,
    PrecheckResourceSnapshot,
    PrecheckSuggestion,
    PrecheckSummary,
    SubmissionAcceptance,
    SubmissionOut,
)
from app.services import authz, resource_service

logger = logging.getLogger(__name__)

ERR_NOT_FOUND = 4040
ERR_FORBIDDEN = 4030
ERR_CONFLICT = 4090
ERR_INVALID_PARAM = 4001

# 成果文件（`C-SUBMISSION-FILE@1`）：格式白名单与大小上限；不做第三方正文解析。
SUBMISSION_UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "submissions"
MAX_FILE_BYTES = 10 * 1024 * 1024
ALLOWED_FILE_EXTS = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
PARSEABLE_FILE_EXTS = frozenset({".txt", ".md"})

# 提交策略（`C-SUBMISSION-POLICY@1`）的拒绝文案：前端本地校验与服务端保持一致。
MSG_POLICY_EMPTY = "请按任务要求的成果提交方式提交"
MSG_TEXT_NOT_ALLOWED = "本任务不接受文字说明提交"
MSG_LINK_NOT_ALLOWED = "本任务不接受成果链接提交"
MSG_FILE_NOT_ALLOWED = "本任务不接受文件提交"
MSG_EXT_NOT_ALLOWED = "文件类型不在任务允许范围内"

STATUS_PASS = "pass"
STATUS_FAIL = "fail"
STATUS_WARN = "warn"
STATUS_UNKNOWN = "unknown"

AI_SUGGESTION_KEYS = frozenset({"time", "location", "requirements", "resource", "other"})

_DATE_RE = re.compile(r"(?P<year>20\d{2})\s*[-/.年]\s*(?P<month>\d{1,2})\s*[-/.月]\s*(?P<day>\d{1,2})")
_MONTH_DAY_RE = re.compile(r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*[日号]?")
_TIME_RE = re.compile(r"(?P<hour>[01]?\d|2[0-3])\s*[:：]\s*(?P<minute>[0-5]\d)")
_REQUIREMENT_KEYS = ("title", "description", "location", "start_time", "deadline", "sop_guide", "extras")


class _RawSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = "other"
    message: str
    evidence: str | None = None


class _RawPrecheck(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    suggestions: list[_RawSuggestion] = Field(default_factory=list)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def next_version(db: Session, task_id: int, user_id: int) -> int:
    current = db.execute(
        select(func.max(TaskSubmission.version)).where(
            TaskSubmission.task_id == int(task_id),
            TaskSubmission.user_id == int(user_id),
        )
    ).scalar()
    return int(current or 0) + 1


def create_submission(
    db: Session,
    task: Task,
    user_id: int,
    *,
    content: str | None,
    resource_url: str | None,
    file_name: str | None = None,
    file_size: int | None = None,
    file_mime: str | None = None,
    file_path: str | None = None,
) -> TaskSubmission:
    """新增一条成果版本（只 flush，不 commit）。"""
    text = (content or "").strip() or None
    url = (resource_url or "").strip() or None
    row = TaskSubmission(
        task_id=int(task.id),
        user_id=int(user_id),
        version=next_version(db, int(task.id), int(user_id)),
        content=text,
        resource_url=url,
        file_name=file_name,
        file_size=file_size,
        file_mime=file_mime,
        file_path=file_path,
    )
    db.add(row)
    db.flush()
    return row


def task_acceptance(task: Task) -> SubmissionAcceptance | None:
    """读取任务提交策略（`C-SUBMISSION-POLICY@1`）。

    未配置或历史脏数据一律视为未配置，保持旧任务的宽松行为；写库前的
    ``schemas.normalize_acceptance`` 已保证新任务不会存入非法策略。
    """
    extras = task.extras if isinstance(task.extras, dict) else {}
    raw = extras.get(ACCEPTANCE_KEY)
    if not isinstance(raw, dict):
        return None
    try:
        return SubmissionAcceptance.model_validate(raw)
    except (ApiError, ValidationError):
        logger.warning("任务 %s 的提交策略非法，按未配置处理", getattr(task, "id", None))
        return None


def enforce_submit_policy(
    task: Task,
    content: str | None = None,
    resource_url: str | None = None,
) -> None:
    """文字/链接提交前按策略校验；必须在 ``record_submit`` 之前调用。"""
    policy = task_acceptance(task)
    if policy is None:
        return
    text = (content or "").strip()
    url = (resource_url or "").strip()
    if text and not policy.allows("text"):
        raise ApiError(ERR_INVALID_PARAM, MSG_TEXT_NOT_ALLOWED)
    if url and not policy.allows("link"):
        raise ApiError(ERR_INVALID_PARAM, MSG_LINK_NOT_ALLOWED)
    if not text and not url:
        raise ApiError(ERR_INVALID_PARAM, MSG_POLICY_EMPTY)


def validate_upload_against_policy(task: Task, filename: str) -> None:
    """文件上传前按策略校验通道与扩展名；必须在落盘与 ``record_submit`` 之前调用。"""
    policy = task_acceptance(task)
    if policy is None:
        return
    if not policy.allows("file"):
        raise ApiError(ERR_INVALID_PARAM, MSG_FILE_NOT_ALLOWED)
    allowed = set(policy.allowed_exts)
    if not allowed:
        # 策略未限定文件类型时沿用全局白名单（仍由 validate_submission_file 兜底）
        return
    if Path(filename or "").suffix.lower() not in allowed:
        raise ApiError(ERR_INVALID_PARAM, MSG_EXT_NOT_ALLOWED)


def validate_submission_file(filename: str, payload: bytes) -> str:
    """校验格式、空文件与大小上限，返回原始文件名（不写盘）。"""
    original = Path(filename or "").name.strip()
    ext = Path(original).suffix.lower()
    if not original or ext not in ALLOWED_FILE_EXTS:
        raise ApiError(ERR_INVALID_PARAM, "仅支持 TXT/Markdown/PDF/DOCX")
    if not payload:
        raise ApiError(ERR_INVALID_PARAM, "文件内容为空")
    if len(payload) > MAX_FILE_BYTES:
        raise ApiError(ERR_INVALID_PARAM, "文件不能超过 10MB")
    return original


def save_submission_file(task_id: int, filename: str, payload: bytes) -> dict[str, object]:
    """校验并保存成果文件；返回可直接展开为字段的原始信息与相对路径。"""
    original = validate_submission_file(filename, payload)
    ext = Path(original).suffix.lower()
    relative_dir = str(int(task_id))
    target_dir = SUBMISSION_UPLOAD_ROOT / relative_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{ext}"
    (target_dir / stored).write_bytes(payload)
    return {
        "file_name": original[:255],
        "file_size": len(payload),
        "file_mime": ALLOWED_FILE_EXTS[ext],
        "file_path": f"{relative_dir}/{stored}",
    }


def file_text_for_precheck(row: TaskSubmission) -> str | None:
    """TXT/Markdown 读取前 8000 字符供规则/模型预审；PDF/DOCX 不解析。"""
    if not row.file_path:
        return None
    ext = Path(row.file_path).suffix.lower()
    if ext not in PARSEABLE_FILE_EXTS:
        return None
    try:
        return (SUBMISSION_UPLOAD_ROOT / row.file_path).read_text(
            encoding="utf-8", errors="replace"
        )[:8000]
    except OSError:
        return None


def latest_submission(db: Session, task_id: int, user_id: int) -> TaskSubmission | None:
    return db.execute(
        select(TaskSubmission)
        .where(
            TaskSubmission.task_id == int(task_id),
            TaskSubmission.user_id == int(user_id),
        )
        .order_by(TaskSubmission.version.desc(), TaskSubmission.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_submission(db: Session, task: Task, submission_id: int) -> TaskSubmission:
    row = db.get(TaskSubmission, int(submission_id))
    if row is None or int(row.task_id) != int(task.id):
        raise ApiError(ERR_NOT_FOUND, "成果版本不存在", 404)
    return row


def can_review_task(db: Session, user: User, task: Task) -> bool:
    """成果审核范围（`C-SUBMISSION@1`）：发布者、组织管理员或活动负责人。

    不使用 ``authz.can_manage_task``：该函数把 ``assignee_id`` 视为可管理，
    会让被指派的普通成员看到他人成果；成果审核必须用更窄的判定。
    """
    if int(task.publisher_id) == int(user.id):
        return True
    if task.org_id is not None and authz.org_role(db, user, int(task.org_id)) == "admin":
        return True
    if task.activity_id is not None:
        activity = db.get(Activity, int(task.activity_id))
        if activity is not None and int(activity.owner_id) == int(user.id):
            return True
    return False


def require_task_review(db: Session, user: User, task: Task) -> None:
    """验收权限（`C-SUBMISSION@1`）：发布者 / 组织管理员 / 活动负责人。"""
    if not can_review_task(db, user, task):
        raise ApiError(ERR_FORBIDDEN, "无权验收该任务", 403)


def require_submission_access(db: Session, user: User, task: Task, row: TaskSubmission) -> None:
    """本人可访问自己的版本；发布者/组织管理员/活动负责人可访问全部；其他人 4030。"""
    if int(row.user_id) == int(user.id):
        return
    if can_review_task(db, user, task):
        return
    raise ApiError(ERR_FORBIDDEN, "无权查看该成果版本", 403)


def _requirement_digest(task: Task, activity: Activity | None, resources: Sequence) -> str:
    payload = {
        "task": {key: getattr(task, key, None) for key in _REQUIREMENT_KEYS},
        "activity": {
            "title": activity.title if activity is not None else None,
            "location": activity.location if activity is not None else None,
            "start_time": activity.start_time if activity is not None else None,
            "deadline": activity.deadline if activity is not None else None,
        },
        "resources": [
            {"id": int(item.id), "version": int(item.version)} for item in resources
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _resource_snapshot(resources: Sequence) -> list[dict]:
    """预审引用资料的可读快照（`C-PRECHECK-EVIDENCE@2`）：服务端存 id/标题/版本。"""
    return [
        {"id": int(item.id), "title": item.title, "version": int(item.version)}
        for item in resources
    ]


def _current_digest(db: Session, user: User, task: Task) -> str:
    """当前任务要求 + 资料版本的摘要。

    资源视角唯一化（`C-PRECHECK-EVIDENCE@2`）：``user`` 必须是**成果提交者**，
    预审、成果列表 stale 与验收校验三处共用该视角；审核者视角只用于权限判定。
    """
    activity = db.get(Activity, int(task.activity_id)) if task.activity_id is not None else None
    resources = resource_service.latest_resource_versions(db, user, task, limit=5)
    return _requirement_digest(task, activity, resources)


def _parse_dates(value: str | None) -> set[tuple[int, int, int]]:
    """抽取完整日期；没有年份时年份记为 0，仅按月日比较。"""
    if not value:
        return set()
    dates: set[tuple[int, int, int]] = set()
    for match in _DATE_RE.finditer(value):
        dates.add((int(match.group("year")), int(match.group("month")), int(match.group("day"))))
    if dates:
        return dates
    for match in _MONTH_DAY_RE.finditer(value):
        month, day = int(match.group("month")), int(match.group("day"))
        if 1 <= month <= 12 and 1 <= day <= 31:
            dates.add((0, month, day))
    return dates


def _parse_times(value: str | None) -> set[tuple[int, int]]:
    if not value:
        return set()
    return {(int(match.group("hour")), int(match.group("minute"))) for match in _TIME_RE.finditer(value)}


def _required_dates(task: Task, activity: Activity | None) -> set[tuple[int, int, int]]:
    values = [task.start_time, task.deadline]
    if activity is not None:
        values.extend([activity.start_time, activity.deadline])
    dates: set[tuple[int, int, int]] = set()
    for value in values:
        dates |= _parse_dates(value)
    return dates


def _same_day(left: tuple[int, int, int], right: tuple[int, int, int]) -> bool:
    if left[0] and right[0] and left[0] != right[0]:
        return False
    return left[1] == right[1] and left[2] == right[2]


def _rule_checks(
    task: Task,
    activity: Activity | None,
    submission: TaskSubmission,
    resources: Sequence,
) -> list[PrecheckItem]:
    content = (submission.content or "").strip()
    url = (submission.resource_url or "").strip()
    checks: list[PrecheckItem] = []

    checks.append(
        PrecheckItem(
            key="content_present",
            label="成果内容",
            status=STATUS_PASS if (content or url) else STATUS_FAIL,
            message="已填写成果说明或链接" if (content or url) else "未填写成果说明或链接，无法审核",
            evidence=None if (content or url) else "成果内容与链接均为空",
            source="成果版本",
        )
    )

    required = _required_dates(task, activity)
    submitted = _parse_dates(content) | _parse_dates(url)
    if not required:
        checks.append(
            PrecheckItem(
                key="time_consistency",
                label="时间一致性",
                status=STATUS_UNKNOWN,
                message="任务与活动未提供可解析时间，无法核对",
                source="任务 / 活动要求",
            )
        )
    elif not submitted:
        checks.append(
            PrecheckItem(
                key="time_consistency",
                label="时间一致性",
                status=STATUS_UNKNOWN,
                message="成果中未识别到日期，无法核对时间",
                evidence="要求时间：" + "、".join(f"{y:04d}-{m:02d}-{d:02d}" if y else f"{m:02d}-{d:02d}" for y, m, d in sorted(required)),
                source="成果内容",
            )
        )
    else:
        mismatched = [
            item
            for item in sorted(submitted)
            if not any(_same_day(item, expected) for expected in required)
        ]
        if mismatched:
            actual = "、".join(f"{y:04d}-{m:02d}-{d:02d}" if y else f"{m:02d}-{d:02d}" for y, m, d in mismatched)
            expected_text = "、".join(f"{y:04d}-{m:02d}-{d:02d}" if y else f"{m:02d}-{d:02d}" for y, m, d in sorted(required))
            checks.append(
                PrecheckItem(
                    key="time_consistency",
                    label="时间一致性",
                    status=STATUS_FAIL,
                    message="成果中的时间与任务要求不一致",
                    evidence=f"提交：{actual}；要求：{expected_text}",
                    source="成果内容 / 任务要求",
                )
            )
        else:
            required_times = _parse_times(task.start_time) | _parse_times(task.deadline)
            if activity is not None:
                required_times |= _parse_times(activity.start_time) | _parse_times(activity.deadline)
            submitted_times = _parse_times(content) | _parse_times(url)
            if required_times and submitted_times and not (required_times & submitted_times):
                checks.append(
                    PrecheckItem(
                        key="time_consistency",
                        label="时间一致性",
                        status=STATUS_WARN,
                        message="日期一致，但提交中的时刻与要求时刻不同，请人工确认",
                        evidence=(
                            "提交时刻："
                            + "、".join(f"{h:02d}:{m:02d}" for h, m in sorted(submitted_times))
                            + "；要求时刻："
                            + "、".join(f"{h:02d}:{m:02d}" for h, m in sorted(required_times))
                        ),
                        source="成果内容 / 任务要求",
                    )
                )
            else:
                checks.append(
                    PrecheckItem(
                        key="time_consistency",
                        label="时间一致性",
                        status=STATUS_PASS,
                        message="成果中的日期与任务要求一致",
                        evidence="提交日期均能在任务或活动要求中找到",
                        source="成果内容 / 任务要求",
                    )
                )

    has_requirements = bool(
        (task.description or "").strip()
        or (task.sop_guide or "").strip()
        or (task.extras or {})
    )
    checks.append(
        PrecheckItem(
            key="requirements_present",
            label="验收要求",
            status=STATUS_PASS if has_requirements else STATUS_UNKNOWN,
            message="任务已提供说明或验收要求" if has_requirements else "任务未填写说明或验收要求，无法核对完整性",
            source="任务要求",
        )
    )

    if url:
        checks.append(
            PrecheckItem(
                key="resource_link",
                label="成果链接",
                status=STATUS_PASS if url.startswith(("http://", "https://")) else STATUS_FAIL,
                message="成果链接格式可识别" if url.startswith(("http://", "https://")) else "成果链接不是 http/https 地址，无法安全打开",
                evidence=url,
                source="成果版本",
            )
        )

    checks.append(
        PrecheckItem(
            key="related_resources",
            label="可引用资料",
            status=STATUS_PASS if resources else STATUS_UNKNOWN,
            message=f"找到 {len(resources)} 条可引用资料" if resources else "当前没有可引用的资料，建议人工补充依据",
            source="资料库（权限内）",
        )
    )
    return checks


def _verdict(checks: Sequence[PrecheckItem]) -> str:
    statuses = {check.status for check in checks}
    if STATUS_FAIL in statuses:
        return STATUS_FAIL
    if STATUS_UNKNOWN in statuses:
        return STATUS_UNKNOWN
    return STATUS_PASS


def _mock_summary(checks: Sequence[PrecheckItem]) -> str:
    failed = [check.label for check in checks if check.status == STATUS_FAIL]
    unknown = [check.label for check in checks if check.status == STATUS_UNKNOWN]
    if failed:
        return f"规则预审发现 {len(failed)} 项不通过：{'、'.join(failed)}。请修改后重新提交。"
    if unknown:
        return f"规则预审未发现明确冲突，但有 {len(unknown)} 项缺少依据：{'、'.join(unknown)}。请人工确认。"
    return "规则预审未发现明确冲突；预审不等于验收，仍需负责人人工确认。"


def _ai_suggestions(
    task: dict,
    activity: dict | None,
    submission: dict,
    resources: Sequence,
) -> tuple[str | None, list[PrecheckSuggestion], bool, str | None]:
    """返回 (summary, suggestions, mock, error)。mock 或失败都不影响规则结论。"""
    if llm_client.is_mock_mode():
        return None, [], True, None

    payload = {
        "任务要求": {
            "标题": task["title"],
            "说明": task["description"],
            "地点": task["location"],
            "开始时间": task["start_time"],
            "截止时间": task["deadline"],
            "验收要求": task["sop_guide"],
            "活动": {
                "标题": activity["title"] if activity is not None else None,
                "地点": activity["location"] if activity is not None else None,
                "开始时间": activity["start_time"] if activity is not None else None,
                "截止时间": activity["deadline"] if activity is not None else None,
            },
        },
        "成果": {
            "版本": submission["version"],
            "内容": submission["content"],
            "链接": submission["resource_url"],
        },
        "可引用资料": [
            {"ref": f"R{index}", "标题": item.title, "版本": item.version, "摘要": item.summary}
            for index, item in enumerate(resources, start=1)
        ],
    }
    try:
        raw = llm_client.chat_json(
            prompts.render_precheck_prompt(),
            json.dumps(payload, ensure_ascii=False),
            validate=_RawPrecheck.model_validate,
        )
    except llm_client.LLMError as exc:
        logger.warning("成果预审模型调用失败: code=%s msg=%s", exc.code, exc.message)
        return None, [], False, "AI 建议暂不可用，已保留规则预审结果"
    except Exception as exc:  # noqa: BLE001 - 初始化等非 LLMError 异常统一降级
        logger.warning("成果预审模型调用异常: %s", exc)
        return None, [], False, "AI 建议暂不可用，已保留规则预审结果"

    suggestions = [
        PrecheckSuggestion(
            key=str(item.key or "other") if str(item.key or "other") in AI_SUGGESTION_KEYS else "other",
            message=str(item.message or "").strip()[:500],
            evidence=(str(item.evidence).strip()[:500] if item.evidence else None),
        )
        for item in raw.suggestions
        if str(item.message or "").strip()
    ][:5]
    summary = (raw.summary or "").strip()[:1000] or None
    return summary, suggestions, False, None


def precheck(db: Session, user: User, task: Task, submission_id: int) -> PrecheckOut:
    """对指定成果版本执行规则预审 + （非 mock 时）模型建议，并持久化结果。

    事务前提：调用方不得持有未提交的业务写入——本函数会在模型调用前
    ``rollback`` 结束只读事务；预审本身只写 ``submission_prechecks``。
    """
    submission = get_submission(db, task, submission_id)
    require_submission_access(db, user, task, submission)

    activity = db.get(Activity, int(task.activity_id)) if task.activity_id is not None else None
    # 资源视角唯一化：预审摘要固定按成果提交者可见的资料版本计算，与验收端一致。
    submitter = db.get(User, int(submission.user_id))
    resources = (
        resource_service.latest_resource_versions(db, submitter, task, limit=5)
        if submitter is not None
        else []
    )
    digest = _requirement_digest(task, activity, resources)
    # TXT/Markdown 文件正文在无文字说明时参与规则/模型预审；PDF/DOCX 不解析正文。
    file_text = file_text_for_precheck(submission)
    has_text = bool((submission.content or "").strip())
    checks_view = (
        SimpleNamespace(content=file_text, resource_url=submission.resource_url)
        if file_text and not has_text
        else submission
    )
    checks = _rule_checks(task, activity, checks_view, resources)
    verdict = _verdict(checks)

    # 模型调用前把 ORM 行转成纯值快照并结束读事务，避免长时间持有 SQLite 读锁，
    # 也避免 rollback 后重新触发懒加载查询。
    task_snapshot = _task_snapshot(task)
    activity_snapshot = _activity_snapshot(activity)
    submission_snapshot = _submission_snapshot(submission)
    if file_text and not has_text:
        submission_snapshot["content"] = file_text
    db.rollback()

    ai_summary, suggestions, mock, ai_error = _ai_suggestions(
        task_snapshot, activity_snapshot, submission_snapshot, resources
    )
    if (
        ai_error is None
        and submission.file_path
        and Path(submission.file_path).suffix.lower() not in PARSEABLE_FILE_EXTS
        and not has_text
    ):
        ai_error = "PDF/DOCX 暂不解析正文，请补充文字说明"
    summary = ai_summary or _mock_summary(checks)

    row = SubmissionPrecheck(
        submission_id=int(submission_snapshot["id"]),
        requirement_digest=digest,
        checks=[check.model_dump() for check in checks],
        verdict=verdict,
        summary=summary,
        ai_suggestions=[item.model_dump() for item in suggestions],
        resource_snapshot=_resource_snapshot(resources),
        mock=1 if mock else 0,
        ai_error=ai_error,
        created_at=_now_text(),
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return PrecheckOut(
        submission_id=int(row.submission_id),
        requirement_digest=row.requirement_digest,
        checks=[PrecheckItem(**item) for item in (row.checks or [])],
        verdict=row.verdict,
        summary=row.summary,
        ai_suggestions=[PrecheckSuggestion(**item) for item in (row.ai_suggestions or [])],
        resource_snapshot=[
            PrecheckResourceSnapshot(**item) for item in (row.resource_snapshot or [])
        ],
        mock=bool(row.mock),
        ai_error=row.ai_error,
        created_at=row.created_at,
    )


def _task_snapshot(task: Task) -> dict:
    return {
        "title": task.title,
        "description": task.description,
        "location": task.location,
        "start_time": task.start_time,
        "deadline": task.deadline,
        "sop_guide": task.sop_guide,
        "extras": dict(task.extras or {}),
    }


def _activity_snapshot(activity: Activity | None) -> dict | None:
    if activity is None:
        return None
    return {
        "title": activity.title,
        "location": activity.location,
        "start_time": activity.start_time,
        "deadline": activity.deadline,
    }


def _submission_snapshot(submission: TaskSubmission) -> dict:
    return {
        "id": int(submission.id),
        "version": int(submission.version),
        "content": submission.content,
        "resource_url": submission.resource_url,
    }


def list_submissions(db: Session, task: Task, viewer: User) -> list[SubmissionOut]:
    """列出成果版本：审核者看全部，普通成员（含 assignee）只看自己的版本。"""
    authz.require_task_view(db, viewer, task)
    can_review = can_review_task(db, viewer, task)
    sql = select(TaskSubmission).where(TaskSubmission.task_id == int(task.id))
    if not can_review:
        sql = sql.where(TaskSubmission.user_id == int(viewer.id))
    rows = db.execute(
        sql.order_by(
            TaskSubmission.user_id.asc(),
            TaskSubmission.version.desc(),
            TaskSubmission.id.desc(),
        )
    ).scalars().all()
    if not rows:
        return []

    user_ids = sorted({int(row.user_id) for row in rows})
    names = {
        int(item.id): item.display_name
        for item in db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
    }
    latest_versions: dict[int, int] = {}
    for row in rows:
        latest_versions[int(row.user_id)] = max(
            latest_versions.get(int(row.user_id), 0), int(row.version)
        )

    submission_ids = [int(row.id) for row in rows]
    prechecks: dict[int, SubmissionPrecheck] = {}
    for item in db.execute(
        select(SubmissionPrecheck)
        .where(SubmissionPrecheck.submission_id.in_(submission_ids))
        .order_by(SubmissionPrecheck.id.desc())
    ).scalars().all():
        prechecks.setdefault(int(item.submission_id), item)


    activity = db.get(Activity, int(task.activity_id)) if task.activity_id is not None else None
    digests: dict[int, str] = {}

    def _submitter_digest(user_id: int) -> str:
        """stale 对比固定按成果提交者视角（`C-PRECHECK-EVIDENCE@2`），审核者视角不参与。"""
        cached = digests.get(user_id)
        if cached is not None:
            return cached
        submitter = db.get(User, int(user_id))
        value = (
            _requirement_digest(task, activity, [])
            if submitter is None
            else _current_digest(db, submitter, task)
        )
        digests[user_id] = value
        return value

    return [
        SubmissionOut(
            id=int(row.id),
            task_id=int(row.task_id),
            user_id=int(row.user_id),
            user_name=names.get(int(row.user_id), ""),
            version=int(row.version),
            content=row.content,
            resource_url=row.resource_url,
            file_name=row.file_name,
            file_size=row.file_size,
            file_mime=row.file_mime,
            created_at=row.created_at,
            latest=int(row.version) == latest_versions.get(int(row.user_id)),
            precheck=_precheck_summary(
                prechecks.get(int(row.id)), _submitter_digest(int(row.user_id))
            ),
        )
        for row in rows
    ]


def latest_precheck(db: Session, submission_id: int) -> SubmissionPrecheck | None:
    """取某个成果版本的最新预审；旧的预审行保留，不回写。"""
    return db.execute(
        select(SubmissionPrecheck)
        .where(SubmissionPrecheck.submission_id == int(submission_id))
        .order_by(SubmissionPrecheck.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def require_fresh_precheck(db: Session, task: Task, user_ids: Sequence[int]) -> None:
    """验收通过前校验最新预审是否过期（`C-PRECHECK-EVIDENCE@2`）。

    只检查每个目标成员最新成果版本的最新预审；没有成果或没有预审视为未检查，
    不阻断。digest 固定按该成员本人（成果提交者）的资料视角计算，与预审和成果
    列表 stale 一致；账号不存在时无法复原其视角，按无资料处理且不阻断。
    任一预审不一致即整体拒绝，需在写库前调用。
    """
    for user_id in user_ids:
        submission = latest_submission(db, int(task.id), int(user_id))
        if submission is None:
            continue
        row = latest_precheck(db, int(submission.id))
        if row is None:
            continue
        submitter = db.get(User, int(user_id))
        if submitter is None:
            continue
        if row.requirement_digest != _current_digest(db, submitter, task):
            raise ApiError(
                ERR_CONFLICT,
                "预审已过期（任务要求或引用资料已变化），请重新预审",
            )


def _precheck_summary(row: SubmissionPrecheck | None, current_digest: str) -> PrecheckSummary | None:
    if row is None:
        return None
    return PrecheckSummary(
        id=int(row.id),
        verdict=row.verdict,
        summary=row.summary,
        mock=bool(row.mock),
        ai_error=row.ai_error,
        requirement_digest=row.requirement_digest,
        stale=row.requirement_digest != current_digest,
        created_at=row.created_at,
    )


__all__ = [
    "create_submission",
    "get_submission",
    "latest_precheck",
    "latest_submission",
    "list_submissions",
    "next_version",
    "precheck",
    "can_review_task",
    "require_fresh_precheck",
    "require_task_review",
    "require_submission_access",
]