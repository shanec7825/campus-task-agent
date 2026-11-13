# 阶段 15 · 信息架构与活动详情

> 日期：2026-11-13 ｜ 分支：`main` ｜ 提交：**无（工作区未提交）** ｜ 远程：未推送
> 计划：`.codeartsdoer/plans/phase1-ia-activity/design.md`、`task.md`（按 `.gitignore` 本地忽略）
> 验证入口：`npx vue-tsc --noEmit`、`python tests/frontend/check_contracts.py`、`python -m pytest tests/backend/test_activity_hierarchy.py -q`、`T10_DB_PATH=outputs/phase1-ia/demo.db python tests/backend/verify_tables.py`、`npm run build`
> 范围：用户需求的阶段 0（勘察结论）与阶段 1（导航、事务列表、任务卡片、活动详情的视觉增量），并引入支撑活动详情的最小活动模型。未发布、未部署。
> 编号说明：本轮留痕编号经裁定为「阶段 15」——`LOG.md` 此前已使用 2026-11-12「阶段 12 · 第一阶段可靠性改进」及阶段 13、14，为避免重号改用阶段 15；历史行未修改。

---

## 1 目标与需求来源

### 1.1 用户需求来源

- **阶段 0（勘察结论）**：先确认现有技术栈与可复用边界——Vue 3 + TypeScript + Pinia + Element Plus、FastAPI + SQLAlchemy + SQLite；不更换技术栈与模型供应商。
- **阶段 1（视觉与信息架构增量）**：导航、事务列表、任务卡片、活动详情的视觉增量，并引入支撑活动详情的**最小活动模型**，作为阶段 3 的增量基础。
- 本轮需求收敛为 R1~R7（`design.md §1.1`）：
  - **R1 导航与信息架构**：桌面紧凑侧栏 + 顶部组织上下文；手机顶部标题 + 至多四项底部导航（工作台 / 事务 / 消息 / 我的）；首个视口唯一「发布」主入口；保留 `/tasks`、`/tasks/:id`、`/publish`、`/profile`、`/admin` 深链。
  - **R2 工作台**：按当前用户真实待办呈现待审批 / 待验收 / 我的事项 / 临近截止分区，用一行文字摘要替代重复数字卡。
  - **R3 事务列表**：活动与独立任务两个分区；大厅不渲染子任务；状态 / 范围 / 类型筛选，手机折叠为单个「筛选」抽屉；加载中不渲染空状态。
  - **R4 任务卡片**：标题（≤2 行）、截止时间与唯一主操作视觉主导；发布者见「管理」且不出现「自己发布的任务不可报名」警告；成员见「更新进度」。
  - **R5 活动详情与层级阅读**：标题 → 负责人 / 截止 → 整体进度（含「下层工作已完成，待负责人确认」）→ 主任务树 → 操作；首层任务默认展开、子任务可折叠；缩进不超过一层且不横向滚动。
  - **R6 页面可被浏览器 Chatbot 直接阅读**：语义元素与真实 DOM 文本；不以颜色 / hover / 图片单独承载负责人、截止与状态；稳定深链；加载态 `aria-busy`；展开控件为原生 `button` + `aria-expanded`。
  - **R7 活动最小模型与数据兼容**：`activities` 表持久化 id、title、description、location、start_time、deadline、owner_id、org、status、created_at；新增可空 `tasks.activity_id`；子任务继承父任务活动；第三层 / 环 / 跨活动父子链以 **4001** 拒绝且数据不变；迁移只加列 / 表 / 索引且可重跑。

### 1.2 本轮明确不含

阶段 2（正式认证、会话、邀请、组织角色与跨组织权限、副本迁移验证）、阶段 3（完整任务 / 子任务状态机与验收规则）、阶段 4（原生语音 `SpeechAdapter` 与 Android/iOS 桥接、其余页面响应式）、阶段 5（完整回归与比赛材料）**不在本轮实现范围**。

---

## 2 决策与边界（Open decisions 已裁定）

| 编号 | 决策 | 影响 |
|---|---|---|
| D1 | **认证沿用演示 token**：`deps.py` 进程内 `TOKENS` 与前端 `localStorage` 未改 | 本轮页面在交付说明中标注「阶段 1，非正式认证」，不得声明登录 / 权限需求完成 |
| D2 | **活动可见范围不做组织过滤**：`Activity.org` 列已建但不参与查询 | 跨组织越权测试属阶段 2 |
| D3 | **发布页不接入活动创建**：活动只能经 `POST /api/activities` 或演示脚本在隔离库创建 | 发布页与 AI 解析链路本轮不改 |
| D4 | **不新增运行时依赖**：无图标库、无 Capacitor、无原生插件 | 导航使用文字标签，避免混用图标体系 |
| D5 | **不建数据库级外键**，存在性由应用层校验（与全库口径一致） | 迁移只加列 / 表 / 索引，保持可重跑 |
| D6 | **进度口径唯一**：活动进度 = 已验证的一层任务 / 全部一层任务（排除 cancelled）；绝不把「所有子任务已验证」等同于活动或父任务已验证 | 由 `activity_service.py` 唯一实现，路由与前端只读 |
| D7 | **截图口径**：桌面 1440×900 与手机 390×844，来自本机后端同源托管 `frontend/dist`；手机为浏览器模拟，不得当作真机结论 | 证据记录见 `outputs/phase1-ia/walkthrough.md` |

---

## 3 工具、角色与派工

### 3.1 工具与模型

| 项 | 实际值 |
|---|---|
| 平台 | 华为云 CodeArts 代码智能体 |
| 实际编排 | team-leader |
| 执行 Agent | coding-engineer（6 个并行实现任务）、developer-test-generator（行为测试）、team-code-reviewer（两轮独立只读审查） |
| 底层模型标识 | 平台显示 `deepseek-v4.1-flash-1017`，**未独立核验** |
| 运行环境 | Windows 11 + git-bash；Node 25.2.1 / npm 11.6.2；Python 3.12.10 |
| 数据 | 隔离库 `outputs/phase1-ia/demo.db`（未触碰既有业务数据） |

### 3.2 派工要点（按 `task.md` T1~T8）

| 任务 | 执行 | 核心要求 | 契约 |
|---|---|---|---|
| T1 | coding-engineer | 新增 `activities` 表与可空 `tasks.activity_id`；层级校验与进度聚合的唯一实现；`init_db()` 可重跑补列与 `ix_tasks_activity_id`；`verify_tables` 表清单 10 → 11 | `C-DATA-ACTIVITY@1`、`C-HIERARCHY@1`、`C-MIGRATION-2@1` |
| T2 | coding-engineer | 三个登录后活动端点，统一 `{code,msg,data}`，挂载 `routers.activities` | `C-ACTIVITY-API@1` |
| T3 | coding-engineer | 任务载荷输出 `activity_id` / 批量解析 `activity_title`；创建与修改走 `resolve_task_placement`；子任务继承父活动 | `C-TASK-FIELDS@1` |
| T4 | coding-engineer | 前端活动类型镜像与唯一 `api/activities.ts` 入口 | `C-FE-API@1` |
| T5 | coding-engineer | 桌面侧栏、1024px 顶部导航、≤768px 顶部标题 + 四项底部导航、组织上下文、唯一发布主入口；令牌与字号基线 | `C-ROUTE-NAV@1`、`C-TOKENS@2` |
| T6 | coding-engineer | 工作台分区与消息页（未读计数、单条 / 全部已读） | `C-WORKBENCH@1`、`C-SEMANTIC@1` |
| T7 | coding-engineer | 事务列表活动 / 独立任务分区、筛选抽屉、加载态不显空状态；卡片主操作优先级与两行标题 | `C-CARD@2` |
| T8 | coding-engineer | 活动详情摘要、`<dl>`、进度与待确认提示、任务树、展开全部；任务详情面包屑 | `C-SEMANTIC@1` |
| 行为测试 | developer-test-generator | 隔离库断言层级 / 跨活动 / 进度口径 | `C-HIERARCHY@1`、`C-DATA-ACTIVITY@1` |
| 审查 | team-code-reviewer | 只读两轮：契约一致性、越界改动、语义与可达性 | 全部 |

派工约束：每个 coder 只读自己的 `task.md` 条目与对应契约 ID，写集合隔离，不读取同伴实现文件；不运行构建 / 测试（由验证阶段执行）。

---

## 4 产出

### 4.1 修改 / 新增文件（`git status` 实测，工作区未提交）

**后端**

- 新增 `backend/app/routers/activities.py`、`backend/app/services/activity_service.py`
- 修改 `backend/app/models.py`、`backend/app/schemas.py`、`backend/app/db.py`、`backend/app/main.py`、`backend/app/routers/tasks.py`
- 修改 `tests/backend/verify_tables.py`（期望表清单 10 → 11）
- 新增 `tests/backend/test_activity_hierarchy.py`、`scripts/seed_phase1_demo.py`

**前端**

- 新增 `frontend/src/api/activities.ts`、`frontend/src/views/Workbench.vue`、`frontend/src/views/ActivityDetail.vue`、`frontend/src/views/Messages.vue`、`frontend/src/components/task/ActivityTaskTree.vue`
- 修改 `frontend/src/types/models.ts`、`frontend/src/router/index.ts`、`frontend/src/App.vue`、`frontend/src/layouts/AppLayout.vue`、`frontend/src/views/TaskHall.vue`、`frontend/src/views/TaskDetail.vue`、`frontend/src/components/task/TaskCard.vue`、`frontend/src/styles/theme.css`、`frontend/src/styles/typography.css`

**文档与留痕**

- 修改 `README.md`、`readme/README.md`
- 新增 `codearts_proof/ai_dialogue/stage15_信息架构与活动详情.md`；修改 `codearts_proof/LOG.md`、`codearts_proof/prompts/prompt迭代记录.md`（P-015）
- 本地证据 `outputs/phase1-ia/*`（`/outputs/` 被 `.gitignore` 忽略，见 `walkthrough.md`）

### 4.2 自动化验证（真实命令与结果）

```text
$ npx vue-tsc --noEmit                       # frontend
exit 0

$ python tests/frontend/check_contracts.py
25 passed, 0 failed

$ python -m pytest tests/backend/test_activity_hierarchy.py -q
11 passed

$ T10_DB_PATH=outputs/phase1-ia/demo.db python tests/backend/verify_tables.py
数据库 11 张表 / 列 / 唯一约束全部 PASS
（末尾 HTTP 健康检查 FAIL：脚本固定探测 8021，本轮服务在 8000；非数据库断言失败）

$ npm run build
成功
```

### 4.3 浏览器验证（模拟视口）

- 工具：Playwright MCP；登录账号 `teacher01`；视口 1440×900（桌面）与 390×844（手机模拟）。
- 实测页面：工作台、事务列表、活动详情、任务详情。
- 活动详情读取：`h1Count=1`，`h1` 为「2026 迎新志愿活动」；负责人「王老师」；截止「2026-11-22 18:00」；组织「计算机学院团委」；状态「进行中」；进度「0% · 0/3 个任务已完成」；三个主任务链接 `/tasks/1`、`/tasks/4`、`/tasks/7`；展开按钮 `aria-expanded=false`。
- 任务详情读取：`h1` 为「任务详情」，面包屑「2026 迎新志愿活动 / 场地准备」，任务标题「场地准备」。
- 截图与逐项读数见 `outputs/phase1-ia/walkthrough.md`。

---

## 5 真实问题与修复

| 编号 | 现象 | 原因 | 解决 | 证据 |
|---|---|---|---|---|
| Q1 | 首次 `npx vue-tsc --noEmit` 失败 | `TaskDetail.vue` 本地构造的 `TaskBrief` 缺 `activity_id`，与新增前端类型不一致 | 补 `activity_id` 字段 | 修复后 exit 0 |
| Q2 | 首轮独立审查 **3 严重** | ① `patch_task` 可造第三层或跨活动不一致；② 桌面同屏出现两个「发布」按钮；③ 5 个页面 `<main>` 嵌套 | 先修订 `design.md §2.2` 明确唯一校验入口与唯一主入口，再由原 coder 修复 | 复审进入第二轮；构建与契约检查通过 |
| Q3 | 首轮审查 **6 一般** | 契约细节与语义 / 可达性一致性问题 | 按审查清单逐项修复 | 同 Q2 |
| Q4 | `TaskHall` 加载中副标题显示「共 0 个活动 · 0 个独立任务」 | 加载态误用空数据摘要，与「加载中不渲染空状态」契约冲突 | 改为「正在加载事务…」 | 浏览器复验 |
| Q5 | `AppLayout` 手机标题与内容标题构成两个 `<h1>` | 顶部标题使用 `<h1>`，内容区同页也有 `<h1>` | 标题改 `<span>`，保证页面 `h1` 唯一 | 活动详情实测 `h1Count=1` |
| Q6 | 沙箱后台启动 uvicorn 首次 socketpair 受限 | 沙箱进程能力限制 | 采用固定端口 socketpair 的 `outputs/phase1-ia/serve_backend.py`；上一轮 8000 旧服务已停止并由本阶段服务接管 | 服务 8000 可访问，浏览器走查完成 |
| Q7 | 第三轮审查发现显式 `activity_id: null` 仍可让有子任务的任务脱离活动 | 活动归属比较未把「显式空值」与「目标为空」纳入同一判据，空值绕过跨活动 / 层级校验 | 条件改为 `int(activity_id or 0) != int(task.activity_id or 0)`，目标为空同样拒绝 | 第三轮仅查新增差异时发现并修复 |
| Q8 | 空活动漂移缺少回归覆盖 | 既有 11 条用例未覆盖显式 `activity_id: null` 场景 | 新增 2 条 drift 回归用例 | `python -m pytest tests/backend/test_activity_hierarchy.py -k "drift or 漂移" -q` → **2 passed, 11 deselected**（未重跑全量） |
| Q9 | 详情页标题层级仍不唯一 | `AppLayout` 手机标题使用 `<h1>`，与内容区 `<h1>` 重复；`TaskDetail` 任务标题原为 `<h2>`，字号未接入页面标题令牌 | 手机标题改为 `<span>`；`TaskDetail` 任务标题由 `<h2>` 改为 `<h1>`，字号改用 `--app-font-page-title` | 活动详情实测 `h1Count=1` |
| Q10 | `TaskHall` 加载中曾显示「共 0 个活动 · 0 个独立任务」 | 加载态误用空数据摘要 | 改为「正在加载事务…」，并加 `aria-live` 宣告 | 浏览器复验加载态 |

---

## 6 状态与未完成项

### 6.1 本轮可声称的状态

- **实现中 → 实现完成**（代码已写入工作区）。
- **自动测试通过**：`vue-tsc` exit 0、静态契约 25/0、`test_activity_hierarchy.py` 11 passed、数据库 11 表断言 PASS、`npm run build` 成功（`verify_tables` 末尾 HTTP 项 FAIL 已说明端口口径）。
- **浏览器（模拟视口）验证**：1440×900 与 390×844 实测工作台、事务列表、活动详情、任务详情。
- **未提交、未推送、未部署**；**真机验证未做**；**CI 未运行 / 未查询**。

### 6.2 明确未完成

1. 正式注册登录与会话、邀请、组织角色与跨组织权限、副本迁移验证（阶段 2）。
2. 完整任务 / 子任务状态机与验收规则（阶段 3）。
3. 发布页接入活动创建（本轮活动仅 API / 演示脚本创建）。
4. 其余页面响应式改造（阶段 4）。
5. 语音 `SpeechAdapter` 与 Android/iOS 原生桥接；真机验证；iOS 构建（阶段 4 / 阶段 5）。
6. GitHub Actions / CI 结果未运行、未查询，不宣称通过。
7. 截图与 `walkthrough.md` 位于 `outputs/phase1-ia/`，被 `.gitignore` 的 `/outputs/` 忽略，仅本地证据，不作为唯一比赛材料。
### 6.3 未验证范围（补充）

- `/profile` 截图在浏览器工具 **5s 超时**下未成功；已删除误生成的同名文件，个人中心视觉未纳入本轮截图证据。