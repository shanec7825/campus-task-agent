# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage24 / AIW-06 收口：验收套件、阶段门禁、三轮独立审查、浏览器关键流程与留痕已完成；业务提交 `a728788` 已推送，对应 CI run 43532974986 四个 job success。AIW-00 至 AIW-06 全部完成并通过验收）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 本轮开工基线：`d25c91cc2fd38910fff76d2934465e46558c5fdd`（stage23 文档回填）。
- 本轮改动：AIW-06「整体验收」验收增量；业务提交 `a728788af906ccd2bf529166321f467277beec92` 已推送 `origin/main`；对应 CI run 43532974986 四个 job 全部 success。
- 本轮授权范围：AIW-00 至 AIW-06 已确认阶段的实现、必要修复、测试、独立审查、留痕；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作、修改安全策略。
- 本轮使用编号：留痕 **stage24**（新增，LOG 原最大 23）。未改业务 Prompt，无新 P 编号。
- AIW-05 验收依据：业务提交 `e35836d` → CI run 43513010046 四个 job success。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `tests/backend/test_aiw06_acceptance.py` | 新增一条完整晚会协作链路；导入前隔离临时库，导入后断言 engine 指向临时库，退出 `dispose()` 后清理 | 本套件必须单文件运行；全量 pytest 会模块级 skip。改通知/额度/改期/验收行为必须重跑 |
| `.github/workflows/ci.yml`、`docs/CI.md` | Backend reliability job 接入新套件；文档补整体验收描述与本地命令 | 保留只读权限与既有 job，不静默跳过 |
| `codearts_proof/screenshots/stage24/` | 8 张真实截图：桌面 AI 首页、大厅、活动详情、提交 v1、预审失败、改期影响卡；移动 AI 首页、任务详情 | 01/03/04/05 实际 1425 宽，仅 02/06 为 1440×900；不得声称全部满足 design 的 1440×900 |
| `codearts_proof/reports/stage24_整体验收.md` | 命令、退出码、计数、截图索引、未验证范围 | 历史数字不替代本轮结果 |
| `codearts_proof/ai_dialogue/stage24_整体验收.md` | 五节/八节过程记录、问题表、审查与验证 | 同阶段接续更新本文件，不重分 stage |
| `codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage24_整体验收_启动指令.md` | 本轮实际收到的定时任务指令原文 + 摘要 | 原文与摘要分区，不重建缺失内容 |
| `codearts_proof/LOG.md`、`docs/HANDOFF.md` | 新增 stage24 行/更新交接 | 提交与 CI 结果实际发生后回填 |

## 3. 验证、审查与提交状态

- 验收套件：`PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw06_acceptance.py -q` → **1 passed**（收口时 3.46s；2026-11-14 CI 回填续跑复跑 5.15s，均 EXIT=0）。
- 后端 `run_all`：**EXIT=0**；`verify_tables` **58 项（23 表）**、applications 410、api_e2e 255、agent_mock 229、incremental 358、sse 105、unfiltered 25。
- 前端 `run_all`：**EXIT=0**；构建 **4/4**、契约 **25/25**、语音 **21/21**；dist 已重建。
- 安全红线：本地 **12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**。失败仅因 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/temp/`、`work/` 的忽略日志残留；未删除证据、未修改基线，CI 干净检出不含这些文件。
- 浏览器（Playwright MCP，8000 同源 dist + `outputs/aiw06/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：AI 首页通知/额度；大厅活动下任务；活动详情任务全景；成员提交 v1；预审 fail（时间一致性）；后台改期影响卡（成员 1、后续任务 0、通知接收人 2）；移动 AI 首页与任务详情。页面宽度实测 `innerWidth=390`、`docScrollWidth=375`、`horizontalOverflow=false`。截图见 `codearts_proof/screenshots/stage24/`。
- 未验证：真实模型输出质量、真机、移动端完整提交/验收操作、深色主题、部署、全量 pytest 下本套件 skip 的报告形态。
- 独立审查三轮（general，只读）：首轮 **0 Critical / 4 Important**；第二轮 **0 Critical / 2 Important**；第三轮 **0 Critical / 0 Important / 3 Suggestion**。第三轮为最终轮，之后仅补文档留痕，未改测试或业务代码。
- **提交/推送/CI：** `a728788` 已推送 `origin/main`；CI run [43532974986](https://github.com/shanec7825/campus-task-agent/actions/runs/43532974986) 四个 job 全部 success（Backend API/SSE integration、Backend reliability ubuntu/windows、Frontend build/voice/security）。未部署。
- **文档回填：** 提交 `2439154078ecb3860526c0c70edbcee251f272b9`（`docs(stage24): 回填 AIW-06 提交与 CI 结果`）已推送；对应 CI run `43533483789` 四个 job 全部 success。

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源与写入约束。
3. 本地总计划 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw06-acceptance/design.md) 与 [task.md](../.codeartsdoer/plans/aiw06-acceptance/task.md)。
5. [stage24 过程与验证](../codearts_proof/ai_dialogue/stage24_整体验收.md)。
6. [stage24 验收报告](../codearts_proof/reports/stage24_整体验收.md)。
7. 上一阶段 [stage23 过程](../codearts_proof/ai_dialogue/stage23_主动协作与额度.md)。

本地计划缺失时，先告知用户并请求提供文件或明确的新设计依据；不要从历史 HTML、旧 phase 计划或文件名推导完整需求。

## 5. 下一步

- AIW-00 至 AIW-06 的实现、本地验收与对应 CI 已全部通过，AIW-06 标记为最终完成。
- 全部已确认阶段完成并通过验收，本项目每小时定时任务（Task ID `75f554a4`）已于 2026-11-14 暂停（`cronDelete` pause，未删除，配置保留）；后续如需继续，须由用户另行明确新的产品范围后再恢复。
- 未验证项保持如实记录：真实模型、真机、移动端完整提交/验收、深色主题、部署。后续若要继续，先单独确认新的产品范围，不从本交接自动推导新阶段。
- 不提交 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/`、数据库、演示凭据与依赖、构建产物。

## 6. 新 Agent 的最短启动指令

```text
先读取 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md
以及交接文件指向的本地总计划，核对 Git 基线和当前文件。
本轮目标由我在这条指令后明确指定；没有目标时先报告现状，不展开开发。
执行选定阶段前先完善对应 design.md 与 task.md。
按项目规则记录真实过程、问题与验证，不自动进入下一阶段。
提交、推送、部署与删除按本轮明确授权执行。
```