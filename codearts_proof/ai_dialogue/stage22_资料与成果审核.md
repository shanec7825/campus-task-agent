# stage22 资料与成果审核（AIW-04）

> 日期：2026-11-14。状态（截至本记录）：实现完成；新增 `test_aiw04_resource_review.py` **15 passed**；受影响回归与后端 `run_all` **EXIT=0 / 1434 PASS**、前端 `run_all` **EXIT=0**、`vue-tsc` **EXIT=0**；独立审查三轮（9 / 2 / 0 Important，第三轮 **0 Critical / 0 Important**）；浏览器仅完成资料新增与展示，其余交互因 Playwright MCP 重复调用/超时未验证；真实模型、真机、移动视口未验证。**已提交并推送 `a3632ce`，CI run 43505516305 四个 job 全部 success；未部署。**
> 本文件只记录真实发生的事项；未执行的项目明确写「未验证」或「待回填」。

## 1. 需求来源与授权

- 来源：用户本轮「每小时触发一次的阶段开发任务」指令（原文归档 `codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage22_资料与成果审核_启动指令.md`）；本地总计划 `ai-workbench/roadmap.md` 的 AIW-04「资料与成果审核」。
- 授权：AIW-00 至 AIW-06 已确认范围内的阶段开发、必要修复、测试、独立审查与记录；每阶段一次提交、正常推送 `origin/main` 并跟踪对应 SHA 的 CI；不授权部署、付费、删除文件或数据、破坏性 Git 操作。
- 非目标：文件上传/正文解析/向量检索、多级审批、最终自动验收、收费/额度规则；人工验收仍是唯一改变成员状态与积分的路径。

## 2. 开工基线

- 分支 `main`；开工 HEAD `54440b0d2133b6a4277a42432546fa68b40511e1`（stage21 文档回填）。
- `git status --porcelain` 为空；无 `.git/index.lock`；未发现其他会话或子任务写入者。
- AIW-03 对应 CI 实查：`a1bd455` → run 43490920161 `completed / success`；`54440b0` → run 43491327394 `completed / success`。因此 AIW-03 已验收，本次进入 AIW-04。
- 开工快照：`outputs/aiw04/opening-head.txt`、`opening-git-status.txt`、`opening-diff.patch`（本地忽略）。
- 本地新增计划 `aiw04-resource-review/{design,task}.md`（Git 忽略，不提交）。

## 3. 决策与范围

- 新表 3 张（19 → 22）：`activity_resources`（资料与版本）、`task_submissions`（成果版本）、`submission_prechecks`（预审记录）。
- 资料可见性在 SQL 层过滤：绑定任务看任务可见性；绑定活动看活动负责人/组织 admin/活动下可见任务；仅组织看组织成员或创建者本人；三条均不满足不返回。
- 资料版本按 `resource_key + version` 追加，旧版本保留；新版本不得改变归属范围。
- 每次成员从 `in_progress|rejected → submitted` 生成一条成果版本；旧无 body 提交仍可生成空内容版本。
- 验收可带 `submission_id`，指定时必须等于该成员最新版本，否则 `4090`；前端同页验收始终携带当前展示版本。
- 成果审核范围单独收窄为**发布者 / 组织管理员 / 活动负责人**（`can_review_task`）；`assignee` 仍是任务管理者，但不算成果审核者，后续权限梳理另议。
- 预审 = 确定性规则（必选） + 模型建议（非 mock 时）。`verdict` 只由规则决定；模型失败写 `ai_error`，不改变规则结论、不冒充通过；预审只写预审表。
- 外链只允许 http/https：资料创建直接 `4001`；成果链接规则判 `fail`；前端 `href` 再次做协议白名单。

## 4. 实际变更

后端：

- `backend/app/models.py`：新增 `ActivityResource`（`uq_activity_resources_key_version` + 三个归属索引）、`TaskSubmission`（`uq_task_submissions_task_user_version`）、`SubmissionPrecheck`（`submission_id` 索引），表数 22。
- `backend/app/services/resource_service.py`：归属一致性、创建/追加版本、SQL 可见性、关键词打分、任务相关资料、权限判定、外链校验。
- `backend/app/services/submission_service.py`：版本写入与读取、窄审核判定、规则预审（内容/时间/要求/链接/资料）、时间证据、模型建议、失败降级、预审持久化、stale 摘要。
- `backend/app/routers/resources.py`：`GET /api/resources`、`POST /api/resources`。
- `backend/app/routers/tasks.py`：`submit` 可选 body 并生成版本；`GET /{id}/submissions`；`POST /{id}/submissions/{sid}/precheck`；`verify` 校验 `submission_id` 为最新版本，并把验收权限改为 `require_task_review`。
- `backend/app/schemas.py`：资料、提交、预审 DTO 与 `VerifyIn.submission_id`。
- `backend/app/agents/prompts.py`：新增 `PRECHECK_SYSTEM_PROMPT` / `render_precheck_prompt`（正文唯一来源；本轮未真实模型试跑）。
- `backend/app/db.py`、`main.py`、`routers/__init__.py`：表清单/路由挂载同步。

前端：

- `frontend/src/api/resources.ts`、`api/tasks.ts`、`types/models.ts`：资料与成果接口和类型。
- `frontend/src/views/TaskDetail.vue`：提交对话框（成果说明/链接）、本人版本历史、发布者待验收区（最新版本 + 预审 + 同页通过/退回）、相关资料；成果加载失败/加载中禁用验收，避免盲批。
- `frontend/src/views/ActivityDetail.vue`：活动资料列表、权限内关键词检索、添加资料/追加版本（回填 `task_id/org_id`）。
- 复用既有 `--app-*` / `--el-*` 令牌与 768px 断点，无新增硬编码色值和 12px 字号。

测试与门禁：

- `tests/backend/test_aiw04_resource_review.py`：15 个行为用例，覆盖 4 条验收标准、三条可见性分支、版本、预审失败/通过/未知、模型失败、空成果、非法链接、assignee 越权、stale。
- `tests/backend/verify_tables.py`：22 表 + 新表列/唯一约束/DDL 名/索引，52 项断言。
- `.github/workflows/ci.yml`、`docs/CI.md`、`tests/backend/run_all.sh`：接入新套件并同步表数文案。

## 5. 真实问题与处置

| 编号 | 现象 | 根因与处置 | 状态 |
|---|---|---|---|
| S22-I01 | 首次新增测试 2 failed：资料越权断言期望 HTTP 200，实际 403；检索断言要求结果集合只含一条 | 测试预期写错（`ApiError(4030)` 是 HTTP 403；关键词检索会命中相似资料） | 已修正测试，9 passed |
| S22-I02 | Playwright MCP 在同一消息重复 invoke navigate/type/click/snapshot，随后 `browser_run_code_unsafe` 超时 | 与 stage20/21 同类：同一消息复制了两次工具调用；按项目规则立即停止浏览器调用，不继续重试 | 已停止；仅完成资料新增/展示 |
| S22-I03 | 演示库 `member01` 密码校验失败（历史演示副本曾被重置） | 历史演示账号密码已变更，不是产品缺陷；在隔离副本内重置为测试口令后继续，未触碰真实库 | 已处理（隔离库） |
| S22-I04 | 接口走查最后一步中文查询触发 `UnicodeEncodeError` | urllib 需 URL 编码中文 query；改为 `urllib.parse.quote` | 已修复，走查通过 |
| S22-I05 | 首轮独立审查 **0 Critical / 9 Important / 11 Suggestion**，结论阻塞 | 9 项：活动页任务资料无法更新、活动 admin 可见性旁路、可见性分支测试缺失、assignee 可看他人成果、外链未校验协议、创建资料 4030 泄露存在性、模型失败/空成果无测试、成果加载失败可盲批、留痕缺失 | 前 8 项已修复并补测试；留痕本轮补齐 |
| S22-I06 | 第二轮复核 **0 Critical / 2 Important / 5 Suggestion** | `verify` 仍用 `can_manage_task`，assignee 可越权验收并探测他人成果；成果加载期间按钮可盲批 | 已修复：新增 `can_review_task/require_task_review` 并接入 verify；加载中/失败均禁用验收；补 assignee 4030 与活动 admin 分支测试 |
| S22-I07 | 第三轮复核 **0 Critical / 0 Important / 4 Suggestion** | 不阻塞；建议包括 assignee 其他管理操作属既有契约、组织 admin 验收 UI 未扩展、文档措辞、检索性能 | 未修改；记录为后续建议 |
| S22-I08 | 合并多个 pytest 文件运行 `test_reliability.py` 出现 10 setup errors：`no such table: users` | 同一 pytest 进程先导入 app，模块级临时 `DATABASE_PATH` 失效；CI 本身分 step 运行。单独复跑 11 passed，不是产品缺陷 | 已确认并如实记录 |
| S22-I09 | `test_applications.py` pytest 收集 0 项、EXIT=5 | 该文件是独立脚本（`main()`），由 `run_all.sh` 调用，不是 pytest 用例 | 已确认，不改测试 |

## 6. 验证（真实命令与结果）

后端（项目根，Python 3.12）：

- `python -m pytest tests/backend/test_aiw04_resource_review.py -q`：首轮 **9 passed**；补审查用例后 **13 passed**；第二轮修复后 **15 passed**（日志 `outputs/aiw04/round2-aiw04.log`）。
- 核心回归（同进程）：`test_task_graph.py + test_activity_workflow.py + test_applications.py + test_aiw04...` → **34 passed**（其中 applications 为独立脚本，pytest 收集 0 项）。
- 单独进程：`test_reliability.py` **11 passed**、`test_auth_org_permissions.py` **47 passed**、`test_ai_console.py` **11 passed**、`test_aiw02_activity_scope.py` **6 passed**、`test_activity_hierarchy.py` **13 passed**；`test_task_graph.py` **13 passed**、`test_activity_workflow.py` **8 passed**。
- `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`：**EXIT=0，1434 PASS / 0 FAIL**（`outputs/aiw04/round2-backend-runall.log`，本地忽略）；`verify_tables` **52 项断言（22 表）**。

前端（项目根）：

- `cd frontend && npx vue-tsc --noEmit`：**EXIT=0**（修复后复跑仍 0）。
- `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`：**EXIT=0**，构建成功、契约 **25 passed / 0 failed**、语音 **21 PASS / 0 FAIL**（`outputs/aiw04/round2-frontend-runall.log`）。
- `bash tests/security/test_security_redline.sh`：本地 **12 通过 / 0 PASS-LOCAL / 1 失败（B5b）**。失败仅因 `outputs/`、`work/` 忽略日志残留；未删除证据、未改基线，CI 干净检出不含这些文件。

真实 HTTP 接口走查（隔离演示副本 `outputs/aiw04/demo.db`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`）：

- 预审错误时间：`PRECHECK_V1 fail 提交：2026-11-19；要求：2026-11-18、2026-11-20、2026-11-22`。
- 旧版本验收：`4090 该成果版本已不是最新版本，请刷新后重新验收`。
- 最新版本验收：积分 4，`credited_user_ids=[4]`。
- 资料检索：本组织可见「往届迎新推文模板」，外组织结果为空。
- 脚本与日志：`outputs/aiw04/api_smoke.py`（本地忽略）。

浏览器（Playwright MCP，8000 同源 dist + `outputs/aiw04/demo.db`，`MAAS_MOCK=1`）：

- 活动详情资料区渲染；`orgadmin` 可看到「添加资料」；填写标题/链接/摘要并保存，`POST /api/resources` **200**，列表出现「往届迎新推文模板 v1」。
- **未验证**：成员提交对话框、预审错误时间展示、发布者同页验收、旧版本拒绝提示、跨组织资料不可见的前端表现；MCP 重复调用/超时后停止，未重试。
- **未验证**：真实模型预审质量、真机、390×844 移动视口、深色主题下的新卡片。

## 7. 独立审查

- 首轮（general，只读）：**0 Critical / 9 Important / 11 Suggestion**，结论阻塞。9 项均已按第 5 节处置。
- 第二轮（general，只读，仅复核修复 diff）：**0 Critical / 2 Important / 5 Suggestion**。2 项为 verify 越权与加载期盲批，已修复并补测试。
- 第三轮（general，只读）：**0 Critical / 0 Important / 4 Suggestion**，结论「不阻塞提交」。4 项 Suggestion 未在本轮修改：assignee 其他管理操作属既有契约（另立权限梳理）、组织管理员验收 UI 入口、design 措辞已同步、检索性能。
- 审查者未独立复跑完整 `run_all`、安全红线、浏览器与 CI；验证结果由主实现 Agent 与验证子代理执行。

## 8. 未完成与待回填

- 浏览器提交/预审/同页验收、真实模型、真机、移动视口、深色主题新卡片：**未验证**。
- 安全红线 B5b：本地因 `outputs/`、`work/` 被忽略日志残留失败；CI 干净检出预期通过，以对应 SHA 的 CI 为准。
- 未处理 Suggestion：资料检索全量打分、预审列表读取大 JSON、`latest_resource_versions` 50 条窗口、`resource_key` 跨组织探测、并发版本号、`total` 语义、AdminConsole 不携带版本、assignee 其他管理操作、组织 admin 验收 UI 入口。
- Git 提交：`a3632cebde608ff877cd1310a287337baa93939f`（`feat(review): 增加资料检索、成果版本与成果预审`），已推送 `origin/main`（`54440b0..a3632ce`）。
- 对应 SHA 的 CI：run [43505516305](https://github.com/shanec7825/campus-task-agent/actions/runs/43505516305) 四个 job 全部 success（Backend API/SSE integration、Backend reliability ubuntu/windows、Frontend build/voice/security）；未部署。
- 提交后的文档回填（本文件、LOG、HANDOFF）作为同阶段收口补充提交；其结果在交接中回填，不改变业务提交 `a3632ce` 的验收结论。