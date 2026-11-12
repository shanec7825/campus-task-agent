#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T15 · 无头端到端功能验收（不依赖浏览器，只用 Python 标准库）。

覆盖链路（第二轮 T8，与 `C-APPLY@1` / `C-DATA@2` / `C-AGENT@2` / `C-KB@1` / `C-NOTIFY@1` 对应）：
    登录 → 发布 → 列表可见 → **报名×2 → 审批×2** → 进度×2 → 提交×2 → 验收（两人各 +25）
    → 积分到账（两人）→ **签到×2** → 通知列表 → Agent extract / review / stream-parse（两片跨片更正 + 三片链式 + 介绍建议）
    → KB similar → 分解 → SSE 实时通知通道 → 前端 preview 页面与静态资源

端口约定：后端 **8050**、前端 preview **8051**（第四轮 T6 独占；禁止占用 8000/5173）。
数据库：系统临时目录，脚本结束删除；不污染仓库。

用法::

    python tests/security/e2e_headless.py
    python tests/security/e2e_headless.py --root campus-task-agent --keep-temp

退出码：0 = 全部步骤 PASS；1 = 存在 FAIL；2 = 环境/启动失败。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_PORT = 8050
FRONTEND_PORT = 8051
BASE = f"http://127.0.0.1:{BACKEND_PORT}"
FRONTEND_BASE = f"http://127.0.0.1:{FRONTEND_PORT}"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


class HeadlessE2E:
    def __init__(self, root: Path, keep_temp: bool = False) -> None:
        self.root = root
        self.backend_dir = root / "backend"
        self.frontend_dir = root / "frontend"
        self.python = self.backend_dir / ".venv" / "Scripts" / "python.exe"
        self.temp_dir = Path(tempfile.mkdtemp(prefix="t15_e2e_"))
        self.db_path = self.temp_dir / "t15.db"
        self.keep_temp = keep_temp
        self.results: list[StepResult] = []
        self.backend_proc: subprocess.Popen[str] | None = None
        self.frontend_proc: subprocess.Popen[str] | None = None
        self.teacher: dict[str, Any] = {}
        self.student: dict[str, Any] = {}
        self.student2: dict[str, Any] = {}

    # -- 结果 ---------------------------------------------------------------
    def step(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append(StepResult(name, ok, detail))
        prefix = "[PASS]" if ok else "[FAIL]"
        print(f"{prefix} {name}")
        if not ok and detail:
            print(f"       → {detail}")
        return ok

    # -- HTTP ---------------------------------------------------------------
    def http(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        token: str | None = None,
        base: str = BASE,
    ) -> tuple[int | None, dict[str, Any], str]:
        url = base + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            # 中文必须用 UTF-8 编码，且 ensure_ascii=False（禁止依赖 curl 的本地编码）
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except Exception as exc:
            return None, {}, f"{type(exc).__name__}: {exc}"
        try:
            return status, json.loads(raw), ""
        except json.JSONDecodeError:
            return status, {"raw": raw[:300]}, "响应不是 JSON"

    def code_of(self, payload: dict[str, Any]) -> Any:
        return payload.get("code")

    def data_of(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = payload.get("data")
        return value if isinstance(value, dict) else {}

    # -- 进程 ---------------------------------------------------------------
    def start_backend(self) -> bool:
        env = os.environ.copy()
        env.update(
            {
                "DATABASE_PATH": str(self.db_path),
                "MAAS_MOCK": "1",
                "RUN_SCHEDULER": "0",
                "PYTHONIOENCODING": "utf-8",
            }
        )
        self.backend_proc = subprocess.Popen(
            [str(self.python), "-m", "uvicorn", "app.main:app", "--port", str(BACKEND_PORT),
             "--log-level", "warning"],
            cwd=str(self.backend_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for _ in range(80):
            status, payload, err = self.http("GET", "/api/health")
            if status == 200 and self.code_of(payload) == 0:
                return True
            time.sleep(0.25)
        return False

    def start_frontend(self) -> bool:
        command = (
            f"npm run preview -- --port {FRONTEND_PORT} --strictPort --host 127.0.0.1"
        )
        self.frontend_proc = subprocess.Popen(
            command,
            cwd=str(self.frontend_dir),
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for _ in range(80):
            try:
                with urllib.request.urlopen(FRONTEND_BASE + "/", timeout=3) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                time.sleep(0.25)
        return False

    def stop_all(self) -> None:
        if self.backend_proc is not None:
            self.backend_proc.terminate()
            try:
                self.backend_proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.backend_proc.kill()
                self.backend_proc.communicate()
        if self.frontend_proc is not None:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.frontend_proc.pid)],
                    capture_output=True, text=True, timeout=20,
                )
            except Exception:
                pass
            try:
                self.frontend_proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                self.frontend_proc.kill()

    def clean_temp(self) -> None:
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = Path(str(self.db_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        if self.keep_temp:
            print(f"[INFO] 保留临时目录：{self.temp_dir}")
        elif self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -- 业务步骤 -----------------------------------------------------------
    def login(self, username: str) -> dict[str, Any]:
        status, payload, err = self.http("POST", "/api/auth/login", {"username": username})
        data = self.data_of(payload)
        ok = status == 200 and self.code_of(payload) == 0 and bool(data.get("token"))
        self.step(
            f"登录 {username}",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} err={err}",
        )
        return data

    def run_business_flow(self) -> int | None:
        # 1) teacher01 登录
        self.teacher = self.login("teacher01")
        teacher_token = self.teacher.get("token", "")
        teacher = self.teacher.get("user", {})
        self.step(
            "teacher01 角色为 publisher",
            teacher.get("role") == "publisher",
            f"role={teacher.get('role')}",
        )

        # 2) 发布任务
        create_body = {
            "title": "T15 终验任务：教三宣讲会物料准备",
            "description": "准备海报、签到表与桌牌",
            "location": "教三",
            "start_time": "2026-11-12 14:00",
            "deadline": "2026-11-15 18:00",
            "quota": 2,
            "volunteer_hours": 2.0,
            "claim_type": "open",
            "extras": {"material": "海报"},
            "credit_reward": 25,
            "reminder_rule": {"days_before": 1, "day_of": True, "on_overdue": True},
        }
        status, payload, err = self.http("POST", "/api/tasks", create_body, teacher_token)
        task = self.data_of(payload)
        task_id = task.get("id")
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and isinstance(task_id, int)
            and task.get("status") == "published"
            and task.get("publisher_id") == teacher.get("id")
            and task.get("credit_reward") == 25
        )
        self.step(
            "发布任务（POST /api/tasks）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} data={task} err={err}",
        )
        if not isinstance(task_id, int):
            return None

        # 3) student01 / student02 登录（两名成员用于多人报名与各 +25）
        self.student = self.login("student01")
        student_token = self.student.get("token", "")
        student = self.student.get("user", {})
        self.step(
            "student01 角色为 student",
            student.get("role") == "student",
            f"role={student.get('role')}",
        )
        self.student2 = self.login("student02")
        student2_token = self.student2.get("token", "")
        student2 = self.student2.get("user", {})
        self.step(
            "student02 角色为 student",
            student2.get("role") == "student" and student2.get("id") != student.get("id"),
            f"role={student2.get('role')} id={student2.get('id')}",
        )

        # 4) 列表可见
        status, payload, err = self.http("GET", "/api/tasks?scope=all&include_sub=false", token=student_token)
        items = self.data_of(payload).get("items", [])
        visible = [item for item in items if item.get("id") == task_id]
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and bool(visible)
            and visible[0].get("status") == "published"
            and visible[0].get("is_claimable") is True
        )
        self.step(
            "任务在 student01 列表中可见且可认领",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} 命中={len(visible)} err={err}",
        )

        # 5) 报名 ×2 + 审批 ×2（P2：claim 语义变更，pending 后必须发布者 approve）
        def apply_and_approve(who_token: str, who_label: str) -> dict[str, Any]:
            status, payload, err = self.http("POST", f"/api/tasks/{task_id}/apply", {}, who_token)
            applied = self.data_of(payload)
            application = applied.get("application") or {}
            app_id = application.get("id")
            claimed_ok = (
                status == 200
                and self.code_of(payload) == 0
                and application.get("status") == "pending"
                and isinstance(app_id, int)
                and applied.get("task", {}).get("status") in ("published", "claimed")
            )
            self.step(
                f"{who_label} 报名（POST /apply → pending）",
                claimed_ok,
                "" if claimed_ok else f"http={status} code={self.code_of(payload)} data={applied} err={err}",
            )
            status, payload, err = self.http(
                "POST", f"/api/applications/{app_id}/decide", {"approve": True}, teacher_token
            )
            approved = self.data_of(payload)
            approved_app = approved.get("application") or {}
            approved_task = approved.get("task") or {}
            ok = (
                status == 200
                and self.code_of(payload) == 0
                and approved_app.get("status") == "approved"
                and approved_task.get("status") == "claimed"
                and int(approved_task.get("approved_count") or 0) >= 1
            )
            self.step(
                f"{who_label} 审批通过（POST /applications/{app_id}/decide）",
                ok,
                "" if ok else f"http={status} code={self.code_of(payload)} data={approved} err={err}",
            )
            return approved

        apply_and_approve(student_token, "student01")
        final_approved = apply_and_approve(student2_token, "student02")
        final_task = final_approved.get("task") or {}
        members_ok = (
            final_task.get("approved_count") == 2
            and sorted(final_task.get("assignee_names") or [])
            == sorted([student.get("display_name", ""), student2.get("display_name", "")])
        )
        self.step(
            "审批后两名 approved 成员（approved_count=2 + assignee_names 两人）",
            members_ok,
            f"approved_count={final_task.get('approved_count')} names={final_task.get('assignee_names')}",
        )

        # 6) 进度 ×2（每名 approved 成员各提交自己进度；首次 claimed→in_progress）
        progress_results = []
        for who_token, who_label, content in (
            (student_token, "student01", "已完成海报初稿"),
            (student2_token, "student02", "已完成签到表"),
        ):
            status, payload, err = self.http(
                "POST", f"/api/tasks/{task_id}/progress", {"content": content}, who_token
            )
            progress = self.data_of(payload)
            progress_results.append(progress)
            ok = (
                status == 200
                and self.code_of(payload) == 0
                and progress.get("content") == content
                and progress.get("task_id") == task_id
            )
            self.step(
                f"{who_label} 提交进度（POST /progress）",
                ok,
                "" if ok else f"http={status} code={self.code_of(payload)} data={progress} err={err}",
            )
        self.step(
            "两名成员进度归属正确（user_id 各为本人）",
            progress_results[0].get("user_id") == student.get("id")
            and progress_results[1].get("user_id") == student2.get("id"),
            f"ids={[p.get('user_id') for p in progress_results]}",
        )
        status, payload, _ = self.http("GET", f"/api/tasks/{task_id}", token=student_token)
        detail = self.data_of(payload)
        contents = [p.get("content") for p in detail.get("progress", [])]
        self.step(
            "进度后任务状态为 in_progress 且 progress_logs 两条",
            status == 200 and self.code_of(payload) == 0 and detail.get("status") == "in_progress"
            and len(detail.get("progress", [])) == 2
            and "已完成海报初稿" in contents and "已完成签到表" in contents,
            f"http={status} status={detail.get('status')} progress={contents}",
        )

        # 7) 提交 ×2（任务级状态只流转一次，第二人提交按幂等成功处理）
        submitted_ok = True
        submitted_detail = ""
        for who_token, who_label in ((student_token, "student01"), (student2_token, "student02")):
            status, payload, err = self.http("POST", f"/api/tasks/{task_id}/submit", {}, who_token)
            submitted = self.data_of(payload)
            ok = status == 200 and self.code_of(payload) == 0 and submitted.get("status") == "submitted"
            submitted_ok = submitted_ok and ok
            if not ok:
                submitted_detail += (
                    f"{who_label}: http={status} code={self.code_of(payload)} "
                    f"status={submitted.get('status')} err={err}；"
                )
        self.step(
            "两名成员均提交完成（POST /submit，第二名幂等成功）",
            submitted_ok,
            submitted_detail,
        )

        # 8) 验收 + 积分
        status, payload, err = self.http(
            "POST", f"/api/tasks/{task_id}/verify", {"pass": True}, teacher_token
        )
        verified = self.data_of(payload)
        credit_delta = verified.get("credit_delta")
        credited = verified.get("credited_user_ids") or []
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and verified.get("task", {}).get("status") == "verified"
            and credit_delta == 25
            and sorted(credited) == sorted([student.get("id"), student2.get("id")])
        )
        self.step(
            "发布者验收（POST /verify，pass=true，credit_delta=25，credited_user_ids 两人）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} data={verified} err={err}",
        )

        credit_ok = True
        credit_detail = ""
        for who_token, who_label in ((student_token, "student01"), (student2_token, "student02")):
            status, payload, err = self.http("GET", "/api/credits/me", token=who_token)
            credits = self.data_of(payload)
            logs = credits.get("logs", [])
            task_logs = [log for log in logs if log.get("task_id") == task_id and log.get("delta") == 25]
            ok = (
                status == 200
                and self.code_of(payload) == 0
                and credits.get("credits") == 25
                and len(task_logs) == 1
            )
            credit_ok = credit_ok and ok
            if not ok:
                credit_detail += (
                    f"{who_label}: http={status} code={self.code_of(payload)} "
                    f"credits={credits.get('credits')} task_logs={len(task_logs)} err={err}；"
                )
        self.step(
            "两人积分各到账 +25（余额 25 + 本任务流水各 1 条）",
            credit_ok,
            credit_detail,
        )

        # 9) 签到 ×2（每名 approved 成员各一条）+ 重复签到对抗探针
        for who_token, who_label, who_id in (
            (student_token, "student01", student.get("id")),
            (student2_token, "student02", student2.get("id")),
        ):
            status, payload, err = self.http("POST", "/api/checkin", {"task_id": task_id}, who_token)
            checkin = self.data_of(payload)
            ok = (
                status == 200
                and self.code_of(payload) == 0
                and checkin.get("task_id") == task_id
                and checkin.get("user_id") == who_id
                and bool(checkin.get("checkin_time"))
            )
            self.step(
                f"{who_label} 签到（POST /api/checkin）",
                ok,
                "" if ok else f"http={status} code={self.code_of(payload)} data={checkin} err={err}",
            )
        status, payload, err = self.http("POST", "/api/checkin", {"task_id": task_id}, student_token)
        self.step(
            "重复签到被拒绝（对抗探针，期望 code!=0）",
            self.code_of(payload) != 0,
            f"http={status} code={self.code_of(payload)} msg={payload.get('msg')}",
        )

        # 10) 通知列表（两名成员各收到「报名已通过」「验收通过」；发布者收到报名申请与签到）
        for who_token, who_label in ((student_token, "student01"), (student2_token, "student02")):
            status, payload, err = self.http("GET", "/api/notifications?limit=50", token=who_token)
            notes = self.data_of(payload)
            titles = [item.get("title", "") for item in notes.get("items", [])]
            ok = (
                status == 200
                and self.code_of(payload) == 0
                and any("报名已通过" in title for title in titles)
                and any("验收通过" in title for title in titles)
                and notes.get("unread", 0) >= 1
            )
            self.step(
                f"{who_label} 通知含报名通过 + 验收通过（unread>=1）",
                ok,
                "" if ok else f"http={status} code={self.code_of(payload)} titles={titles} err={err}",
            )
        status, payload, _ = self.http("GET", "/api/notifications?limit=100", token=teacher_token)
        teacher_titles = [item.get("title", "") for item in self.data_of(payload).get("items", [])]
        ok = any("报名" in title for title in teacher_titles) and any(
            "签到" in title for title in teacher_titles
        )
        self.step(
            "teacher01 通知含报名申请与签到",
            ok,
            f"titles={teacher_titles}",
        )

        # 11) Agent extract（mock + 教三→教四 correction）
        status, payload, err = self.http(
            "POST",
            "/api/agent/extract",
            {"text": "明天下午两点在教三开宣讲会，哎不对是教四，需要2名志愿者，记得措辞严谨一点"},
            student_token,
        )
        extract = self.data_of(payload)
        draft = extract.get("draft", {})
        corrections = extract.get("corrections", [])
        has_correction = any(
            item.get("old_value") == "教三" and item.get("new_value") == "教四" for item in corrections
        )
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and extract.get("mock") is True
            and draft.get("location") == "教四"
            and has_correction
            and bool(draft.get("style_prompt"))
        )
        self.step(
            "Agent extract（mock=true，教三→教四 correction，style_prompt 剥离）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} draft={draft} corrections={corrections} err={err}",
        )

        # 12) Agent review
        review_draft = draft or {"title": "宣讲会", "location": "教四"}
        status, payload, err = self.http(
            "POST", "/api/agent/review", {"draft": review_draft}, student_token
        )
        review = self.data_of(payload)
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and review.get("mock") is True
            and isinstance(review.get("ambiguities"), list)
            and isinstance(review.get("suggested_sub_tasks"), list)
            and review.get("polished") is not None
        )
        self.step(
            "Agent review（mock=true，ambiguities/polished/suggested_sub_tasks）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} keys={list(review)} err={err}",
        )
        self.assert_pure_payload(review, "Agent review")

        # 13) Agent stream/parse 两片（P2 跨片更正保留：教三→教四）
        session_id = "t15-session-1"
        status1, payload1, err1 = self.http(
            "POST",
            "/api/agent/stream/parse",
            {"session_id": session_id, "chunk": "明天下午两点在教三开宣讲会，", "is_final": False},
            student_token,
        )
        first = self.data_of(payload1)
        first_ok = (
            status1 == 200
            and self.code_of(payload1) == 0
            and first.get("mock") is True
            and first.get("draft", {}).get("location") == "教三"
            and not first.get("corrections")
        )
        self.step(
            "stream/parse 第 1 片（location=教三，无 correction）",
            first_ok,
            "" if first_ok else f"http={status1} code={self.code_of(payload1)} data={first} err={err1}",
        )
        status2, payload2, err2 = self.http(
            "POST",
            "/api/agent/stream/parse",
            {"session_id": session_id, "chunk": "哎不对，是教四，", "is_final": False},
            student_token,
        )
        second = self.data_of(payload2)
        second_ok = (
            status2 == 200
            and self.code_of(payload2) == 0
            and second.get("mock") is True
            and second.get("draft", {}).get("location") == "教四"
            and any(
                item.get("old_value") == "教三" and item.get("new_value") == "教四"
                for item in second.get("corrections", [])
            )
        )
        self.step(
            "stream/parse 第 2 片（location=教四，correction 教三→教四）",
            second_ok,
            "" if second_ok else f"http={status2} code={self.code_of(payload2)} data={second} err={err2}",
        )

        # 13b) P3 三片顺序增量链式 + 介绍建议 + 纯值红线（R18-AC3/4/7/10）
        self.probe_agent_chain(student_token)

        # 14) KB similar
        query = urllib.parse.urlencode({"q": "T15 终验任务：教三宣讲会物料准备"})
        status, payload, err = self.http("GET", f"/api/kb/similar?{query}", token=student_token)
        similar = self.data_of(payload)
        similar_items = similar.get("items", [])
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and isinstance(similar_items, list)
            and any(item.get("task_id") == task_id for item in similar_items)
            and similar.get("threshold") == 0.6
        )
        self.step(
            "KB similar（命中已发布任务，threshold=0.6）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} items={similar_items} err={err}",
        )

        # 15) 分解：契约（plan 2.2.7 mock 规则）——仅标题含"晚会"/"秋之韵"时返回 3 条，
        #     其余场景返回空数组；两个分支都要验证，避免把契约正确行为误判为缺陷。
        status, payload, err = self.http(
            "POST", f"/api/tasks/{task_id}/decompose", {}, teacher_token
        )
        decompose = self.data_of(payload)
        suggestions = decompose.get("suggested_sub_tasks", [])
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and decompose.get("mock") is True
            and suggestions == []
        )
        self.step(
            "任务分解·非晚会标题（POST /decompose，mock=true，按契约返回空数组）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} data={decompose} err={err}",
        )

        # 15b) 分解：标题含"秋之韵" ⇒ 固定 3 条（布置场地/活动执行/收尾清场，depends_on=null,0,1）
        status, payload, err = self.http(
            "POST",
            "/api/tasks",
            {
                "title": "秋之韵晚会彩排物料准备",
                "description": "晚会彩排的场地布置、现场执行与收尾清场",
                "deadline": "2026-11-18 18:00",
                "claim_type": "open",
            },
            teacher_token,
        )
        party_id = self.data_of(payload).get("id")
        decompose_ok = False
        decompose_detail = ""
        if not isinstance(party_id, int):
            decompose_detail = f"创建秋之韵任务失败：http={status} code={self.code_of(payload)}"
        else:
            status, payload, err = self.http(
                "POST", f"/api/tasks/{party_id}/decompose", {}, teacher_token
            )
            party = self.data_of(payload)
            subs = party.get("suggested_sub_tasks", [])
            titles = [item.get("title") for item in subs]
            deps = [item.get("depends_on") for item in subs]
            sop_steps = [
                len([line for line in str(item.get("sop_guide", "")).splitlines() if line.strip()])
                for item in subs
            ]
            decompose_ok = (
                status == 200
                and self.code_of(payload) == 0
                and party.get("mock") is True
                and titles == ["布置场地", "活动执行", "收尾清场"]
                and deps == [None, 0, 1]
                and len(sop_steps) == 3
                and all(steps >= 3 for steps in sop_steps)
            )
            decompose_detail = (
                "" if decompose_ok
                else f"http={status} code={self.code_of(payload)} titles={titles} deps={deps} "
                     f"sop_steps={sop_steps} err={err}"
            )
        self.step(
            "任务分解·秋之韵标题（3 条建议 + depends_on=null/0/1 + SOP 各≥3 步）",
            decompose_ok,
            decompose_detail,
        )

        # 16) SSE 实时通知通道（对抗性：并发连接 + 业务事件触发）
        self.probe_sse(teacher_token)
        return task_id

    def assert_pure_payload(self, payload: dict[str, Any], label: str) -> bool:
        """纯值红线（Q1 / R18-AC10）：draft 8 标量 + extra_tags + changes 不含建议语。"""
        markers = ("AI建议", "改为", "用户：")
        problems: list[str] = []
        draft = payload.get("draft") or {}
        for field in (
            "title",
            "time",
            "location",
            "details",
            "quota",
            "volunteer_hours",
            "notes",
            "requirements",
        ):
            value = draft.get(field)
            if isinstance(value, str):
                for marker in markers:
                    if marker in value:
                        problems.append(f"draft.{field} 含「{marker}」")
        for key, value in (draft.get("extra_tags") or {}).items():
            for marker in markers:
                if marker in str(value):
                    problems.append(f"extra_tags[{key}] 含「{marker}」")
        for change in payload.get("changes") or []:
            new_value = change.get("new_value")
            if isinstance(new_value, str):
                for marker in markers:
                    if marker in new_value:
                        problems.append(f"changes[{change.get('field')}] 含「{marker}」")
        return self.step(f"{label} 纯值红线（无 AI建议/改为/用户：）", not problems, "；".join(problems))

    def probe_agent_chain(self, token: str) -> None:
        """P3 顺序增量三片链式 + 介绍建议 + 纯值红线（R18-AC3/4/7/10）。

        断言第 2 片不重复产出 time、第 3 片不重复产出 time/location，
        且 extra_tags["工作内容"] 不重复叠加。
        """
        session_id = "t15-chain-3chunks"
        status, payload, err = self.http(
            "POST",
            "/api/agent/stream/parse",
            {"session_id": session_id, "chunk": "明天下午两点", "is_final": False},
            token,
        )
        first = self.data_of(payload)
        first_fields = [item.get("field") for item in first.get("changes") or []]
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and first.get("draft", {}).get("time") == "明天下午两点"
            and "time" in first_fields
        )
        self.step(
            "三片链式·第 1 片（time=明天下午两点，changes 含 time）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} draft={first.get('draft')} fields={first_fields} err={err}",
        )
        self.assert_pure_payload(first, "三片链式·第 1 片")

        status, payload, err = self.http(
            "POST",
            "/api/agent/stream/parse",
            {"session_id": session_id, "chunk": "在操场", "is_final": False},
            token,
        )
        second = self.data_of(payload)
        second_fields = [item.get("field") for item in second.get("changes") or []]
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and second.get("draft", {}).get("location") == "操场"
            and "time" not in second_fields
            and second_fields == ["location"]
        )
        self.step(
            "三片链式·第 2 片（location=操场，changes 不含 time）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} fields={second_fields} err={err}",
        )
        self.assert_pure_payload(second, "三片链式·第 2 片")

        status, payload, err = self.http(
            "POST",
            "/api/agent/stream/parse",
            {"session_id": session_id, "chunk": "搬桌椅，3 个人", "is_final": True},
            token,
        )
        third = self.data_of(payload)
        third_draft = third.get("draft", {})
        third_fields = [item.get("field") for item in third.get("changes") or []]
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and third_draft.get("quota") == 3
            and third_draft.get("extra_tags") == {"工作内容": "搬桌椅"}
            and "time" not in third_fields
            and "location" not in third_fields
            and set(third_fields) == {"quota", "extra_tags.工作内容"}
        )
        self.step(
            "三片链式·第 3 片（quota=3，changes 不含 time/location，extra_tags 不重复）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} draft={third_draft} fields={third_fields} err={err}",
        )
        self.assert_pure_payload(third, "三片链式·第 3 片")

        # B10：details 空 + style_prompt ⇒ 完整介绍建议，且不进入 changes / 不写字段
        intro_draft = {
            "title": "秋之韵志愿招募",
            "time": "明天下午两点",
            "location": "操场",
            "quota": 3,
            "extra_tags": {"工作内容": "搬桌椅"},
            "style_prompt": "温柔一点",
        }
        status, payload, err = self.http(
            "POST", "/api/agent/review", {"draft": intro_draft}, token
        )
        intro = self.data_of(payload)
        polished = intro.get("polished") or {}
        intro_details = (polished.get("details") or "").strip()
        intro_changes = intro.get("changes") or []
        markers = ("AI建议", "改为", "用户：")
        ok = (
            status == 200
            and self.code_of(payload) == 0
            and intro.get("mock") is True
            and len(intro_details) >= 20
            and "秋之韵志愿招募" in intro_details
            and not any(item.get("field") in ("details", "notes") for item in intro_changes)
            and not any(marker in intro_details for marker in markers)
        )
        self.step(
            "Agent review·介绍建议（details 空 + style ⇒ polished.details 完整、不落字段）",
            ok,
            "" if ok else f"http={status} code={self.code_of(payload)} polished={polished} changes={intro_changes} err={err}",
        )
        self.assert_pure_payload(intro, "Agent review·介绍建议")

    def probe_sse(self, teacher_token: str) -> None:
        bucket: dict[str, Any] = {"status": None, "ctype": "", "lines": []}
        errors: list[str] = []

        def worker() -> None:
            url = f"{BASE}/api/notifications/stream?token={urllib.parse.quote(teacher_token)}"
            request = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    bucket["status"] = response.status
                    bucket["ctype"] = response.headers.get("Content-Type", "")
                    deadline = time.time() + 18
                    while time.time() < deadline:
                        line = response.readline()
                        if not line:
                            break
                        text = line.decode("utf-8", errors="replace").strip()
                        if text.startswith("event:") or text.startswith("data:"):
                            bucket["lines"].append(text)
                        if len(bucket["lines"]) >= 2:
                            break
            except Exception as exc:  # 连接被关闭/超时都记录
                errors.append(f"{type(exc).__name__}: {exc}")

        worker_thread = threading.Thread(target=worker, daemon=True)
        worker_thread.start()
        time.sleep(0.8)

        # 触发 teacher01 的一条新通知：student01 认领第二个任务
        teacher_token = self.teacher.get("token", "")
        status, payload, err = self.http(
            "POST",
            "/api/tasks",
            {"title": "T15 SSE 探针任务", "deadline": "2026-11-20 18:00", "claim_type": "open"},
            teacher_token,
        )
        probe_id = self.data_of(payload).get("id")
        if isinstance(probe_id, int):
            self.http("POST", f"/api/tasks/{probe_id}/apply", {}, self.student.get("token", ""))

        worker_thread.join(timeout=20)
        lines = bucket.get("lines", [])
        event_ok = any(line.startswith("event: notify") for line in lines)
        data_ok = any(line.startswith("data:") and "SSE 探针任务" in line for line in lines)
        ok = (
            bucket.get("status") == 200
            and "text/event-stream" in str(bucket.get("ctype", ""))
            and event_ok
            and data_ok
        )
        self.step(
            "SSE 实时通知（event: notify + 认领事件 data）",
            ok,
            "" if ok else f"status={bucket.get('status')} ctype={bucket.get('ctype')} lines={lines} err={errors}",
        )

    def probe_frontend(self) -> None:
        ok_pages = True
        details: list[str] = []
        html = ""
        for path in ("/", "/login", "/tasks"):
            try:
                with urllib.request.urlopen(FRONTEND_BASE + path, timeout=10) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    if resp.status != 200 or '<div id="app">' not in body:
                        ok_pages = False
                        details.append(f"{path} http={resp.status} app_div={('<div id=\"app\">' in body)}")
                    elif path == "/":
                        html = body
            except Exception as exc:
                ok_pages = False
                details.append(f"{path} {type(exc).__name__}: {exc}")
        self.step("前端 preview 页面 200（/、/login、/tasks 均含 #app）", ok_pages, "；".join(details))

        assets = re.findall(r'(?:src|href)="([^"]+\.(?:js|css))"', html)
        asset_ok = bool(assets)
        asset_details: list[str] = []
        for asset in assets:
            try:
                with urllib.request.urlopen(FRONTEND_BASE + asset, timeout=10) as resp:
                    size = len(resp.read())
                    if resp.status != 200 or size == 0:
                        asset_ok = False
                    asset_details.append(f"{asset} {resp.status} {size}B")
            except Exception as exc:
                asset_ok = False
                asset_details.append(f"{asset} {type(exc).__name__}: {exc}")
        self.step(
            "dist 静态资源可访问（js/css 200 且非空）",
            asset_ok,
            "；".join(asset_details),
        )

    def probe_round4_source(self) -> None:
        """第四轮探针：C1 默认 AI 模式（源码级）+ C2 字号基线（构建产物级）。

        为什么 C1 只做「源码断言」而不做「构建产物 / DOM 断言」：
        1. 本脚本无 Playwright / Selenium（plan O-D4-1），无法运行浏览器读 DOM 激活态；
        2. ``frontend/dist/assets/*.js`` 经 Vite 压缩 + 变量改名，``activeTab`` 的初值
           ``'ai'`` 在 bundle 内无法稳定定位（压缩后可能内联进 setup 闭包）；
        3. 源码与运行同仓（同一编译单元），``ref<PublishMode>('ai')`` + 双 ``v-show`` 面板
           足以证明默认态的实现事实；**「Tab 实际激活 / 切换后草稿保留」仍是人工项 M23**，
           在 ``ACCEPTANCE.md`` 记为 DEFERRED，不得由本探针冒充。

        C2 则可以做构建产物探针：``typography.css`` 是否真的进入打包后的 CSS，
        决定 Element Plus 变量覆盖在运行时是否生效。
        """
        source_path = self.root / "frontend" / "src" / "views" / "PublishPage.vue"
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            self.step("C1 发布页默认 AI 智能模式（源码断言）", False, f"读取失败：{exc}")
            return

        default_ai = "ref<PublishMode>('ai')" in source
        manual_panel = 'v-show="activeTab === \'manual\'"' in source
        ai_panel = 'v-show="activeTab === \'ai\'"' in source
        mode_panel_vif = any(
            "mode-panel" in line and 'v-if="activeTab' in line for line in source.splitlines()
        )
        ok = default_ai and manual_panel and ai_panel and not mode_panel_vif
        self.step(
            "C1 发布页默认 AI 智能模式（源码断言：activeTab='ai' + 双 v-show 面板 + .mode-panel 无 v-if）",
            ok,
            ""
            if ok
            else (
                f"default_ai={default_ai} manual_panel={manual_panel} "
                f"ai_panel={ai_panel} mode_panel_vif={mode_panel_vif}"
            ),
        )

        dist_assets = self.root / "frontend" / "dist" / "assets"
        css_files = sorted(dist_assets.glob("*.css")) if dist_assets.is_dir() else []
        if not css_files:
            self.step(
                "C2 构建产物含字号基线变量（--el-font-size-base:15px）",
                False,
                f"未找到 dist CSS：{dist_assets}（请先执行 npm run build）",
            )
            return
        merged = "".join(path.read_text(encoding="utf-8", errors="replace") for path in css_files)
        compact = re.sub(r"\s+", "", merged)
        expected_vars = {
            "--el-font-size-base": "15px",
            "--el-font-size-small": "14px",
            "--el-font-size-extra-small": "13px",
        }
        missing = [
            f"{name}:{value}"
            for name, value in expected_vars.items()
            if f"{name}:{value}" not in compact
        ]
        self.step(
            "C2 构建产物含字号基线变量（base:15px / small:14px / extra-small:13px）",
            not missing,
            "" if not missing else f"构建产物 CSS 缺少 {missing}（typography.css 未被引入打包？）",
        )

    # -- 第五轮源码探针（D1~D4） -------------------------------------------
    @staticmethod
    def _strip_ts_comments(text: str) -> str:
        """把 TS 注释替换为等长空白（保留换行，避免注释里的伪代码参与结构判定）。"""
        without_block = re.sub(
            r"/\*.*?\*/",
            lambda match: re.sub(r"[^\n]", " ", match.group(0)),
            text,
            flags=re.S,
        )
        return re.sub(
            r"//[^\n]*",
            lambda match: " " * len(match.group(0)),
            without_block,
        )

    @staticmethod
    def _extract_balanced(text: str, open_index: int) -> str:
        """从 ``text[open_index] == '{'`` 起提取配对的花括号片段。"""
        if open_index < 0 or open_index >= len(text) or text[open_index] != "{":
            raise ValueError("括号提取起点不是 '{'")
        depth = 0
        for index in range(open_index, len(text)):
            char = text[index]
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return text[open_index : index + 1]
        raise ValueError("花括号未闭合")

    @classmethod
    def _function_body(cls, text: str, name: str) -> tuple[str, int]:
        """按符号名提取 ``function name(...) { ... }`` 的函数体（1 基起始行号）。"""
        pattern = re.compile(
            rf"(?:export\s+)?(?:async\s+)?function\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*\("
        )
        match = pattern.search(text)
        if match is None:
            raise ValueError(f"未找到函数 {name}()")
        open_paren = text.find("(", match.end() - 1)
        depth = 0
        close_paren = -1
        for index in range(open_paren, len(text)):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_paren = index
                    break
        if close_paren < 0:
            raise ValueError(f"函数 {name}() 的参数列表未闭合")
        brace_index = text.find("{", close_paren)
        if brace_index < 0:
            raise ValueError(f"函数 {name}() 的签名后未找到函数体")
        return cls._extract_balanced(text, brace_index), text.count("\n", 0, brace_index) + 1

    def probe_round5_source(self) -> None:
        """第五轮 D1~D4 的源码级探针（真机 / 浏览器项仍按 M29~M31 记 DEFERRED）。

        覆盖边界与 ``check_contracts.py`` 的 ㉒~㉕ 一致：本探针不替代契约检查，
        而是在无头 E2E 侧独立复算一遍（同一事实、不同实现路径），防止夹具被单点改坏。
        """
        frontend = self.root / "frontend"

        # D1：allowedHosts 恰 1 个元素 + port / proxy 冻结值
        try:
            vite = (frontend / "vite.config.ts").read_text(encoding="utf-8")
        except OSError as exc:
            self.step("D1 allowedHosts 放行 *.takin.cc（源码断言）", False, f"读取失败：{exc}")
        else:
            host_match = re.search(r"allowedHosts\s*:\s*\[([^\]]*)\]", vite)
            hosts = (
                re.findall(r"['\"]([^'\"]+)['\"]", host_match.group(1))
                if host_match is not None
                else []
            )
            host_occurrences = len(re.findall(r"\ballowedHosts\b", vite))
            d1_ok = (
                hosts == [".takin.cc"]
                and host_occurrences == 1
                and re.search(r"port\s*:\s*5173", vite) is not None
                and re.search(r"target\s*:\s*['\"]http://127\.0\.0\.1:8000['\"]", vite)
                is not None
                and re.search(r"changeOrigin\s*:\s*true", vite) is not None
            )
            self.step(
                "D1 allowedHosts 恰 ['.takin.cc'] + port/proxy 冻结（源码断言）",
                d1_ok,
                "" if d1_ok else f"hosts={hosts} allowedHosts_occurrences={host_occurrences}",
            )

        try:
            composer_raw = (
                frontend / "src" / "composables" / "useVoiceComposer.ts"
            ).read_text(encoding="utf-8")
            slicer_raw = (frontend / "src" / "utils" / "voiceSlicer.ts").read_text(
                encoding="utf-8"
            )
        except OSError as exc:
            self.step("D2 续接保留 dedupTail（源码断言）", False, f"读取失败：{exc}")
            self.step("D3 trimRestartOverlap 导出与接入（源码断言）", False, "读取失败")
            self.step("D4 commitStoppedSession 首行幂等守卫（源码断言）", False, "读取失败")
            return

        composer = self._strip_ts_comments(composer_raw)
        slicer = self._strip_ts_comments(slicer_raw)

        # D2：dedupTail 只在 else（新建会话）分支清空
        try:
            start_body, _ = self._function_body(composer, "start")
            condition = re.search(
                r"if\s*\(\s*options\.keepSession\s*&&\s*sessionId\s*\)\s*\{", start_body
            )
            if condition is None:
                raise ValueError("未找到 keepSession 分支条件")
            if_open = start_body.find("{", condition.end() - 1)
            if_body = self._extract_balanced(start_body, if_open)
            tail = start_body[if_open + len(if_body) :]
            else_match = re.match(r"\s*else\s*\{", tail)
            if else_match is None:
                raise ValueError("keepSession 分支后未找到 else 分支")
            else_body = self._extract_balanced(tail, else_match.end() - 1)
            keep_session_clear = "dedupTail = ''" in if_body
            new_session_clear = "dedupTail = ''" in else_body
            d2_ok = new_session_clear and not keep_session_clear
            d2_detail = (
                ""
                if d2_ok
                else f"keepSession_clear={keep_session_clear} newSession_clear={new_session_clear}"
            )
        except ValueError as exc:
            d2_ok, d2_detail = False, f"分支提取失败：{exc}"
        self.step("D2 续接保留 dedupTail、新建会话才清空（源码断言）", d2_ok, d2_detail)

        # D3：纯函数导出 + 仅在追加路径接入（replaceTail 内零命中）
        d3_problems: list[str] = []
        if "export function trimRestartOverlap" not in slicer:
            d3_problems.append("voiceSlicer 未导出 trimRestartOverlap")
        if re.search(r"import\s*\{[^}]*\btrimRestartOverlap\b", composer) is None:
            d3_problems.append("useVoiceComposer 未引入 trimRestartOverlap")
        try:
            for name in ("applyInterim", "applyFinal"):
                body, _ = self._function_body(composer, name)
                if "trimResumedTranscript(" not in body:
                    d3_problems.append(f"{name} 未接入 trimResumedTranscript")
            replace_body, _ = self._function_body(composer, "replaceTail")
            if "trimResumedTranscript(" in replace_body or "trimRestartOverlap(" in replace_body:
                d3_problems.append("replaceTail 内出现重吐裁剪")
            trim_body, _ = self._function_body(composer, "trimResumedTranscript")
            if "trimRestartOverlap(" not in trim_body:
                d3_problems.append("trimResumedTranscript 未调用 trimRestartOverlap")
        except ValueError as exc:
            d3_problems.append(f"函数提取失败：{exc}")
        if "RESUMED_RESTART_FRAME_BUDGET = 3" not in composer:
            d3_problems.append("缺少 RESUMED_RESTART_FRAME_BUDGET = 3")
        self.step(
            "D3 trimRestartOverlap 导出 + 仅追加路径接入（源码断言）",
            not d3_problems,
            "" if not d3_problems else "；".join(d3_problems),
        )

        # D4：commitStoppedSession 首条有效语句为幂等守卫
        try:
            commit_body, _ = self._function_body(composer, "commitStoppedSession")
            lines = [line.strip() for line in commit_body.splitlines() if line.strip()]
            first = lines[1] if lines and lines[0] == "{" else (lines[0] if lines else "")
            d4_ok = first.startswith("if (!stopping) return")
            d4_detail = "" if d4_ok else f"首条有效语句={first!r}"
        except ValueError as exc:
            d4_ok, d4_detail = False, f"函数提取失败：{exc}"
        self.step("D4 commitStoppedSession 首行幂等守卫（源码断言）", d4_ok, d4_detail)

    # -- 主流程 -------------------------------------------------------------
    def run(self) -> int:
        print("=" * 72)
        print(" T15 无头端到端功能验收")
        print(f" 工程根：{self.root}")
        print(f" 后端：{BASE}（临时库 {self.db_path}）")
        print(f" 前端：{FRONTEND_BASE}")
        print("=" * 72)

        if not self.python.exists():
            print(f"[FATAL] 未找到后端虚拟环境解释器：{self.python}", file=sys.stderr)
            return 2
        if not (self.frontend_dir / "dist" / "index.html").exists():
            print("[FATAL] frontend/dist 不存在，请先执行 npm run build", file=sys.stderr)
            return 2

        started = False
        try:
            if not self.start_backend():
                self.step("后端启动并 /api/health 就绪", False, "80 次轮询均未就绪")
                return 2
            started = True
            status, payload, _ = self.http("GET", "/api/health")
            health = self.data_of(payload)
            self.step(
                "后端健康检查（code=0、tables=9、mock=true）",
                status == 200
                and self.code_of(payload) == 0
                and sorted(health.get("tables", []))
                == sorted(
                    {
                        "users",
                        "tasks",
                        "checkins",
                        "credit_logs",
                        "notifications",
                        "kb_entries",
                        "parse_sessions",
                        "progress_logs",
                        "task_applications",
                    }
                )
                and health.get("mock") is True,
                f"http={status} data={health}",
            )

            self.run_business_flow()

            # 第四轮（C1/C2）：源码级 + 构建产物级探针，不依赖前后端起服务
            self.probe_round4_source()
            # 第五轮（D1~D4）：源码级探针，不依赖浏览器 / 麦克风；真机项见 M29~M31
            self.probe_round5_source()

            if not self.start_frontend():
                self.step("前端 preview 启动", False, "80 次轮询均未就绪")
            else:
                self.probe_frontend()
        finally:
            self.stop_all()
            self.clean_temp()

        failed = [result for result in self.results if not result.ok]
        print("-" * 72)
        print(f" 汇总：{len(self.results) - len(failed)} PASS / {len(failed)} FAIL / 共 {len(self.results)} 项")
        if failed:
            print(" 失败项：")
            for result in failed:
                print(f"  ✗ {result.name}")
            print(" 结论：无头 E2E FAIL")
            print("=" * 72)
            return 1
        print(" 结论：无头 E2E PASS")
        print("=" * 72)
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T15 无头端到端功能验收（只读业务、使用临时库）")
    parser.add_argument(
        "--root",
        default=str(Path(__file__).resolve().parents[2]),
        help="工程根目录（默认：tests/security 上两级）",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="保留临时数据库目录（默认删除）",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"[FATAL] 工程根不存在：{root}", file=sys.stderr)
        return 2
    return HeadlessE2E(root, keep_temp=args.keep_temp).run()


if __name__ == "__main__":
    raise SystemExit(main())