# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage23 / AIW-05 收口：实现、最终门禁、三轮独立审查、浏览器关键流程、提交与 CI 均已完成）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 本轮开工基线：`f09084d842bccc28846fa993a34da923a6af51e5`（stage22 文档回填）。
- 本轮改动：AIW-05「主动协作与额度」已提交 `e35836d5d87cd0bb50a4ff850353e0417ad380ea` 并推送 `origin/main`；对应 CI run 43513010046 四个 job 全部 success。
- 本轮授权范围：AIW-05 收口（实现、必要修复、测试、独立审查、留痕）；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 本轮使用编号：留痕 **stage23**（新增）；未改业务 Prompt，无新 P 编号。
- AIW-04 验收依据：业务提交 `a3632ce` → CI run 43505516305 四个 job success。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `backend/app/models.py`、`db.py` | 新增 `AiUsageLedger` 表（表数 23）；`notifications.stale` 加列 | 表数/列断言在 `verify_tables.py`；旧库幂等补列 |
| `backend/app/services/notify_service.py` | `deadline_version`、`stale_task_reminders`、`notify_task_changed` | 变更通知 key 必须含接收人 ID；只经本服务写通知 |
| `backend/app/services/reminder_scheduler.py` | 每轮按当前截止版本清理旧提醒 | 只失效 `remind:/overdue:/overdue_pub:/unassigned:` |
| `backend/app/services/ai_service.py` | 额度统计、`request_id` 幂等、账本、4290、二次额度检查 | 失败不写账本；额度是次数软上限，非并发硬上限 |
| `backend/app/routers/tasks.py` | `GET /{id}/change-impact`；PATCH 改期/取消副作用 | 下游任务按查看者可见性过滤；PATCH 校验 deadline |
| `backend/app/routers/notifications.py` | stale 不计未读；失效项不可标记已读 | 列表仍返回 stale 供追溯 |
| `backend/app/routers/agent.py` | `GET /api/agent/usage` | 只返回本人数据 |
| `frontend/src/stores/aiChat.ts` | 额度按日期刷新、失败重试复用 request_id、4290 刷新 | 完整页/长条共用同一状态 |
| `frontend/src/views/{AiConsole,Profile,AdminConsole}.vue` | 额度条、AI 用量、失效标签、改期影响确认卡 | 影响卡只读预览，确认后走既有 PATCH |
| `tests/backend/test_aiw05_proactive_quota.py` | 12 用例 | 改通知/额度/改期行为必须重跑 |
| `.github/workflows/ci.yml`、`docs/CI.md` | 接入新套件并设置 `AI_DAILY_QUOTA=50` | 保留只读权限与既有 job |

## 3. 验证、审查与提交状态

- 最终独立验证子代理：`test_aiw05_proactive_quota.py` **12 passed**；`vue-tsc` **EXIT=0**；前端 `run_all` **EXIT=0**（构建 **4/4**、契约 **25/25**、语音 **21/21**）；后端 `run_all` **EXIT=0**（23 表、verify_tables **58 项**、applications 410、api_e2e 255、agent_mock 229、incremental 358、sse 105、unfiltered 25）。
- 安全红线：本地 **12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**。失败仅因 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/temp/`、`work/` 的忽略日志残留；未删除证据、未修改基线，CI 干净检出不含这些文件。
- 浏览器（Playwright MCP，8000 同源 dist + `outputs/aiw05/demo.db`，`MAAS_MOCK=1`）：成员个人页旧提醒「已失效」且不计未读、变更通知未读 1；AI 用量 1/50；发布者后台改期对话框显示当前→拟调整、成员 1、后续任务 0、通知接收人 2。截图 `codearts_proof/screenshots/stage23/admin-change-impact.png`。
- 真实模型、真机、移动视口、深色主题、零额度 UI、AgentDock 零额度提示：**未验证**。
- 独立审查三轮：首轮 **0 Critical / 10 Important**；第二轮 **0 Critical / 2 Important**；第三轮 **0 Critical / 1 Important**。最后一项 AgentDock 额度预加载已修复，但按“最多三轮”上限 **未再开第四轮复核**；该事实已在 stage23 记录中明示。
- 归档证据：[stage23 过程](../codearts_proof/ai_dialogue/stage23_主动协作与额度.md)、[stage23 启动指令](../codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage23_主动协作与额度_启动指令.md)、[LOG](../codearts_proof/LOG.md)、[截图](screenshots/stage23/admin-change-impact.png)。
- **提交/推送/CI：** `e35836d` 已推送 `origin/main`；CI run [43513010046](https://github.com/shanec7825/campus-task-agent/actions/runs/43513010046) 四个 job 全部 success（Backend API/SSE integration、Backend reliability ubuntu/windows、Frontend build/voice/security）。该业务提交是阶段验收依据；随后仅做文档回填。未部署。

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源与写入约束。
3. 本地总计划 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw05-proactive-quota/design.md) 与 [task.md](../.codeartsdoer/plans/aiw05-proactive-quota/task.md)。
5. [stage23 过程与验证](../codearts_proof/ai_dialogue/stage23_主动协作与额度.md)。
6. 上一阶段 [stage22 过程](../codearts_proof/ai_dialogue/stage22_资料与成果审核.md)。

本地计划缺失时，先告知用户并请求提供文件或明确的新设计依据；不要从历史 HTML、旧 phase2 计划或文件名推导完整需求。

## 5. 下一步

- AIW-05 已完成实现、最终门禁、三轮独立审查、浏览器关键流程、留痕、提交推送与 CI。仅真实模型、真机、移动视口、零额度 UI 与 AgentDock 额度提示未验证。
- 下一次定时运行先核对 AIW-05 对应 SHA 的 CI 与留痕是否齐全（当前 `e35836d` / run 43513010046 已 success）；确认后进入 **AIW-06：整体验收**（晚会全流程、退回重提、多角色多设备回归与参赛证据）。进入 AIW-06 前重新扫描 stage 编号（当前最大 23）、读取本地总计划并新建设计与任务文档；本轮不展开 AIW-06。
- 不提交 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/`、数据库、演示凭据与依赖。

## 6. 新 Agent 的最短启动指令

```text
先读取 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md
以及交接文件指向的本地总计划，核对 Git 基线和当前文件。
本轮目标由我在这条指令后明确指定；没有目标时先报告现状，不展开开发。
执行选定阶段前先完善对应 design.md 与 task.md。
按项目规则记录真实过程、问题与验证，不自动进入下一阶段。
提交、推送、部署与删除按本轮明确授权执行。
```