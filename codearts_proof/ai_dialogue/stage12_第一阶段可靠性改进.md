# 阶段 12 · 第一阶段可靠性改进

> 归档日期：2026-11-12
> 使用 Agent：领航员（DeepSeek-V4.1-Flash-1017）→ 构造师-数据契约 / 构造师-成员流转 / 构造师-AI时间 / 构造师-催办 / 画师-草稿时间 / 画师-成员界面 / 哨兵-回归测试；独立审查由审查官-独立复核（首轮）、审查官-复审（第二轮）、审查官-终审（第三轮）完成；书记官负责本文件与文档收口。
> 归档口径：只写本轮实际发生、可核验的代码位置、命令与数字。当前工作区在本次可靠性改进之后还包含活动/UI 等其他改动，本文件只统计 Phase 1 可靠性变更集。
> 基线行号说明：仓库 git 历史从导入快照 `1c45b7d` 开始，该快照已包含本轮修复后的代码，无法从 git 还原修复前版本的精确行号；第 2 节因此以“修复前函数/文件定位 + 修复后当前行号”记录，未编造基线行号。

## 1 用户反馈

### 1.1 用户原始诉求（保留原话细节）

用户要求“直接分析并修复当前校园任务协同项目，完成第一阶段的可靠性改进”，并列出四条重点线索：

1. `frontend/src/stores/draft.ts` 中，“AI 草稿发布可能只将 time 写入 start_time，没有写入催办需要的 deadline。”
2. “多人报名通过后，任务进度、提交和验收可能仍共用一套任务状态，无法区分每名成员的完成情况。”
3. `backend/app/services/reminder_scheduler.py` “可能只向首位成员提醒，并只对首位成员执行逾期扣分。”
4. “任务进入 overdue 后，状态机可能只允许取消，无法延期或补交。”

时间字段的具体要求：

- “在本次范围内明确区分‘任务开始时间’和‘提交截止时间’，不要把二者默认为同一个时间。”
- “用户明确说‘周五下午三点开始，周六晚上八点前提交’时，两种时间应分别保存。”
- “用户只给出开始时间时，不自动编造截止时间；用户只给出截止时间时，不错误写成开始时间。”
- “缺少合法截止时间时，不触发基于截止时间的催办和逾期扣分。”

逐人执行与催办的具体要求：

- “区分‘任务整体状态’和‘每名已通过成员的执行状态’。”
- “一名成员提交或通过验收，不能让其他未完成成员被视为已完成。”
- “已提交待验收、已验收通过的成员，不应继续收到要求提交的催办。”
- “已拒绝、已撤回及其他非有效成员，不收到执行催办或被扣分。”
- “提前提醒、临近截止提醒和逾期提醒，均按成员去重。”

逾期处理的具体要求：

- “逾期不能成为只能取消、无法继续执行的死路。”
- “发布者修改截止时间；未完成成员逾期后继续提交补交；发布者按现有权限取消任务。”
- “修改截止时间后，后续提醒应按新时间计算。”
- “调度重复运行、服务重启或截止时间修改，不能造成重复扣分。”
- “逾期扣分按实际未完成成员判断，不能只扣首位成员。”

范围与数据保护要求：

- “不要顺便重构无关模块，不增加活动岗位、排班、外部消息渠道、日历集成或新的 AI Agent。”
- “不提交、推送、部署，不操作真实用户数据。”
- “不删除现有数据库，不通过重建数据库掩盖迁移问题。”
- “对旧的单负责人任务、没有逐人成员状态的数据，提供明确的兼容或迁移策略。”
- “任何需要修改数据库的验证，使用隔离的测试数据库。”

验收要求：

- “为确认的问题增加‘修复前失败、修复后通过’的回归测试。”
- “代码完成后，调用独立 Review Agent，只读审查需求、diff 和验证证据。最多三轮。”
- “如果无法使用独立 Review Agent，明确报告，不把自查称为独立审查。”

### 1.2 复现环境

- 操作系统：Windows 11 Home China（win32 / git-bash）。
- 后端：Python 3.12.10，FastAPI + SQLAlchemy + SQLite；代码位于 `backend/`。
- 前端：Node 25.2.1、npm 11.6.2，Vue 3 + TypeScript + Element Plus；代码位于 `frontend/`。
- 测试隔离：所有涉及数据库的验证使用 `tempfile.mkdtemp()` 下的临时 SQLite 文件，通过 `DATABASE_PATH` 指定；未连接、未修改真实数据库。
- 基线现象（修复前）：
  - AI 草稿的 `toTaskPayload()` 只返回 `start_time`，没有 `deadline`；后端 `Draft` schema、AI prompt、mock 解析、diff/merge 同样只有 `time`。
  - 任务只有整体 `tasks.status`；“多人已通过”只体现在报名表，没有逐人执行状态，提交/验收会直接改任务整体状态。
  - `reminder_scheduler` 以单个 `assignee_id` 为主角，提醒和逾期扣分只落在一人。
  - `task_state` 的 `overdue` 出边只有 `cancelled`，无法提交、验收或改期恢复。

## 2 Leader 决策与根因定位

### 2.1 基线代码定位（修复前问题所在）

| 基线位置（文件 / 函数） | 修复前行为 | 修复后当前行号（供核对） |
|---|---|---|
| `frontend/src/stores/draft.ts::toTaskPayload()` | 只组装 `start_time: draft.time`，没有 `deadline` | `frontend/src/stores/draft.ts:1346-1360`（`deadline` 在 1359） |
| `frontend/src/stores/draft.ts::BASE_FIELD_KEYS` | 固定字段中没有 `deadline`，草稿恢复也没有该字段 | `frontend/src/stores/draft.ts:82-88`（`deadline` 在 85） |
| `backend/app/schemas.py::Draft` | 只有 `time`，没有 `deadline` | `backend/app/schemas.py:501-509`（`deadline` 在 508） |
| `backend/app/schemas.py::TaskOut` | 没有 `members` / `my_member_status`，前端只能看到任务整体状态 | `backend/app/schemas.py:150-189`（派生字段在 188-189） |
| `backend/app/models.py` | 没有 `task_members` 表；只有报名表和 `tasks.assignee_id` | `backend/app/models.py:198`（`TaskMember`） |
| `backend/app/services/reminder_scheduler.py` | 以首位 `assignee_id` 取提醒对象；逾期扣分也只对首位 | `backend/app/services/reminder_scheduler.py:165-360`（`scan_and_remind` / `_handle_overdue` / `_handle_unassigned_task`） |
| `backend/app/services/task_state.py::ALLOWED_TRANSITIONS` | `overdue` 只能迁到 `cancelled` | `backend/app/services/task_state.py:19`（当前为 `claimed|in_progress|submitted|verified|cancelled`） |
| `backend/app/routers/tasks.py::verify_task()` | 验收改任务整体状态，无法指定成员 | `backend/app/routers/tasks.py:860-902`（成员级验收、自验收拦截、零奖励保留） |
| `backend/app/db.py::init_db()` | 无逐人成员表/通知去重列/legacy 回填 | `backend/app/db.py:68-146`（增量迁移） |

> 说明：上表“修复后当前行号”是 2026-11-12 代码状态；后续活动/UI 迭代可能使行号漂移，但函数名与路径仍可作为核对入口。

### 2.2 真实技术根因

1. **时间字段断链，不是手动表单缺控件**
   - `ManualForm.vue` 已有独立的 `start_time`、`deadline` 两个日期控件；缺口在 AI 草稿链路：`Draft` schema、`prompts.py`、`mock_fixtures.py`、`diffing.py`、`draft.ts` 都没有 `deadline`。
   - `draft.ts` 的 `toTaskPayload()` 只把 `draft.time` 写进 `start_time`，因此即使 AI 解析出两个时间，发布请求也只带一个。
   - 数据库 `tasks.deadline` 列本身已存在，不是缺列问题。

2. **单任务状态承载多人执行，缺少逐人事实表**
   - 原模型只有 `tasks.status` + 单个 `assignee_id`；`task_applications` 只记录报名审批，不记录执行进度、提交、退回、验收。
   - 因此“一个人提交”只能改任务整体状态，无法表达“A 待验收、B 进行中、C 未开始”。
   - 验收接口只能按任务整体判定，退回会覆盖其他人的结果，积分也无法按成员幂等结算。

3. **催办和逾期扣分绑定单负责人**
   - `reminder_scheduler` 只取 `assignee_id` 作为提醒对象，并只对该用户写逾期扣分流水；多名额审批上线后，其他 approved 成员成为盲区。
   - 去重键只按任务/级别，未包含成员和截止时间版本，改期后无法合理产生新提醒。

4. **overdue 被写成终态**
   - `ALLOWED_TRANSITIONS["overdue"]` 只有 `cancelled`，提交/验收/改期都会被状态机拒绝，逾期成员没有补交路径。

5. **审查额外发现的权限/积分根因**
   - `decide_application` 通过分支没有任务状态守卫，终态任务仍能审批 pending 报名并新建成员行。
   - 创建、指派、PATCH 三个入口未拦截 `assignee_id == publisher_id`，发布者可自指派→自提交→自验收并拿积分。
   - 验收奖励使用 `task.credit_reward or DEFAULT`，把显式 `0` 当成未设置。

### 2.3 排除的无关猜测

- **不是“手动表单没有截止时间字段”**：`ManualForm.vue` 已有独立的 `start_time` / `deadline` 控件与 payload，问题只在 AI 草稿链路。
- **不是“数据库缺 `deadline` 列”**：`tasks.deadline` 原本已存在，缺的是草稿 schema、解析、前端 store 与发布 payload 的完整映射。
- **不是 SSE 通道故障**：通知仍经站内通知和 SSE 到达；真实问题是收件人选择、逐人去重和重复发送，不是推送链路不可用。
- **不是“只改前端即可”**：多人执行状态必须有后端持久化事实表，前端单改会继续用任务整体状态推断个人状态。

### 2.4 收敛后的任务项与决策

- **T1 数据模型、共享类型与幂等迁移**：新增 `TaskMember`、`Notification.dedupe_key`、`Draft.deadline`、`MemberOut`、`TaskOut.members/my_member_status`、`VerifyIn.user_id`；迁移只增列/索引/补行。
- **T2 逐人执行、聚合状态与成员级验收**：新增 `task_state.py`、`member_service.py`；提交/验收/退回只改目标成员；任务整体状态由成员状态聚合。
- **T3 后端开始/截止时间独立解析**：prompt 增加 `deadline`，mock 用“时间片段邻接截止语义词”归属，diff/merge/sanitize 支持 deadline。
- **T4 逐人催办、通知去重与逾期扣分**：按成员状态判断提醒；`submitted/verified` 跳过；逾期扣分按 `(task_id,user_id)` 幂等；去重键含截止时间版本。
- **T5 前端草稿与发布映射**：`BASE_FIELD_KEYS`、`buildDraft`、`writeDraftFields`、`toTaskPayload`、AiPanel 相似任务带入全部支持 deadline。
- **T6 前端成员视图**：TaskDetail 按 `my_member_status` 控制进度/提交并展示成员表；AdminConsole 支持成员级验收、改期、取消；Profile/TaskCard 展示个人状态。
- **T7 回归测试**：`tests/backend/test_reliability.py`，覆盖起止时间、三成员 A/B/C、重复提交/验收/调度/重启、逾期补交、迁移、越权。
- **T8 独立审查**：三轮只读审查；首轮 3 个 Important，修复后第二轮确认，第三轮终审 PASS。
- **业务决策（本轮已实现并写入契约）**：任务整体 `submitted` 表示“至少一名成员有待验收提交”，不代表全员完成；全部 approved 成员 `verified` 才整体 `verified`；不限人数任务在全体验收或发布者取消后结束；改期不自动退还历史逾期扣分；报名/审批仅限 `published/claimed`，进入执行后遗留 pending 只能拒绝或撤回。

## 3 派工 Prompt 要点与契约登记

| 任务 | 派工 Prompt 核心要求（1~3 句） | 契约 ID |
|---|---|---|
| T1 数据模型与迁移 | 读 `task.md` T1；按契约新增 `TaskMember`、`Notification.dedupe_key`、`Draft.deadline` 与共享类型；`init_db()` 只做幂等增量迁移，不删列不删行。 | `C-DATA-MEMBER@1`、`C-MIGRATION@1` |
| T2 成员执行与验收 | 读 `task.md` T2；实现成员级进度/提交/验收/退回与聚合状态；路由只持有一次业务 commit，验收积分幂等，禁止自验收。 | `C-MEMBER@1`、`C-TASK-API@1` |
| T3 后端时间解析 | 读 `task.md` T3；prompt 增加 `deadline` 字段并明确开始/截止互不复制；mock 按截止语义词归属，diff/merge/sanitize 同步支持。 | `C-TIME-AGENT@1` |
| T4 催办与通知 | 读 `task.md` T4；按 approved 成员状态逐人提醒，`submitted/verified` 跳过；逾期扣分按 `(task_id,user_id)` 一次；去重键含截止时间版本。 | `C-NOTIFY@1` |
| T5 前端草稿时间 | 读 `task.md` T5；把 `deadline` 加入固定字段、草稿构建/恢复、发布 payload、相似任务带入；手动表单保持独立起止控件。 | `C-TIME-FE@1` |
| T6 前端成员视图 | 读 `task.md` T6；TaskDetail 按个人状态开放进度/提交；AdminConsole 按成员验收、修改截止时间、取消；Profile/TaskCard 展示成员状态。 | `C-FE-MEMBER@1` |
| T7 回归测试 | 读 `task.md` T7；在隔离临时库覆盖起止时间、三成员 A/B/C、重复调度/重启、逾期补交、迁移与越权，使用真实断言而非占位。 | 消费 `C-DATA-MEMBER@1` / `C-MIGRATION@1` / `C-MEMBER@1` / `C-TASK-API@1` / `C-NOTIFY@1` / `C-TIME-AGENT@1` |
| T8 独立审查 | 只读审查需求、diff 与验证证据；首轮列阻断/非阻断，后续轮只复审新增修复；不修改文件。 | 无新增契约，核对上述契约 |

派工方式：Leader 先写 `.codeartsdoer/plans/phase1-reliability/design.md` 冻结 §2.2 契约，再写 `task.md` 的 T1~T8；T1~T6 在首轮同时派工，T7 在 T1~T4 完成后启动，T8 在全部实现与测试后启动。审查发现的问题交回原实现 Agent（T2/T4/T6/T7）修复，再由新审查 Agent 复审。

## 4 产出

### 4.1 本轮实际修改/新增文件

后端：

- `backend/app/models.py`
- `backend/app/schemas.py`
- `backend/app/db.py`
- `backend/app/services/task_state.py`（新增）
- `backend/app/services/member_service.py`（新增）
- `backend/app/services/reminder_scheduler.py`
- `backend/app/services/notify_service.py`
- `backend/app/services/application_service.py`
- `backend/app/routers/tasks.py`
- `backend/app/routers/applications.py`
- `backend/app/agents/prompts.py`
- `backend/app/agents/mock_fixtures.py`
- `backend/app/agents/diffing.py`
- `backend/app/agents/extractor.py`

前端：

- `frontend/src/types/models.ts`
- `frontend/src/stores/draft.ts`
- `frontend/src/utils/traceText.ts`
- `frontend/src/components/Publish/AiPanel.vue`
- `frontend/src/components/Publish/ManualForm.vue`
- `frontend/src/api/tasks.ts`
- `frontend/src/views/TaskDetail.vue`
- `frontend/src/views/AdminConsole.vue`
- `frontend/src/views/Profile.vue`
- `frontend/src/components/task/TaskCard.vue`

测试与计划：

- `tests/backend/test_reliability.py`（新增，11 个用例）
- `tests/backend/verify_tables.py`（10 张表校验）
- `.codeartsdoer/plans/phase1-reliability/design.md`（新增）
- `.codeartsdoer/plans/phase1-reliability/task.md`（新增）

留痕与文档（本次收口）：

- `codearts_proof/ai_dialogue/stage12_第一阶段可靠性改进.md`
- `codearts_proof/LOG.md`
- `codearts_proof/prompts/prompt迭代记录.md`
- `readme/README.md`
- `README.md`

> 当前工作区在 Phase 1 之后还包含活动/UI 等其他改动（如 `backend/app/routers/activities.py`、`frontend/src/views/ActivityDetail.vue`）。它们不属于本轮可靠性变更集，未在本文件第 4 节统计。

### 4.2 自动化测试原始结果

```text
PYTHONPATH=backend python -m pytest tests/backend/test_reliability.py -q
→ 11 passed in 4.58s
```

11 个用例名（真实存在）：

1. `test_start_and_deadline_are_independent`
2. `test_three_members_verify_reject_and_pending`
3. `test_reminder_skips_finished_members_and_is_idempotent`
4. `test_overdue_penalty_once_per_member`
5. `test_deadline_extension_reminds_on_new_deadline`
6. `test_overdue_late_submission_verify_and_cancel`
7. `test_legacy_database_migration_is_idempotent`
8. `test_terminal_approval_self_assign_and_zero_reward_guards`
9. `test_verified_task_rejects_pending_approval`
10. `test_historical_self_verification_is_rejected`
11. `test_cleared_deadline_stops_deadline_reminders`

既有后端脚本（临时库 + 独立后端进程，按顺序执行）原样输出：

```text
verify_tables.py          → 41 项断言通过（10 张表）
test_applications.py      → 413 项断言通过
test_api_e2e.py           → 257 项断言通过
test_agent_mock.py        → 229 项断言通过
test_agent_incremental.py → 358 项断言通过
test_sse_and_reminder.py  → 106 项断言通过
```

静态与构建：

```text
python -m compileall -q backend/app
→ exit 0

cd frontend && npm run typecheck
→ exit 0

cd frontend && npm run build
→ 构建成功；仅有 chunk > 500 kB 的体积提示，无编译错误
```

页面走查说明：本轮可靠性改进的验证范围为后端 pytest、既有后端脚本、前端 typecheck 与 build；**未进行真实浏览器页面走查**，因此本文件不填写截图、页面尺寸或人工走查数字。该未验证范围已如实保留，未用静态检查代替页面验证。

环境准备（本轮实际执行）：`python -m pip install -q -r backend/requirements.txt pytest httpx`；`npm install --no-package-lock --no-audit --no-fund`。

独立审查实际结果：

- 首轮：结论“无阻断项，可交付”，同时通过运行时探针复现 3 个 Important（终态审批、自指派、零奖励）。
- 第二轮：确认 I1~I3 已修复、无新阻断；补充发现历史自验收、legacy 计数、时区、截止时间清空等残余项。
- 第三轮：终审结论 **PASS（无阻塞项）**；审查者独立复跑 `pytest tests/backend/test_reliability.py -q` 得到 `11 passed in 4.58s`。
- 审查者未复跑：`npm run build`、`compileall`、需要外部起服务的既有脚本；这些由交付方实际执行，结果见上。该差异已如实记录，未把未复跑项写成审查者已验证。

## 5 真实问题与修复

### P1 无成员任务的发布者提醒被误删

- **现象**：`tests/backend/test_sse_and_reminder.py` 预期 warning 任务（published、无负责人、30 小时后截止）给发布者 1 条 warning；逐人催办改造后，`_handle_task` 在成员列表为空时直接 skip，导致该既有用例失败。
- **原因**：旧调度器用 `assignee_id` 作为提醒对象；改为成员列表后，没有为“published 且无人报名/审批”的任务保留发布者级兜底。
- **修复**：新增 `_handle_unassigned_task`，无 approved 成员时按截止时间给发布者 warning/urgent/overdue；去重键为 `unassigned:{task}:{publisher}:{level}:{deadline版本}`；无成员时绝不写积分流水。既有 4 条通知预期恢复。

### P2 overdue 通知文案与标题回归

- **现象**：`test_sse_and_reminder.py` 断言“overdue 通知共 2 条”“overdue 文案含‘已逾期’”“含负责人名称”，首次跑测失败；`smoke_sse.sh` 还要求两条 overdue 通知标题均为「任务已逾期」。
- **原因**：逐人改造后成员文案写成“已于 … 截止，你的任务尚未提交”，缺“已逾期”；发布者标题写成「成员任务已逾期」，与既有契约不一致。
- **修复**：成员与发布者 overdue 标题统一为「任务已逾期」；文案同时包含任务名、负责人姓名、截止时间和“已逾期”/“请尽快补交”或“请及时处理”；无成员 overdue 文案也补“任务已逾期”。

### P3 新增 `task_members` 导致建表校验失败

- **现象**：`verify_tables.py` 断言 `/api/health` 的表集合为 9 张，实际多出 `task_members`，首次执行失败。
- **原因**：Phase 1 按设计新增逐人成员表，既有校验的固定表集合未同步。
- **修复**：将 `verify_tables.py` 的期望表集合改为 10 张，加入 `task_members`；新增断言 `uq_task_members_task_user` 命名唯一索引；同时把 `health.tables` 数量断言从 9 改为 10。该修改是测试口径随新表的必要同步，不是放宽断言。

### P4 逾期状态被成员进度“拉回”造成抖动

- **现象**：任务已逾期、成员仍 `in_progress` 时，任一进度/提交后的 `sync_task_status` 会把任务改回 `in_progress` 或 `claimed`，即使截止时间仍在过去；下一轮调度又置回 `overdue`。
- **原因**：聚合函数只按成员状态计算目标状态，没有把“截止时间是否已过”纳入 overdue 的恢复判断。
- **修复**：`sync_task_status` 在 current == `overdue` 且目标为 `claimed/in_progress` 时，只有 `deadline` 可解析且晚于当前本地时间才允许恢复；截止时间缺失/非法/已过则保持 overdue；目标为 `submitted/verified` 仍允许迁出。这样既保留逾期标记，又允许改期恢复和逾期补交。

### P5 发布者“待验收”通知重复

- **现象**：成员提交后，提交路由已给发布者发 `submit:{task}:{user}:{submitted_at}` 通知；调度器又发一条 pending-verify 汇总，同一提交出现两条发布者通知。
- **原因**：职责重叠，调度器和提交路由都实现“有待验收提交”的提醒。
- **修复**：移除调度器的 `_notify_pending_verification` 及常量；发布者待验收通知由提交路由唯一负责；调度器只保留截止提醒、逾期提醒和逐成员扣分。既有 SSE/通知测试的条数预期不受影响。

### P6 取消任务后前端仍显示可操作按钮

- **现象**：后端取消任务后，成员进度/提交/验收返回 4090；TaskDetail 仍按成员状态显示“可更新进度/可提交”，AdminConsole 也仍可能打开验收入口。
- **原因**：前端只按 `my_member_status` 判断，没有叠加任务的 `cancelled` 终态。
- **修复**：`TaskDetail.vue` 的 `canProgress`/`canSubmit` 在 `status === 'cancelled'` 时返回 false，提示「任务已取消，无法继续操作」；`AdminConsole.vue` 的 `canVerify` 增加 `cancelled/verified` 排除；审批入口 `canAudit` 限定 `published/claimed`。后端仍保留最终权威校验。

### P7 首轮独立审查：终态审批、自指派、零奖励

- **现象**：审查用运行时探针复现：
  - 取消任务后仍可审批通过 pending 报名，code=0，并新建 `task_members` 行；
  - 发布者自指派后可自提交、自验收，`credit_delta=20`；
  - `credit_reward=0` 时实际发放默认 20。
- **原因**：
  - `decide_application` 通过分支只校验 pending 与名额，没有校验任务状态；
  - 创建、指派、PATCH 三个入口都没有 `assignee_id == publisher_id` 拦截；
  - 奖励计算使用 `task.credit_reward or DEFAULT`。
- **修复**：
  - 审批通过分支增加 `task.status ∈ ASSIGN_ALLOWED_STATUSES` 守卫（`published/claimed`），终态/执行中返回 4090；拒绝分支仍可清理 pending；
  - 创建（`create_task`）、指派（`assign_approved` / `assign_task`）、PATCH（`patch_task`）均返回 4030「不能指派自己」；
  - `verify_task` 增加自验收 4030 防御，覆盖历史脏数据；
  - 奖励改为 `task.credit_reward if task.credit_reward is not None else DEFAULT`；
  - 新增 `test_terminal_approval_self_assign_and_zero_reward_guards` 等用例。

### P8 第二轮审查残余：历史自验收、legacy 计数、时区、截止时间清空

- **现象**：
  - 历史库若 `assignee_id == publisher_id`，legacy 回填后发布者仍可能自我验收；
  - `status_counts_bulk` 与 `_approved_ids_by_task` 对“负责人已有 rejected/cancelled 报名行”的回退口径不一致；
  - 带时区 ISO 在调度器与成员聚合中换算不一致；
  - AdminConsole 文案说“留空不设置截止”，但 `saveDeadline` 空值直接拦截，无法清空。
- **修复**：
  - `verify_task` 在写库前对任一 target 等于发布者返回 4030「不能验收自己」；
  - `status_counts_bulk` 跳过“负责人已有任意报名行”的 legacy 回退，与 `_approved_ids_by_task` 的 `has_own_row` 对齐；
  - `reminder_scheduler._parse_deadline` 对带时区 ISO 使用 `astimezone().replace(tzinfo=None)`，与 `member_service._deadline_is_future` 一致；
  - `saveDeadline` 空值归一为 `null` 并 PATCH `{deadline: null}`，更新弹窗文案，允许清除截止时间；
  - 补测试：verified 终态审批、历史自验收 4030、清空截止时间后不催办、迁移 `decided_at/decided_by` 为 NULL。

### P9 已识别但本轮未修复的低优先级问题（如实保留）

- 拒回/提交通知去重键包含秒级 `submitted_at`；同一秒内退回后重提再拒回，存在键碰撞导致通知被去重抑制的边界，当前未加更细的序号字段。
- 通知去重查询按 `(user_id, task_id, dedupe_key)`，而数据库唯一索引只在 `dedupe_key`；现有键均内嵌 `user_id`，但未来新增不含 user 的键可能触发唯一冲突。该点保留为技术债。
- 任务进入 `in_progress/submitted/overdue` 后，遗留 pending 报名不能“通过”，只能拒绝或学生撤回；这是本阶段“报名/审批仅限 published/claimed”策略的直接结果，已在第 2.4 节记录，未擅自扩展执行中补审批。

> 以上 P9 是真实已知边界，不是占位；本轮未声称它们已修复。