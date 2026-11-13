# stage23 主动协作与额度（AIW-05）

> 日期：2026-11-14。状态（截至本记录）：实现完成；新增 `test_aiw05_proactive_quota.py` **12 passed**；前端构建 **4/4**、契约 **25/25**、语音 **21/21**、`vue-tsc` **EXIT=0**；后端 `run_all` **EXIT=0**（23 表、verify_tables 58 项）；独立审查三轮 **0 Critical / 10 → 2 → 1 Important**，第三轮最后修复按上限未再开第四轮；浏览器实测通知失效、AI 额度、后台改期影响卡；安全红线本地 **12 通过 / 1 失败（B5b）**；真实模型、真机、移动视口、零额度 UI 未验证。**已提交并推送 `e35836d`，CI run 43513010046 四个 job 全部 success；未部署。**

## 1. 需求来源与授权

- 来源：用户本轮「每小时触发一次的阶段开发任务」指令（原文归档 `codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage23_主动协作与额度_启动指令.md`）；本地总计划 `ai-workbench/roadmap.md` 的 AIW-05「主动协作与额度」。
- 授权：AIW-00 至 AIW-06 已确认范围内的阶段开发、必要修复、测试、独立审查与记录；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 非目标：不做 AI 生成的改期/指派动作提案，不新增 AI 写操作执行端点；不做收费、支付、套餐、供应商结算；不做多级审批、最终自动验收、文件上传、正文解析或向量检索。

## 2. 开工基线

- 分支 `main`；开工 HEAD `f09084d842bccc28846fa993a34da923a6af51e5`（stage22 文档回填）。
- `git status --porcelain` 为空；无 `.git/index.lock`；未发现其他会话或子任务写入者。
- AIW-04 对应 CI 实查：业务提交 `a3632cebde608ff877cd1310a287337baa93939f` → run 43505516305 `completed / success`，4 个 job 全部 success；因此 AIW-04 已验收，本次进入 AIW-05。
- 开工快照：`outputs/aiw05/opening-head.txt`、`opening-git-status.txt`、`opening-diff.patch`（本地忽略）。
- 本地新增计划 `aiw05-proactive-quota/{design,task}.md`（Git 忽略，不提交）。

## 3. 决策与范围

- `notifications` 新增 `stale`：改期/取消后旧提醒置 1，历史保留但不计未读；只作用于 `remind:` / `overdue:` / `overdue_pub:` / `unassigned:` 前缀。
- `PATCH /api/tasks/{id}` 仅在截止时间归一化版本真实变化、或任务真实取消时失效旧提醒并写变更通知；通知去重键包含任务、旧值、新值、接收人。
- 新增只读 `GET /api/tasks/{id}/change-impact`：返回成员、调用者可见的下游任务（只暴露 `id/title/status`）、提醒是否重置与通知接收人；不写库、不发通知。
- 新增 `ai_usage_ledger`（表 22 → 23）：成功回答写 `settled` 记录；`request_id` 唯一约束提供幂等；失败不写、不扣额度。
- 每日额度 `AI_DAILY_QUOTA`（默认 50，0 表示当天不生成）；额度只限制 `/api/agent/chat`，通知、任务、报名、审批、验收照常可用。写账本前二次检查只缩小竞态窗口，是次数软上限，不是 SQLite 并发硬上限。
- 受控操作卡本轮落为**人工改期确认卡**：后台改期前展示当前→拟调整、提醒重置、成员、下游任务与通知接收人；确认后才调用既有 PATCH，由后端再次鉴权。AI 仍不直接写业务表。
- 错误码新增 `4290` 表示 AI 额度用尽；沿用 `4001/4030/4040/4090`。

## 4. 实际变更

后端：

- `backend/app/models.py`：`Notification.stale`；`AiUsageLedger`（唯一约束 `uq_ai_usage_user_request`，索引 `ix_ai_usage_user_created`），表数 23。
- `backend/app/db.py`：幂等补 `notifications.stale` 列；建表注释同步。
- `backend/app/services/notify_service.py`：`deadline_version`、`stale_task_reminders`、`notify_task_changed`；变更通知 key 纳入接收人 ID。
- `backend/app/services/reminder_scheduler.py`：每轮按当前截止时间版本清理旧提醒。
- `backend/app/services/ai_service.py`：额度统计、`request_id` 幂等重放、账本写入、`4290`、二次额度检查、`get_usage`。
- `backend/app/routers/tasks.py`：`GET /{id}/change-impact`；PATCH 改期/取消副作用、截止时间校验、归一化比较、下游可见性过滤、变更结果。
- `backend/app/routers/notifications.py`：`stale` 未读口径；失效项不可标记已读。
- `backend/app/routers/agent.py`：`GET /api/agent/usage`；chat 透传 `request_id`。
- `backend/app/schemas.py`：通知 `stale`、AI 额度 DTO、`request_id`/`replayed`、改期影响 DTO。

前端：

- `frontend/src/types/models.ts`、`api/agent.ts`、`api/tasks.ts`：额度、通知 stale、改期影响与变更结果类型。
- `frontend/src/stores/aiChat.ts`：额度状态、按日期刷新、失败重试复用 `request_id`、4290 后刷新/置零。
- `frontend/src/stores/notifications.ts`：未读排除 stale；推送与本地已读同步排除。
- `frontend/src/views/AiConsole.vue`：额度条、零额度提示、发送禁用。
- `frontend/src/components/ai/AgentDock.vue`：挂载预加载额度、零额度发送拦截与禁用。
- `frontend/src/views/Profile.vue`：AI 用量区块、失效提醒标签与未读口径。
- `frontend/src/views/AdminConsole.vue`：改期影响预览、请求序号防竞态、关闭/保存失效在途响应。

测试与门禁：

- 新增 `tests/backend/test_aiw05_proactive_quota.py`（12 用例）：改期/取消 stale、变更通知、影响预览权限与下游过滤、等价格式/空串/非法时间、逾期前缀、问答题账本/重放/二次额度/真实模型成功/失败/零额度/跨账号。
- `tests/backend/verify_tables.py`：23 表、58 项断言（含 `stale NOT NULL DEFAULT 0`）。
- `.github/workflows/ci.yml`、`docs/CI.md`：接入新套件并设置 `AI_DAILY_QUOTA=50`。
- `README.md`、`readme/README.md`：同步功能与配置说明。

## 5. 真实问题与处置

| 编号 | 现象 | 根因与处置 | 状态 |
|---|---|---|---|
| S23-I01 | 首轮新增测试 3 failed：多接收人写变更通知触发 `UNIQUE constraint failed: notifications.dedupe_key` | `notifications.dedupe_key` 是全局唯一索引；变更通知原 key 未含接收人，发布者与成员撞键。把接收人 ID 纳入 key 后 12 passed | 已修复 |
| S23-I02 | 首轮独立审查 **0 Critical / 10 Important / 11 Suggestion**，阻塞提交 | 下游任务未按可见性过滤且字段过宽、PATCH 接受非法 deadline、原始字符串比较与归一化版本不一致、并发唯一冲突未返回 4090、额度二次检查缺失、前端失败重试不复用 request_id、stale 未读误减、改期预览重复请求、4290 后额度不刷新、测试缺口 | 前 9 项已修复并补测试；测试缺口补齐 |
| S23-I03 | 第二轮复核 **0 Critical / 2 Important / 10 Suggestion** | AgentDock 未拦截零额度；并发额度二次检查只是软上限，测试命名/说明会误导 | 已在 store/AgentDock 增加守卫并澄清软上限与测试名 |
| S23-I04 | 第三轮复核 **0 Critical / 1 Important / 6 Suggestion** | AgentDock 挂载时不加载 usage，独立页面首次发送不被拦截；跨天缓存可能误禁用 | 已改为 AgentDock 预加载 + store 发送前按日期刷新。按项目“最多三轮”上限未再开第四轮，**该最后修复未经独立复核** |
| S23-I05 | 新增测试出现 `used` 断言 2 != 1 | 测试函数共享同一 worker，真实模型用例先扣 1 次；改为相对基线断言，行为未变 | 已修复 |
| S23-I06 | 准备隔离演示库时 `scripts/seed_phase2_demo.py` 固定写 `outputs/phase2/demo_secrets.json`，覆盖了该本地忽略历史文件 | 脚本路径写死，不是本轮代码缺陷；旧邀请/重置明文 token 不可恢复；未进入 Git、未影响业务库 | 已记录，未再运行该脚本 |
| S23-I07 | Playwright MCP 在同一消息重复 invoke，截图元素超时 | 与 stage20/22 同类；按项目规则停止浏览器调用，不重试。已取得通知失效、AI 额度、改期影响卡的真实快照与截图 | 已停止 |
| S23-I08 | 安全红线本地 12 通过 / 1 失败（B5b） | 仅因 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/temp/`、`work/` 被忽略日志残留；未删除证据、未改基线 | 如实记录 |

## 6. 验证（真实命令与结果）

后端（项目根，Python 3.12，隔离临时库）：

- `python -m pytest tests/backend/test_aiw05_proactive_quota.py -q`：**12 passed / 0 failed**（最终验证子代理复跑，2.24s）。
- 受影响回归：`test_ai_console.py` 11 passed、`test_reliability.py` 11 passed、`test_task_graph.py` 13 passed、`test_aiw04_resource_review.py` 15 passed。
- `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`：**EXIT=0**；`verify_tables` **58 项（23 表）**、applications 410、api_e2e 255、agent_mock 229、incremental 358、sse 105、unfiltered 25。

前端：

- `cd frontend && npx vue-tsc --noEmit`：**EXIT=0**。
- `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`：**EXIT=0**，构建 **4/4**、契约 **25/25**、语音 **21/21**，dist 已重建。

安全红线：

- `bash tests/security/test_security_redline.sh`：**12 通过 / 0 PASS-LOCAL / 1 失败 / 共 13 项**，失败项 **B5b**（本地运行产物残留）。未删除证据、未修改基线，CI 干净检出不含这些文件。

浏览器（Playwright MCP，`http://127.0.0.1:8000` 同源 dist + `outputs/aiw05/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：

- 成员 `member01` 个人页：变更通知「任务截止时间已调整」未读 1 条；旧提醒「任务今天截止」显示 **已失效** 且不计未读；AI 用量显示 **今日 1 / 50 次，剩余 49 次** 与最近 `chat · 1 次`。
- AI 页：提问后生成 mock 回答与 2 条可见来源，额度从 0/50 变为 1/50。
- 发布者 `collab` 后台：改期对话框显示「当前截止 → 拟调整」、提醒未变化、受影响成员 1 人（陈同学）、后续任务 0、通知接收人 2。
- 截图：`codearts_proof/screenshots/stage23/admin-change-impact.png`。
- **未验证**：零额度 UI 的浏览器表现、AgentDock 零额度提示、移动视口、深色主题、真实模型、真机。Playwright MCP 重复调用后已停止，未继续重试。

## 7. 独立审查

- 首轮（general，只读）：**0 Critical / 10 Important / 11 Suggestion**，结论阻塞。Important 全部处置。
- 第二轮（同一审查会话，只复核修复）：**0 Critical / 2 Important / 10 Suggestion**。R1/R2 已处置。
- 第三轮（同一审查会话，只复核修复）：**0 Critical / 1 Important / 6 Suggestion**。T1 已处置；按项目最多三轮上限，**T1 的最后修复未经第四轮独立复核**。
- 审查者未独立运行 pytest、`vue-tsc`、`run_all`、安全红线或浏览器；最终验证由独立验证子代理执行并回报。

## 8. 未完成与待回填

- 真实模型、真机、移动视口、深色主题、零额度 UI 与 AgentDock 零额度提示：**未验证**。
- 额度并发为软上限，不保证 SQLite 多请求下的硬上限；本轮已在代码注释、测试名与留痕中明确。
- Git 提交：`e35836d5d87cd0bb50a4ff850353e0417ad380ea`（`feat(collab): 增加提醒失效、变更影响与 AI 用量额度`），已推送 `origin/main`（`f09084d..e35836d`）。
- 对应 SHA 的 CI：run [43513010046](https://github.com/shanec7825/campus-task-agent/actions/runs/43513010046) 四个 job 全部 success（Backend API/SSE integration、Backend reliability ubuntu/windows、Frontend build/voice/security）；未部署。
- 提交后的文档回填（本文件、LOG、HANDOFF、task）作为同阶段收口补充提交；其结果在交接中回填，不改变业务提交 `e35836d` 的验收结论。