# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage22 / AIW-04 收口：实现、本地门禁、三轮独立审查已完成；提交与 CI 待回填）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 本轮开工基线：`54440b0d2133b6a4277a42432546fa68b40511e1`（stage21 文档回填）。
- 本轮改动：AIW-04「资料与成果审核」已提交 `a3632cebde608ff877cd1310a287337baa93939f` 并推送 `origin/main`（详见第 2 节）；对应 CI run 43505516305 四个 job 全部 success。
- 本轮授权范围：AIW-04 收口（实现、必要修复、测试、独立审查、留痕）；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 本轮使用编号：留痕 **stage22**（新增，接续本表下一顺位）；业务 Prompt 新增成果预审段，真实模型未试跑。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `backend/app/models.py` | 新增 `ActivityResource`、`TaskSubmission`、`SubmissionPrecheck`，表数 22 | 资料版本按 `resource_key+version`；成果版本按 `(task,user,version)` |
| `backend/app/services/resource_service.py` | 归属校验、SQL 可见性（任务/活动/仅组织）、检索、版本追加、外链协议 | 可见性不得在 Python 过滤；新版本不得改归属 |
| `backend/app/services/submission_service.py` | 版本写入/列表、`can_review_task`、规则预审、模型失败降级、stale | `verdict` 只由规则决定；模型失败不得冒充通过 |
| `backend/app/routers/tasks.py` | `submit` 可选 body、`GET /submissions`、`POST /submissions/{id}/precheck`、`verify` 版本校验与窄审核权限 | 验收权限为发布者/组织 admin/活动负责人；`submission_id` 必须最新 |
| `backend/app/routers/resources.py` | `GET/POST /api/resources` | 创建前先 view（4040）再 manage（4030） |
| `backend/app/schemas.py` | 资料/提交/预审 DTO、`VerifyIn.submission_id` | 新字段均有默认值，旧调用兼容 |
| `tests/backend/test_aiw04_resource_review.py` | 15 用例：权限三分支、版本、预审 fail/pass/unknown、模型失败、空成果、非法链接、旧稿拒绝、assignee 越权、stale | 修改资料/成果/验收行为必须重跑 |
| `tests/backend/verify_tables.py` | 22 表断言 + 新表唯一约束/索引，52 项 | 表数量与约束需同步模型 |
| `frontend/src/views/TaskDetail.vue` | 提交对话框、版本/预审、同页验收、相关资料；加载中/失败禁用盲批 | 验收必须携带 `submission_id` |
| `frontend/src/views/ActivityDetail.vue` | 资料列表、检索、添加/追加版本（回填 task/org） | 更新任务资料不得丢 `task_id/org_id` |
| `.github/workflows/ci.yml`、`docs/CI.md` | backend-reliability 接入 `test_aiw04_resource_review.py` | 保留只读权限与既有 job |

## 3. 验证、审查与提交状态

- 后端（隔离临时库）：`test_aiw04_resource_review.py` **15 passed**；单独进程 `task_graph 13 / activity_workflow 8 / reliability 11 / auth 47 / ai_console 11 / aiw02 6 / hierarchy 13`；`tests/backend/run_all.sh` **EXIT=0 / 1434 PASS / 0 FAIL**（`outputs/aiw04/round2-backend-runall.log`，本地忽略）。
- 前端：`npx vue-tsc --noEmit` **EXIT=0**；`tests/frontend/run_all.sh` **EXIT=0**（构建成功、契约 **25/25**、语音 **21/21**；`outputs/aiw04/round2-frontend-runall.log`）。
- 安全红线：本地 **12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**。失败仅因 `outputs/`、`work/` 被忽略运行日志残留；未删除证据、未修改基线。CI 干净检出不含这些文件。
- 真实 HTTP 走查（隔离演示库，`MAAS_MOCK=1`）：预审错误时间 `fail` 且证据「提交 2026-11-19；要求 2026-11-18/20/22」；旧版本验收 `4090`；最新版本通过并加分；资料本组织可见、外组织为空。
- 浏览器（Playwright MCP，8000 同源 dist）：活动资料新增与列表 v1 已实测；**提交对话框、预审展示、同页验收、跨组织资料前端表现未验证**（MCP 重复调用/超时后停止）。
- 独立审查：首轮 **0 Critical / 9 Important**；第二轮 **0 Critical / 2 Important**；第三轮 **0 Critical / 0 Important / 4 Suggestion**，均已在代码/测试/留痕处置。
- 归档证据：[stage22 过程](../codearts_proof/ai_dialogue/stage22_资料与成果审核.md)、[stage22 启动指令](../codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage22_资料与成果审核_启动指令.md)、[LOG](../codearts_proof/LOG.md)。
- **提交/推送/CI：** `a3632ce` 已推送 `origin/main`；CI run [43505516305](https://github.com/shanec7825/campus-task-agent/actions/runs/43505516305) 四个 job 全部 success（Backend API/SSE integration、Backend reliability ubuntu/windows、Frontend build/voice/security）。该业务提交是阶段验收依据；随后的文档回填提交不改变业务代码。未部署。

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源与写入约束。
3. 本地总计划 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw04-resource-review/design.md) 与 [task.md](../.codeartsdoer/plans/aiw04-resource-review/task.md)。
5. [stage22 过程与验证](../codearts_proof/ai_dialogue/stage22_资料与成果审核.md)。
6. 上一阶段 [stage21 过程](../codearts_proof/ai_dialogue/stage21_真实任务全景.md)。

本地计划缺失时，先告知用户并请求提供文件或明确的新设计依据；不要从历史 HTML、旧 phase2 计划或文件名推导完整需求。

## 5. 下一步

- AIW-04 已完成实现、自动测试、三轮独立审查与留痕；提交/推送/CI 待本次收口回填。仅真实模型、真机、移动视口、浏览器提交/预审/同页验收未验证。
- 下一阶段为 **AIW-05：主动协作与额度**（检查点提醒、变更影响、受控操作卡、用量账本）。下一次定时运行开始前重新扫描 stage 编号（当前最大 22）、读取本地总计划，并为 AIW-05 新建设计与任务文档；本轮不展开 AIW-05。
- 不提交 `outputs/`、`.playwright-mcp/`、`.codeartsdoer/`、数据库与依赖。

## 6. 新 Agent 的最短启动指令

```text
先读取 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md
以及交接文件指向的本地总计划，核对 Git 基线和当前文件。
本轮目标由我在这条指令后明确指定；没有目标时先报告现状，不展开开发。
执行选定阶段前先完善对应 design.md 与 task.md。
按项目规则记录真实过程、问题与验证，不自动进入下一阶段。
提交、推送、部署与删除按本轮明确授权执行。
```