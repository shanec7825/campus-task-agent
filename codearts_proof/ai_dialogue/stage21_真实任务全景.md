# stage21 真实任务全景（AIW-03）

> 日期：2026-11-14。状态（截至本记录）：实现完成；收口轮门禁通过（新增 `test_task_graph.py` **13 passed**、受影响后端回归 **85 passed**、后端 `run_all` **EXIT=0 / 1419 PASS**、前端 `run_all` **EXIT=0**、`vue-tsc` **EXIT=0**、安全红线本地 **12 通过 / 1 失败（B5b 本地日志残留）**）；第二轮独立审查 **0 Critical / 2 Important** 已修复；第三轮复核结论见第 7 节；未提交、未推送、未部署。
> 本文件只记录真实发生的事项；未执行的项目明确写「未验证」或「待回填」。

## 1. 需求来源与授权

- 来源：用户本轮「每小时触发一次的阶段开发任务」指令（摘要归档见 `prompts/agent_team_启动指令/2026-11-14_stage21_真实任务全景_启动指令.md`，未逐字重建原文）；本地总计划 `ai-workbench/roadmap.md` 的 AIW-03「真实任务全景」。
- 授权：已确认 AIW-00 至 AIW-06 范围内的阶段开发、必要修复、测试、独立审查与记录；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 非目标：成果上传、AI 预审、自动验收、额度账本、多级审批、拖拽编辑、软/硬依赖。

## 2. 开工基线

- 分支 `main`；HEAD `b6fea74d2b7525d44dd917b8236f6da17d37bd1d`（stage20 文档回填）。
- `git status --short` 为空；`git stash list` 为空；`git worktree list` 只有主工作区。未发现其他会话或子任务写入者。
- 上一阶段 AIW-02 已验收：`d327dcb` 已推送，CI run 43469876180 四个 job success。
- 本地新增计划 `aiw03-task-graph/{design,task}.md`（Git 忽略，不提交）。

## 3. 决策与范围

- 依赖边表 `task_dependencies` 作为新事实来源；旧 `tasks.depends_on` 保留为首个前置兼容索引，读取取并集，写入统一走 `task_graph_service`。
- 依赖合法性：存在、非自身、非重复、同层级、同活动、同组织、无环；失败 `4001` 且写库前返回。
- 显式 `depends_on_ids` 覆盖旧 `depends_on`；显式空数组清空；`depends_on_ids=null` 不修改。
- 归属（parent/activity/org）变更但未显式改依赖时，重新校验旧依赖，防止跨范围脏边。
- 报名：所有前置 `verified` 才可报名；不可见前置不泄露标题，只提示数量。
- 图谱数据只由服务端返回；活动全图与任务局部图共用 `TaskGraph.vue`；缺日期进入未排期，不补时间。
- `TaskContentSections.vue` 供发布（可编辑）与详情（只读）复用。
- 从活动进入发布页时，手动与 AI 模式都携带 `activity_id`。

## 4. 实际变更

后端：

- `backend/app/models.py`：新增 `TaskDependency`（`uq_task_dependencies_task_dep`、`ix_task_dependencies_depends_on_id`），表数 19。
- `backend/app/services/task_graph_service.py`：新增依赖读取/校验/替换、批量状态、未完成前置、邻居任务、共用图谱构造。
- `backend/app/routers/tasks.py`：创建/PATCH/详情/列表接入多前置；`_is_claimable` 改为全部前置完成；归属变更重新校验；节点与边输出。
- `backend/app/routers/applications.py`：4020 校验改为全集，并过滤不可见前置标题。
- `backend/app/routers/activities.py`：活动详情返回 `graph`，与可见任务集合同源。
- `backend/app/schemas.py`：新增 `TaskOut.depends_on_ids`、`TaskDetailOut.dependencies/dependents`、`TaskBrief.depends_on_ids`、`TaskGraph*`、`ActivityDetailOut.graph`。
- `tests/backend/test_task_graph.py`：13 个测试函数，覆盖多前置、解锁、非法依赖、成环、图一致性、可见性、局部图、PATCH 替换/清空、归属变更、消息脱敏、子任务摘要完整前置集合。
- `tests/backend/verify_tables.py`：19 表断言 + 新表列/唯一约束/DDL 名/反向前置索引。
- `tests/backend/run_all.sh`、`.github/workflows/ci.yml`、`docs/CI.md`：表数量文案与 AIW-03 测试接入。

前端：

- `frontend/src/components/task/TaskGraph.vue`：依赖层级、边文字、工作区间条、未排期区、实例级唯一 aria id、真实时间上下界。
- `frontend/src/components/task/TaskContentSections.vue`：发布/详情共用字段区块；只读态保留长描述折叠。
- `frontend/src/views/ActivityDetail.vue`：活动「依赖与时间图」。
- `frontend/src/views/TaskDetail.vue`：多前置列表、局部图、同活动全景按需加载、隐藏前置提示、共享内容区块。
- `frontend/src/components/Publish/ManualForm.vue`：同活动多前置选择、共享内容区块。
- `frontend/src/views/PublishPage.vue`、`components/Publish/AiPanel.vue`：AI/手动都携带活动归属。
- `frontend/src/types/models.ts`、`api/tasks.ts`、`components/task/TaskCard.vue`：类型与多前置阻断提示。

## 5. 真实问题与处置

| 编号 | 现象 | 根因与处置 | 状态 |
|---|---|---|---|
| S21-I01 | 首次运行新增测试 1 failed：重复前置请求返回 code=0 | `_merge_dependency_ids` 在服务校验前静默去重，掩盖用户错误；改为保留原始输入，由 `validate_dependencies` 判重 | 已修复，7 passed |
| S21-I02 | 同一测试后续失败：`非法依赖请求不得留下任何边` 期望 0，实际 4 | 测试使用全局边数而非基线，前序用例已写入合法边；改为记录基线并检查被拒标题未落库、边数不变 | 已修复 |
| S21-I03 | 浏览器验证中 Playwright MCP 在同一消息重复执行 navigate/snapshot/click | 同一条消息同时使用 `tool_call` 与直接工具名通道；系统提示重复调用模式后停止 MCP 交互，不再重试 | 已停止；AI Tab 未点击验证 |
| S21-I04 | 首轮独立审查 9 项 Important | PATCH 归属变更未重校验旧依赖、合并语义与设计分叉、4020 泄露不可见前置标题、前端仍用旧 `depends_on`、隐藏前置文案矛盾、重复 DOM id、时间上界偏小、边界测试缺口、留痕未落盘 | 代码与测试项已修复；留痕本文件 |
| S21-I05 | 审查 Suggestion：PublishPage 注释过期、TaskBrief 前端多出后端无的时间字段、依赖索引未断言、节点未去重、长描述折叠回退、活动/组件标题重复 | 已同步注释、删除多余类型字段、补索引断言、图节点去重、只读描述折叠、活动标题改为「依赖与时间图」 | 已修复 |
| S21-I06 | 审查 Suggestion：原生 `<a>` 整页刷新、无区间刻度、并发环检测窗口 | 未在本轮修改；记录为后续建议 | 未处理（非阻断） |
| S21-I07 | 收口轮首次运行测试 `collection` 失败：`test_task_graph.py:779` `IndentationError: unexpected indent` | 上次编辑把 `assert int(detail["activity_id"])...` 顶格，丢失函数体缩进；补 4 空格后 **12 passed** | 已修复 |
| S21-I08 | 第二轮审查 Important：`SubTaskTree` 仍以单值 `depends_on` 判断前置完成，多前置中「首项已完成、其余未完成」时会误判为可推进 | 后端 `TaskBrief` 新增 `depends_on_ids`，任务详情对 `children/dependencies/dependents` 批量填充；前端子任务树按全集判断 `blocked`，展示首项并标注总项数 / 信息缺失数；新增子任务摘要回归用例（**13 passed**） | 已修复 |
| S21-I09 | 第二轮审查 Important：`LOG.md` / `HANDOFF.md` 无 stage21 行，stage21 第 8 节仍为待回填 | 本次收口更新 stage21、`codearts_proof/LOG.md`、`docs/HANDOFF.md` | 已修复 |
| S21-I10 | 第三轮审查 Important：`SubTaskTree` 当前节点只收到首个 `predecessor`，第 2 个及以后前置被误判为「信息缺失」并显示不可推进，即使全部已完成 | `SubTaskTree` 增加 `predecessors: TaskBrief[]` 并合入 `taskMap`；`TaskDetail` 传 `task.dependencies` 全集；提示文案区分「未完成」与「信息缺失」 | 已修复 |
| S21-I11 | 第三轮审查 Important：`docs/HANDOFF.md` 实际未更新，S21-I09 与 LOG 的「已修改」表述不实 | 按实际状态更新 HANDOFF（stage21、基线、变更、验证、审查与未验证项） | 已修复 |
| S21-I12 | 第三轮审查 Important：新增子任务摘要用例只设 1 个前置，回退为单值实现仍会通过 | 改为 2 个前置，断言集合完整且首项与旧 `depends_on` 一致 | 已修复，13 passed |

## 6. 验证（真实命令与结果）

后端（项目根）：

- `python -m pytest tests/backend/test_task_graph.py -q`：首轮 **1 failed / 6 passed**（S21-I01）；修复后 **7 passed**；补审查用例后 **12 passed in 3.55s**；收口轮修复缩进后 **12 passed**，再补子任务摘要用例后 **13 passed in 3.20s**。
- `python -m pytest tests/backend/test_activity_hierarchy.py tests/backend/test_activity_workflow.py tests/backend/test_applications.py tests/backend/test_aiw02_activity_scope.py -q`：**27 passed in 5.40s**。
- `python -m pytest tests/backend/test_auth_org_permissions.py tests/backend/test_ai_console.py -q`：**58 passed in 15.28s**。
- 审查修复后合并回归（活动层级/流程/报名/AIW-02/认证/AI）：**85 passed in 19.35s**；收口轮（含 `TaskBrief.depends_on_ids` 改动）复跑同组 **85 passed in 17.25s**；第三轮修复后最终复跑 **85 passed in 17.38s**。
- `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`：审查前 **EXIT=0，1418 PASS**；收口轮 **EXIT=0，1419 PASS / 0 FAIL**；第三轮修复后最终复跑仍 **EXIT=0，1419 PASS / 0 FAIL**（`outputs/aiw03/backend-runall-release.log`，本地忽略）。

前端（项目根）：

- `cd frontend && npx vue-tsc --noEmit`：**EXIT=0**（收口轮修复后复跑仍 EXIT=0）。
- `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`：审查前 **ALL PASS**；收口轮 **EXIT=0**，构建成功、契约 **25 passed / 0 failed**、语音 **21 PASS / 0 FAIL**；第三轮修复后最终复跑仍 **EXIT=0**（`outputs/aiw03/frontend-runall-release.log`，本地忽略）。
- `PYTHON_BIN="$(command -v python)" bash tests/security/test_security_redline.sh`：本地 **12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**。失败仅因仓库内 `outputs/`、`work/` 的被忽略运行日志残留；未删除本地证据，也未修改检查基线。CI 干净检出不含这些文件。

浏览器（Playwright MCP，8000 同源 dist + `outputs/aiw03/demo-aiw03.db` + `MAAS_MOCK=1` + `RUN_SCHEDULER=0`）：

- `/activities/1`：6 个任务 / 4 条依赖 / 3 层；`舞台布置` 前置「物料采购、场地确认」；`未排期（1）`。
- `/tasks/3`：前置依赖（2）、局部图 4 节点 / 3 边、后继「现场检查」。
- 点击「查看同活动全景」：6 节点 / 4 边。
- `/publish?activity=1`：手动模式「任务将归属活动 #1」、共享内容区块、前置依赖多选。
- 证据：`outputs/aiw03/walkthrough.md`、`.playwright-mcp/page-*.yml`（本地忽略）。
- **未验证**：AI Tab 归属提示与发布、真实模型、真机、390×844 视口；发布提交未点击，避免污染演示库。

## 7. 独立审查

- 首轮独立 Review Agent（general，只读）：结论「有阻塞项」；**0 Critical / 9 Important / 10 Suggestion**。审查者自行复跑 `test_task_graph.py` 7 passed、27 passed、58 passed、`run_all` EXIT=0 / 1418 PASS，并指出前端门禁未独立复跑。
- 9 项 Important 已修复代码与测试；修复后的第二轮复核：
  - 第二轮（general，只读）：**0 Critical / 2 Important / 10 Suggestion**。首轮 9 项修复已实际落实，12 项新增测试与 85 项相关回归通过。2 项 Important 为：`SubTaskTree` 仍按单值 `depends_on` 判断（S21-I08）、阶段留痕未收口（S21-I09）；均已按第 5 节处置。
  - 第三轮（general，只读）：**0 Critical / 3 Important / 5 Suggestion**。3 项 Important 为：当前节点只解析首个前置（S21-I10）、HANDOFF 未更新（S21-I11）、新增用例只测单前置（S21-I12）；均已按第 5 节修复。按项目「最多三轮」规则，最后修复不再开第四轮，**该轮修复未经独立复核**，需在交接中保留此事实。
  - 第三轮审查者实际复跑：`test_task_graph.py` **13 passed**、受影响回归 **85 passed**、`vue-tsc` **EXIT=0**；未独立复跑完整 `run_all`、安全红线、浏览器与 CI。

## 8. 未完成与待回填

- 第三轮独立复核：见下文回填。
- 浏览器 AI 模式、真实模型、真机、390×844 移动端视口、发布提交：**未验证**；本轮未重跑浏览器交互，沿用第 6 节已有实测范围。
- 安全红线 B5b：本地因 `outputs/`、`work/` 被忽略日志残留而失败；CI 干净检出预期通过，但以对应 SHA 的 CI 结果为准。
- 未处理 Suggestion：原生链接整页刷新、区间刻度、并发环检测窗口、`parent_id`/`org_id` 变更用例、多跳环用例、活动图递归收集子任务 id、4020 逐条查询、缺失/不可见前置语义区分等；不写成已修复。
- Git 提交、推送、对应 SHA 的 CI 结果：**未执行**（待最终验证与复核后按授权进行）。