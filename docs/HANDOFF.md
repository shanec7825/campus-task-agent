# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage21 / AIW-03 收口完成：实现、本地门禁、三轮独立审查、提交推送与对应 CI 均已完成）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 本轮开工基线：`b6fea74d2b7525d44dd917b8236f6da17d37bd1d`（stage20 文档回填）。
- 本轮改动：AIW-03「真实任务全景」已提交 `a1bd455d007369663491275a8b53efecdbfef54e` 并推送 `origin/main`（详见第 2 节）。
- 本轮授权范围：AIW-03 收口（实现、必要修复、测试、独立审查、留痕）；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 本轮使用编号：留痕 **stage21**（接续更新，未新增 stage）；业务 Prompt 正文未改。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `backend/app/models.py` | 新增 `TaskDependency`（`uq_task_dependencies_task_dep`、`ix_task_dependencies_depends_on_id`），表数 19 | 依赖边表是新事实来源；不要绕过服务层直接写边 |
| `backend/app/services/task_graph_service.py` | 依赖读取（边表 ∪ 旧 `depends_on`）、7 条校验、替换、批量状态、邻居与共用图谱 | 所有依赖读写必须经此服务；校验先于写库 |
| `backend/app/routers/tasks.py` | 创建/PATCH/详情/列表接入多前置；`_is_claimable` 全部前置 verified；归属变更重校验；`TaskBrief` 批量填充 `depends_on_ids` | 不要恢复单值 `depends_on` 作为主要判定 |
| `backend/app/routers/applications.py` | 4020 按全部前置；不可见前置只给数量；报名列表 `TaskBrief` 同步 `depends_on_ids` | 4020 消息不得泄露不可见前置标题 |
| `backend/app/routers/activities.py` | 活动详情返回 `graph`，与可见任务集合同源，悬空边丢弃 | 图不得新增权限旁路 |
| `backend/app/schemas.py` | `TaskOut.depends_on_ids`、`TaskDetailOut.dependencies/dependents`、`TaskBrief.depends_on_ids`、`TaskGraph*`、`ActivityDetailOut.graph` | 新字段默认空数组，旧接口兼容 |
| `tests/backend/test_task_graph.py` | 13 用例：多前置、解锁、非法依赖/成环、图一致性、可见性、局部图、PATCH 替换/清空、归属变更、消息脱敏、子任务摘要 | 修改依赖行为必须重跑 |
| `tests/backend/verify_tables.py` | 19 表断言 + 新表列/唯一约束/DDL 名/反向前置索引 | 表数量与约束需同步模型 |
| `frontend/src/components/task/TaskGraph.vue` | 依赖层级、边文字、工作区间、未排期区、实例级唯一 aria id、真实时间上下界 | 活动全图与任务局部图共用 |
| `frontend/src/components/task/TaskContentSections.vue` | 发布（可编辑）与详情（只读）共享内容区块 | 不要为详情另写一套字段 |
| `frontend/src/components/task/SubTaskTree.vue` | 按 `depends_on_ids` 全集判断 `blocked`；`predecessors` 传入全部可见前置；区分未完成/信息缺失 | 不要再只看单值 `depends_on` |
| `frontend/src/views/{ActivityDetail,TaskDetail,PublishPage}.vue` | 活动图、任务局部图/同活动全景、共享内容区块；`activity_id` 在手动/AI 模式均保留 | 切换发布模式不得丢活动归属 |
| `.github/workflows/ci.yml`、`docs/CI.md` | backend-reliability 接入 `test_task_graph.py`；文档同步 | 保留只读权限与既有 job |

## 3. 验证、审查与提交状态

- 后端（隔离临时库）：`test_task_graph.py` **13 passed**；受影响回归（活动层级/流程/AIW-02/认证/AI 问答）**85 passed in 17.38s**；`tests/backend/run_all.sh` **EXIT=0 / 1419 PASS / 0 FAIL**（`outputs/aiw03/backend-runall-release.log`，本地忽略）。
- 前端：`npx vue-tsc --noEmit` **EXIT=0**；`PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh` **EXIT=0**（构建成功、契约 **25 passed / 0 failed**、语音 **21 PASS / 0 FAIL**；`outputs/aiw03/frontend-runall-release.log`）。
- 安全红线：本地 **12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**。失败仅因 `outputs/`、`work/` 的被忽略运行日志残留；未删除本地证据、未修改基线。CI 干净检出不含这些文件。
- 浏览器（Playwright MCP，8000 同源 dist + `outputs/aiw03/demo-aiw03.db`，`MAAS_MOCK=1`）：活动全图 6 任务 / 4 边 / 3 层、任务局部图与同活动全景、未排期区、手动发布归属提示均已实测；**AI Tab 归属、发布提交、真实模型、真机、390×844 移动视口未验证**。
- 独立审查：首轮 **0 Critical / 9 Important**、第二轮 **0 Critical / 2 Important**、第三轮 **0 Critical / 3 Important**，均已在代码/测试/留痕中处置；按三轮上限未开第四轮，**第三轮修复未经独立复核**。
- 归档证据：[stage21 过程](../codearts_proof/ai_dialogue/stage21_真实任务全景.md)、[stage21 启动指令](../codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage21_真实任务全景_启动指令.md)、[LOG](../codearts_proof/LOG.md)。
- **提交/推送/CI：** `a1bd455` 已推送 `origin/main`；CI run [43490920161](https://github.com/shanec7825/campus-task-agent/actions/runs/43490920161) 四个 job 全部 success（Backend API/SSE integration、Backend reliability ubuntu/windows、Frontend build/voice/security）。该业务提交是阶段验收依据；随后的文档回填提交不改变业务代码。未部署。

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源与写入约束。
3. 本地总计划 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw03-task-graph/design.md) 与 [task.md](../.codeartsdoer/plans/aiw03-task-graph/task.md)：冻结 5 份契约。
5. [stage21 过程与验证](../codearts_proof/ai_dialogue/stage21_真实任务全景.md)。
6. 上一阶段 [stage20 过程](../codearts_proof/ai_dialogue/stage20_浏览与情境助手.md)。

本地计划缺失时，先告知用户并请求提供文件或明确的新设计依据；不要从历史 HTML、旧 phase2 计划或文件名推导完整需求。

## 5. 下一步

- AIW-03 已完成：实现、自动测试、三轮独立审查、留痕、提交推送与对应 CI（`a1bd455` / run 43490920161）均通过；仅真实模型、真机、移动视口、AI Tab 归属与浏览器发布提交未验证。
- 下一阶段为 **AIW-04：资料与成果审核**（往期资料、按权限检索、成果版本、AI 预审、同页人工验收）。下一次定时运行开始前重新扫描 stage 编号（当前最大 21）、读取本地总计划，并为 AIW-04 新建设计与任务文档；本轮不展开 AIW-04。
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