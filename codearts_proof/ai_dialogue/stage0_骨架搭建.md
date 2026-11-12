# 阶段 0 · 骨架搭建

> **归档口径**：本文件是「AI 交互对话整理版」（官方硬性要求 md 格式）。
> 当前状态：**结构已建立，对话原文尚未归档 —— 待该阶段收尾由哨兵整理**。
> 下方「产出」清单全部为本仓库中**真实存在**的文件；「输入 Prompt」只摘录《校园任务协同AI-Agent-开发方案》第 12 章已有的指令要点，**不臆造任何对话内容**。

## 阶段

阶段 0：搭骨架，不写业务。目标是先把前后端可运行的基线与契约固定下来，为后续并行开发提供稳定底座。

- 工期定位：项目启动第一步（唯一关键路径起点，对应任务 T1）。
- 完成标准：前后端均能本地启动；`GET /api/health` 返回统一响应体；8 张表建表成功。

## 使用的 Agent

| Agent | 模型 | 本阶段职责 |
|---|---|---|
| 领航员（Leader） | GLM-5.3-Flash | 按契约拆分 T1，明确写集与验收条件，派发给构造师与画师并行 |
| 构造师 | **DeepSeek-V4.1-Flash-1017** | 后端骨架：FastAPI 入口、错误体、DB 与 8 张表、Pydantic 模型、7 个路由桩 |
| 画师 | **DeepSeek-V4.1-Flash-1017** | 前端骨架：Vite + Vue3 工程、路由表、Pinia、字段颜色池、6 个页面空壳 |
| 哨兵 | **DeepSeek-V4.1-Flash-1017** | 骨架一致性检查：统一响应体、`.env` 未入库、颜色池键值与契约一致 |

## 输入 Prompt

- 下发方式：把 `prompts/agent_team_启动指令/` 中阶段 0 的启动原文整段发给 Leader（**原文待归档**）。
- 要点（摘自《开发方案》第 12 章阶段 0，实际下发版本以归档原文为准）：
  1. 角色交代：Leader 拆解后派给构造师（后端）与画师（前端）并行；
  2. 后端：FastAPI 可启动、`/api/health` 返回 ok、按方案第 3 章建 8 张表、配置 CORS、`requirements.txt` 含指定依赖；
  3. 前端：Vue3 可启动、配好 vue-router 与 Pinia、创建 `styles/color-pool.css` 写入字段颜色映射；
  4. 安全：创建 `.env.example` 并把 `.env` 写入 `.gitignore`；
  5. 验收：前后端可启动、`/api/health` 通、8 张表建表成功。
- **对话原文：待该阶段收尾由哨兵整理（占位，禁止编造）。**

## 产出

| 文件 | 说明 |
|---|---|
| `backend/app/main.py` | 应用入口：lifespan（init_db → bind_loop → 可选启动调度器）、CORS、异常处理、7 路由挂载、`/api/health` |
| `backend/app/errors.py` | `ApiError` 与统一响应 `ok()`（`{code,msg,data}`） |
| `backend/app/db.py` | 引擎、`SessionLocal`、`Base`、`get_db()`、`init_db()` |
| `backend/app/models.py` | 8 张表：users / tasks / checkins / credit_logs / notifications / kb_entries / parse_sessions / progress_logs |
| `backend/app/schemas.py` | Pydantic 模型（冻结契约，后续任务只消费） |
| `backend/app/deps.py` | `get_current_user` 鉴权依赖基线 |
| `backend/app/routers/*.py` | 7 个模块路由桩：auth / tasks / checkin / credits / notifications / kb / agent |
| `backend/app/services/notification_hub.py` | SSE 连接注册表最小实现 |
| `backend/app/utils/jsonx.py` | TEXT 列 JSON 读写工具 |
| `backend/requirements.txt` | 后端依赖（宽下限 + APScheduler <4） |
| `backend/.env.example` | 环境变量占位值（不含真实 Key） |
| `frontend/src/main.ts`、`App.vue` | 应用挂载与根组件（登录页不套布局） |
| `frontend/src/router/index.ts` | 6 条路由 + 重定向 `/` → `/tasks` |
| `frontend/src/stores/{user,notifications,draft}.ts` | Pinia store 骨架 |
| `frontend/src/styles/color-pool.css`、`utils/colorPool.ts` | 字段颜色池（唯一来源，冻结） |
| `frontend/src/views/*.vue` | 登录 / 发布 / 大厅 / 详情 / 个人中心 / 后台 6 个页面 |
| `frontend/vite.config.ts` | 端口 5173，`/api` 代理到 `127.0.0.1:8000` |
| `.gitignore` | 排除 `.env` / `.venv` / `node_modules` / `*.db` / `dist` |

## 问题

1. **Python 版本与预编译轮子**：环境为 Python 3.14，部分带 C/Rust 扩展的依赖存在 wheel 缺失风险。处置：`requirements.txt` 顶部写明版本策略与降级指引，安装脚本优先选 3.12 / 3.11（详见 `readme/码道应用总结.md` 案例一）。
2. **Windows 虚拟环境布局**：git-bash 下 `python` 可能解析到 MSYS2 解释器，生成 `bin/` 而非 `Scripts/`。处置：文档与脚本统一使用 `.venv/Scripts/python.exe`，并做两种布局的兼容探测（案例二）。
3. **对话与截图未归档**：本阶段在码道中的会话原文、Agent Team 任务面板截图仍待补，归档位置为 `prompts/agent_team_启动指令/` 与 `screenshots/`。