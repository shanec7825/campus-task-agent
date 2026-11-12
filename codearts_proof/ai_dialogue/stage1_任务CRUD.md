# 阶段 1 · 认证 + 任务 CRUD + 基础页面

> **归档口径**：本文件是「AI 交互对话整理版」（官方硬性要求 md 格式）。
> 当前状态：**结构已建立，对话原文尚未归档 —— 待该阶段收尾由哨兵整理**。
> 下方「产出」清单全部为本仓库中**真实存在**的文件；「输入 Prompt」只摘录《校园任务协同AI-Agent-开发方案》第 12 章已有的指令要点，**不臆造任何对话内容**。

## 阶段

阶段 1：打通「登录 → 发布 → 认领 → 进度 → 提交 → 验收 → 积分/通知」的后端闭环，并把基础页面接上真实接口。

- 完成标准：`teacher01` 可发布 / 指派 / 验收；`student01` 可认领 / 更新进度 / 提交；验收通过后 `student01` 积分增加且收到通知。
- 契约依据：`C-AUTH@1`、`C-TASKS@1`、`C-NOTIFY@1`、`C-FEAPI@1`。

## 使用的 Agent

| Agent | 模型 | 本阶段职责 |
|---|---|---|
| 领航员（Leader） | GLM-5.3-Flash | 拆分后端流转与前端页面两条线，冻结错误码与状态机，验收全链路 |
| 构造师 | **DeepSeek-V4.1-Flash-1017** | 认证（首登自动建号、内存 token）、任务 CRUD 与状态机、通知写入、积分流水、回归脚本 |
| 画师 | **DeepSeek-V4.1-Flash-1017** | 登录页、任务大厅、任务详情、个人中心、发布者后台；API 封装层与 Pinia 会话状态 |
| 哨兵 | **DeepSeek-V4.1-Flash-1017** | 鉴权覆盖率检查（除 `/api/health` 外全部 `Depends(get_current_user)`）、状态机字段一致性、积分对账 |

## 输入 Prompt

- 下发方式：接阶段 0 的连续会话，向 Leader 下发阶段 1 指令（**原文待归档**）。
- 要点（摘自《开发方案》第 12 章阶段 1）：
  1. 后端按方案第 4 章契约实现 `POST /api/auth/login`、`GET/POST /api/tasks`、`GET/PATCH /api/tasks/{id}`、`/claim` `/assign` `/progress` `/submit` `/verify`，统一 `{code,msg,data}`；
  2. `verify` 通过时写 `credit_logs` 并更新 `users.credits`，同时给双方写通知；
  3. 画师实现任务大厅（卡片 + 状态标签 + 认领）、任务详情（子任务树 / SOP / 进度 / 提交）、个人中心、发布者后台（指派 / 验收 / 催办规则）；
  4. 登录后携带 token（`Authorization` 头），后端提供 token 校验依赖；
  5. 所有列表空态需有插画文案；
  6. 验收：`teacher01` 全流程可走通，`student01` 积分增加并收到通知记录。
- **对话原文：待该阶段收尾由哨兵整理（占位，禁止编造）。**

## 产出

| 文件 | 说明 |
|---|---|
| `backend/app/routers/auth.py` | 登录（首登自动建号、展示名映射、角色前缀规则）、`/api/auth/me` |
| `backend/app/routers/tasks.py` | 任务 CRUD、列表过滤、详情、claim / assign / progress / submit / verify |
| `backend/app/routers/checkin.py` | 签到（每任务每人一次，成功后通知发布者） |
| `backend/app/routers/credits.py` | 积分查询与流水 |
| `backend/app/routers/notifications.py` | 通知列表、未读数、标记已读 |
| `backend/app/services/credit.py` | 积分增减与 `credit_logs` 记账（唯一入口） |
| `backend/app/services/notify_service.py` | 通知创建唯一入口（不直接写表） |
| `backend/scripts/smoke_core.sh` | 核心 REST 全流程回归，含 4001 / 4010 / 4020 / 4030 / 4040 / 4090 错误码用例 |
| `frontend/src/api/{client,auth,tasks,checkin,credits,notifications}.ts` | 统一 fetch 封装（含 token 注入与错误码处理） |
| `frontend/src/stores/{user,notifications}.ts` | 会话恢复、未读红点状态 |
| `frontend/src/views/LoginPage.vue` | 用户名登录（无密码） |
| `frontend/src/views/TaskHall.vue` | 任务列表、状态筛选、认领 |
| `frontend/src/views/TaskDetail.vue` | 任务信息、子任务与依赖、SOP、进度更新、提交 |
| `frontend/src/views/Profile.vue` | 我的任务、积分流水、签到记录、通知中心 |
| `frontend/src/views/AdminConsole.vue` | 发布者后台：指派、验收、催办设置、进度总览 |
| `frontend/src/router/index.ts`、`layouts/AppLayout.vue` | 登录守卫与顶部导航（未读红点占位） |

## 问题

1. **状态机边界**：`submit` / `verify` 的非法前置状态必须返回业务错误码而不是 500；处置方式为在 service 层集中校验并抛出 `ApiError`，由统一异常处理器转换为 HTTP 200 + `code != 0`。
2. **积分与通知的写入职责**：为避免多处直写 `credit_logs` / `notifications` 造成对账不一致，收敛为 `credit.adjust_credits` 与 `notify_service.create_notification` 两个唯一入口，哨兵静态核查调用点。
3. **前端不得绕过 api 层**：约束 `views/`、`components/` 中不出现 `fetch('/api`，全部经由 `src/api/*.ts`。
4. **对话与截图未归档**：本阶段会话原文、任务面板截图待补，位置为 `prompts/agent_team_启动指令/`、`debug/`、`screenshots/`。