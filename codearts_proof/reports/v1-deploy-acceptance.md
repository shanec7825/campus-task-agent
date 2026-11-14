# V1 部署验收报告（本机生产形态）

> 日期：2026-11-14。提交：`41fe2ac`（stage43）。执行者：team-leader。
> 证据原始输出：`work/deploy/smoke.json`（本地忽略，未提交）。

## 1. 部署形态

- **本机生产形态**：前端 `frontend/dist`（`npm run build`）由 FastAPI `app.main` 同源托管；uvicorn 单进程，动态空闲端口（避免与既有 8000/8010 遗留进程冲突）。
- 隔离运行：`DATABASE_PATH` 指向临时目录、`ORG_LIBRARY_UPLOAD_ROOT` 指向临时目录、`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、`AI_DAILY_QUOTA=50`。
- 演示账号来自 `scripts/seed_phase2_demo.py`（口令仅用于隔离演示库）。
- **未做远程部署**：用户未提供目标主机、域名或凭据；本报告只代表本机生产形态验收，不代表远程环境。

## 2. 执行命令与实际结果

```bash
cd frontend && npm run build        # ✓ built（仅既有 chunk 体积提示）
python scripts/deploy_smoke.py      # EXIT=0，14/14
```

| 断言 | 结果 |
|---|---|
| `/api/health` code=0 / status=ok | PASS |
| `health.tables` = 26（含 `org_resources`、`library_refs`） | PASS |
| `health.mock = true` | PASS |
| 静态首页 `/` 200 且含 `<div id="app">` | PASS（1114 bytes） |
| 静态资源 `/assets/ActivityDetail-*.js` 200 | PASS（12937 bytes） |
| 未登录 `GET /api/tasks` | PASS（HTTP 401 / code 4010） |
| `orgadmin` 登录 | PASS |
| 登录后任务列表 | PASS（1 条） |
| `GET /api/library/refs` | PASS（`items=[]`, `revoked_count=0`） |
| `POST /api/ai/task-draft`（mock） | PASS（3 个任务，`mock=true`） |
| `POST /api/org-resources` 上传 Markdown | PASS（`text_status=ready`、`allow_student_ai=0`） |
| 成员 `GET /api/org-resources` | PASS（HTTP 403 / 4030） |
| 成员引用未开放资料 | PASS（HTTP 404 / 4040） |
| 服务进程存活 | PASS |

- 脚本结束时自动停止 uvicorn 并删除临时库、资料目录；未触碰 `backend/campus.db` 与 `backend/uploads`。

## 3. 覆盖到的 V1 关键路径

- 认证与同源静态托管（生产形态可打开前端）。
- 组织资料上传、解析 ready、默认不允许学生 AI 检索。
- 学生越权访问组织资料被拒、未开放资料不可被引用。
- AI 任务树草案在 mock 下可生成（只读，不写库）。
- 新增表（`org_resources`、`library_refs`）已在新建库中建立。

## 4. 未验证范围

- 远程主机/容器部署、HTTPS、反向代理、持久化对象存储：**未做**（无目标与凭据）。
- 真实模型（`MAAS_MOCK=1`）：未调用外部供应商。
- 浏览器手工交互（草案填充、归档入口、预审正文展示）、移动端真机、深色主题：未做。
- 并发与长稳：未做压测。

## 5. 回滚方式

- 本机验收：停止 `uvicorn`（脚本已自动停止），删除临时目录即可，无持久副作用。
- 代码：`git revert 41fe2ac`（以及其回填提交），不影响既有发布/验收链路。
- 数据库：本机验收使用临时库；正式环境如需回退，保留新增表不删除，仅回退代码引用。