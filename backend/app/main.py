"""FastAPI 应用入口（契约 `C-BOOT@1`，T1 提供）。

启动顺序（lifespan）：``init_db()`` → ``notification_hub.bind_loop()`` →
``RUN_SCHEDULER`` 为真时 ``reminder_scheduler.start()``；关闭时
``reminder_scheduler.shutdown()``。
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import routers
from app.db import Base, init_db
from app.routers import activities as activities_router
from app.routers import orgs as orgs_router
from app.routers import registration as registration_router
from app.errors import ApiError, ok
from app.services import notification_hub, reminder_scheduler

logger = logging.getLogger("campus_task_agent")

DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    return origins or [item.strip() for item in DEFAULT_CORS_ORIGINS.split(",")]


def _run_scheduler() -> bool:
    return os.getenv("RUN_SCHEDULER", "1").strip() not in {"0", "false", "False", ""}


def is_mock_mode() -> bool:
    """Mock 判定入口。

    T1 阶段 ``agents/llm_client.py`` 尚未创建，回退到环境变量；
    T3 提供 ``llm_client.is_mock_mode()`` 后自动以该函数为唯一权威。
    """
    try:  # pragma: no cover - T3 交付后必然命中
        from app.agents.llm_client import is_mock_mode as llm_is_mock_mode

        return bool(llm_is_mock_mode())
    except (ImportError, AttributeError):
        return os.getenv("MAAS_MOCK", "0").strip() == "1" or not os.getenv("MAAS_API_KEY", "").strip()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    notification_hub.bind_loop(asyncio.get_running_loop())
    if _run_scheduler():
        reminder_scheduler.start()
    else:
        logger.info("RUN_SCHEDULER=0，跳过催办调度器启动")
    try:
        yield
    finally:
        reminder_scheduler.shutdown()


app = FastAPI(
    title="校园任务协同 AI Agent API",
    version="1.0.0",
    description="校园任务发布 / 认领 / 进度 / 验收 / 积分 / 催办（P1 契约基线）",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# 统一异常处理：响应体固定 {"code","msg","data"}
# --------------------------------------------------------------------------- #
@app.exception_handler(ApiError)
async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    response = JSONResponse(status_code=exc.http_status, content=exc.to_payload())
    if exc.http_status == 401:
        # 会话失效/过期的 401 必须同时清除 Cookie（`C-SESSION@1`），否则客户端会反复携带同一失效令牌。
        from app.services.session_service import clear_session_cookies

        clear_session_cookies(response)
    return response


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """请求体 / 查询参数校验失败 ⇒ code=4001（HTTP 200，与业务错误口径一致）。"""
    logger.info("参数校验失败: %s", exc.errors())
    return JSONResponse(
        status_code=200,
        content={"code": 4001, "msg": "参数校验失败", "data": None},
    )


@app.exception_handler(Exception)
async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
    logger.exception("未捕获异常: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"code": 5000, "msg": "服务器内部错误", "data": None},
    )


# --------------------------------------------------------------------------- #
# 健康检查（不鉴权，R8-AC4 例外）
# --------------------------------------------------------------------------- #
@app.get("/api/health", tags=["system"])
def health() -> dict[str, Any]:
    return ok(
        {
            "status": "ok",
            "tables": sorted(Base.metadata.tables.keys()),
            "mock": is_mock_mode(),
        }
    )


# --------------------------------------------------------------------------- #
# 路由挂载：T1 一次性挂载 7 个模块，后续 owner 无需修改本文件；
# 阶段 1 追加活动路由（`C-ACTIVITY-API@1`）；
# 阶段 2 追加组织与注册路由（`C-ORG@1`，T1 预挂载）。
# --------------------------------------------------------------------------- #
app.include_router(routers.auth.router)
app.include_router(routers.tasks.router)
app.include_router(routers.applications.router)
app.include_router(routers.checkin.router)
app.include_router(routers.credits.router)
app.include_router(routers.notifications.router)
app.include_router(routers.kb.router)
app.include_router(routers.agent.router)
app.include_router(activities_router.router)
app.include_router(orgs_router.router)
app.include_router(registration_router.router)

# --------------------------------------------------------------------------- #
# 生产形态静态托管（首屏加速）：dist 同源托管，避免经 1Mbps 隧道拉取数百个 ESM
# 模块。必须放在全部 /api router 与 /api/health 之后，避免 catch-all 吃掉 API。
# dist 不存在时整段跳过，本机 dev / 测试不受影响。
# --------------------------------------------------------------------------- #
from pathlib import Path  # noqa: E402  (置于文件末尾，避免改动既有导入区)

from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.is_dir():
    _assets = _dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa_fallback(full_path: str):
        # 路径穿越防护：解析后的目标必须仍位于 dist 内；否则回落到 index.html
        target = (_dist / full_path).resolve()
        if full_path and target.is_file() and _dist in target.parents:
            return FileResponse(target)
        return FileResponse(_dist / "index.html")