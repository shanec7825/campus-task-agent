"""V1 部署验收冒烟（本机生产形态，非远程部署）。

做的事：
1. 用临时目录准备隔离库与资料上传根，调用 ``scripts/seed_phase2_demo.py`` 生成演示账号；
2. 以 ``MAAS_MOCK=1``、``RUN_SCHEDULER=0`` 启动 uvicorn（默认 8010），由 ``app.main`` 同源托管 ``frontend/dist``；
3. 校验健康检查、静态首页/资源、未登录 401、登录后的任务/引用/AI 草案/组织资料上传与越权路径；
4. 输出 JSON 结果到 stdout，并在结束时停止服务、删除临时目录。

用法（仓库根，先构建前端 ``cd frontend && npm run build``）：
    python scripts/deploy_smoke.py
可选环境变量：``DEPLOY_PORT``（默认 8010）、``DEPLOY_TIMEOUT``（秒，默认 40）。
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DIST = ROOT / "frontend" / "dist"
def _free_port() -> int:
    """选一个当前空闲端口，避免与遗留进程（8000/8010）冲突。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


PORT = int(os.getenv("DEPLOY_PORT") or _free_port())
TIMEOUT = float(os.getenv("DEPLOY_TIMEOUT", "40"))
PASSWORD = "TestPass123!"
BASE = f"http://127.0.0.1:{PORT}"


def _wait_health(client: httpx.Client) -> dict:
    deadline = time.time() + TIMEOUT
    last: Exception | None = None
    while time.time() < deadline:
        try:
            resp = client.get(f"{BASE}/api/health", timeout=2.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception as exc:  # noqa: BLE001 启动期间连接失败属预期
            last = exc
        time.sleep(0.5)
    raise SystemExit(f"服务未在 {TIMEOUT}s 内就绪：{last}")


def _login(client: httpx.Client, username: str) -> dict:
    resp = client.post(f"{BASE}/api/auth/login", json={"username": username, "password": PASSWORD})
    body = resp.json()
    if body.get("code") != 0:
        raise SystemExit(f"登录失败（{username}）：{body}")
    return body["data"]


def _body(resp: httpx.Response) -> dict:
    """尽量解析 JSON；非 JSON 时回传状态与正文片段，便于失败定位。"""
    try:
        return resp.json()
    except Exception:  # noqa: BLE001
        return {"_status": resp.status_code, "_raw": resp.text[:200]}


def _csrf(client: httpx.Client) -> str:
    return client.cookies.get("cta_csrf") or ""


def main() -> int:
    if not DIST.is_dir():
        raise SystemExit("缺少 frontend/dist，请先运行 npm run build")
    if not shutil.which("python"):
        raise SystemExit("找不到 python")

    tmp = Path(tempfile.mkdtemp(prefix="cta-deploy-"))
    db_path = tmp / "deploy.db"
    env = {
        **os.environ,
        "DATABASE_PATH": str(db_path),
        "ORG_LIBRARY_UPLOAD_ROOT": str(tmp / "org"),
        "MAAS_MOCK": "1",
        "MAAS_API_KEY": "",
        "RUN_SCHEDULER": "0",
        "AI_DAILY_QUOTA": "50",
        "PYTHONUTF8": "1",
    }
    seed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_phase2_demo.py")],
        env=env,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if seed.returncode != 0:
        raise SystemExit(f"演示数据初始化失败：{seed.stdout}\n{seed.stderr}")

    server_log = tmp / "uvicorn.log"
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(BACKEND),
        env=env,
        stdout=server_log.open("w", encoding="utf-8", errors="replace"),
        stderr=subprocess.STDOUT,
    )
    results: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        admin = httpx.Client(base_url=BASE, follow_redirects=False, timeout=15.0)
        member = httpx.Client(base_url=BASE, follow_redirects=False, timeout=15.0)

        if server.poll() is not None:
            raise SystemExit("服务启动即退出：" + server_log.read_text(encoding="utf-8", errors="replace")[-800:])
        health = _wait_health(admin)
        tables = health.get("data", {}).get("tables", [])
        check("health", health.get("code") == 0 and health.get("data", {}).get("status") == "ok",
              json.dumps(health, ensure_ascii=False)[:200])
        check("health.tables=26", len(tables) == 26, f"{len(tables)} tables")
        check("health.mock", health.get("data", {}).get("mock") is True, str(health.get("data", {}).get("mock")))

        index = admin.get(f"{BASE}/")
        check("static index", index.status_code == 200 and "<div id=\"app\">" in index.text,
              f"HTTP {index.status_code}, {len(index.text)} bytes")
        assets = sorted((DIST / "assets").glob("*.js"))
        if assets:
            asset = admin.get(f"{BASE}/assets/{assets[0].name}")
            check("static asset", asset.status_code == 200 and len(asset.content) > 0,
                  f"{assets[0].name} HTTP {asset.status_code}, {len(asset.content)} bytes")
        else:
            check("static asset", False, "dist/assets 无 js 文件")

        unauth = admin.get(f"{BASE}/api/tasks")
        body = _body(unauth)
        check("unauth 401", unauth.status_code == 401 and body.get("code") == 4010,
              f"HTTP {unauth.status_code}, code={body.get('code')}")

        admin_user = _login(admin, "orgadmin")
        check("login orgadmin", admin_user.get("user", {}).get("username") == "orgadmin",
              json.dumps(admin_user.get("user", {}), ensure_ascii=False)[:160])

        tasks = admin.get(f"{BASE}/api/tasks")
        check("tasks list", _body(tasks).get("code") == 0,
              f"HTTP {tasks.status_code}, count={len(_body(tasks).get('data', {}).get('items', []))}")

        refs = admin.get(f"{BASE}/api/library/refs")
        refs_body = _body(refs)
        check("library refs", refs.status_code == 200 and refs_body.get("code") == 0
              and "items" in refs_body.get("data", {}),
              f"HTTP {refs.status_code}, body={refs.text[:160]!r}")

        draft = admin.post(
            f"{BASE}/api/ai/task-draft",
            json={"prompt": "为迎新晚会生成策划、宣传、执行三个任务", "org_id": None},
            headers={"X-CSRF-Token": _csrf(admin)},
        )
        draft_body = _body(draft)
        draft_tasks = draft_body.get("data", {}).get("tasks", [])
        check("ai task-draft", draft_body.get("code") == 0 and len(draft_tasks) >= 2,
              f"HTTP {draft.status_code}, tasks={len(draft_tasks)}, mock={draft_body.get('data', {}).get('mock')}")

        org_id = (admin_user.get("orgs") or [{}])[0].get("org_id")
        upload = admin.post(
            f"{BASE}/api/org-resources",
            json={
                "org_id": org_id,
                "title": "部署验收资料",
                "summary": "冒烟用文本资料",
                "file": {
                    "name": "smoke.md",
                    "mime": "text/markdown",
                    "size": len("# 迎新晚会策划\n\n往届流程与分工。".encode()),
                    "data_base64": __import__("base64").b64encode(
                        "# 迎新晚会策划\n\n往届流程与分工。".encode()
                    ).decode(),
                },
            },
            headers={"X-CSRF-Token": _csrf(admin)},
        )
        upload_body = _body(upload)
        resource = upload_body.get("data", {})
        check("org resource upload", upload_body.get("code") == 0
              and resource.get("text_status") == "ready"
              and resource.get("allow_student_ai") in (False, 0),
              json.dumps(resource, ensure_ascii=False)[:200])

        _login(member, "member01")
        member_list = member.get(f"{BASE}/api/org-resources", params={"org_id": org_id})
        check("member cannot list org resources", _body(member_list).get("code") == 4030,
              f"HTTP {member_list.status_code}, code={_body(member_list).get('code')}")

        save_ref = member.post(
            f"{BASE}/api/library/refs",
            json={"resource_id": resource.get("id")},
            headers={"X-CSRF-Token": _csrf(member)},
        )
        check("closed resource not referenceable", _body(save_ref).get("code") == 4040,
              f"HTTP {save_ref.status_code}, code={_body(save_ref).get('code')}")

        check("server alive", server.poll() is None, f"pid={server.pid}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for item in results if item["ok"])
    print(json.dumps({"passed": passed, "total": len(results), "results": results},
                     ensure_ascii=False, indent=2))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())