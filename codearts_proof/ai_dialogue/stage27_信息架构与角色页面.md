 # stage27 · AIW-08 信息架构与角色页面（2026-11-14）

## 1. 需求来源与授权

- 触发方式：每小时定时任务（`75f554a4`）。用户授权范围已扩大至 AIW-07～13；AIW-07 已于 stage26 收口，本轮接续 **AIW-08**。
- 依据：`.codeartsdoer/plans/aiw08-navigation-roles/design.md`、`task.md`；`ai-workbench/requirements.md` 的 R-01～R-07、R-18、R-21；`execution-contract.md`。
- 本轮最小增量：服务端「本人发布活动」范围；独立「我的任务」「我发布的活动」；管理者发布活动入口；侧栏/抽屉最近条目；活动字段共享区块。任务整体原子发布（AIW-11）、收费/自动验收/成就（D-01/D-02/D-03/D-05）不在本轮。

## 2. 基线与环境

| 项目 | 实际值 |
|---|---|
| 基线 HEAD | `0b325bd`（stage26 回填），与 `origin/main` 一致 |
| 工作区既有差异 | `AGENTS.md` 单步协议条款（stage26 用户要求留在工作区，本轮未提交、未修改） |
| 本轮隔离库 | `work/aiw08/demo.db`（由 `work/aiw07/demo2.db` 复制，未触碰 `backend/campus.db`） |
| 本轮服务 | `http://127.0.0.1:8020`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、`AI_DAILY_QUOTA=50`，静态托管 `frontend/dist` |
| 历史服务 | 8000 仍为 stage26 旧后端进程（未终止）；8010 零额度实例保留 |
| 浏览器工具 | Playwright CLI，`work/aiw07/runner/`（Git 忽略，仅本地验证） |

## 3. 实际执行与结果

### 3.1 实现

| 层 | 文件 | 内容 |
|---|---|---|
| 后端 | `backend/app/routers/activities.py` | `scope` 增加 `published`；条件为可见性 **且** `Activity.owner_id == 当前用户`，SQL 过滤，不取全表 |
| 测试 | `tests/backend/test_aiw08_navigation_scope.py` | 8 用例：本人/同组织另一管理员/成员/跨组织/新建即见/未登录/非法参数 |
| 前端 API | `frontend/src/api/activities.ts`、`types/models.ts` | `scope` 类型扩展；`ActivityCreatePayload.org_id` |
| 路由 | `frontend/src/router/index.ts` | `/my-tasks`、`/published-activities`、`/activities/new`；管理页守卫；页面标题 |
| 我的任务 | `frontend/src/views/TaskHall.vue` | `variant="mine"` 复用同一实现，范围锁定 `mine`，独立存储键，隐藏范围筛选 |
| 我发布的活动 | `frontend/src/views/PublishedActivitiesPage.vue` | `scope=published` 列表 + 发布活动入口 + 空/错/载入状态 |
| 发布活动 | `frontend/src/views/PublishActivityPage.vue` | 表单 + 实时预览；仅 admin/collaborator 组织可选；创建后进入详情 |
| 共享区块 | `frontend/src/components/activity/ActivityInfoSection.vue` | 活动字段唯一展示源（名称→介绍→负责人/时间/地点/组织/状态） |
| 详情 | `frontend/src/views/ActivityDetail.vue` | 头部改用共享区块；返回按来源历史回退 |
| 导航 | `frontend/src/layouts/AppLayout.vue` | 大厅/我的任务/消息/个人主页；管理者「我发布的活动」「发布者后台」；最近活动/任务各 5 条 + 查看全部；抽屉同步 |

### 3.2 门禁

| 检查 | 命令 | 结果 |
|---|---|---|
| 新增后端测试 | `python -m pytest tests/backend/test_aiw08_navigation_scope.py -q` | 8 passed |
| 活动范围回归 | 同上 + `test_aiw02_activity_scope.py` 合并进程 | 14 passed |
| 前端类型 | `npx vue-tsc --noEmit` | 无输出（通过） |
| 前端门禁 | `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh` | EXIT=0（构建 4/4、契约 25/25、语音 21/21） |
| 后端门禁 | `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | EXIT=0（7 个子脚本均「全部通过」） |
| 安全红线 | `bash tests/security/test_security_redline.sh` | 12 通过 / 1 失败（B5b 忽略目录运行产物，历史口径） |

### 3.3 浏览器验收（CLI，真实交互）

脚本：`work/aiw07/runner/aiw08_check1.mjs`（桌面 1440×900）、`aiw08_check2.mjs`（移动 390×844）、`aiw08_theme.mjs`（移动深色）。证据：`codearts_proof/reports/stage27_browser_evidence.json`、`stage27_browser_evidence_mobile.json`、`stage27_browser_evidence_theme.json`；截图 `codearts_proof/screenshots/stage27/`。

| 目标 | 实际结果 | 判定 |
|---|---|---|
| R-03 未登录直连 `/published-activities` | 回跳 `/login?redirect=/published-activities` | 通过 |
| R-02 成员「我的任务」 | 标题「我的任务」；活动 1、顶层任务 1；范围筛选不出现；侧栏最近条目与「查看全部活动」存在 | 通过 |
| R-04 查看全部 | 跳转 `/my-tasks` | 通过 |
| R-03 成员直连管理页 | 落 `/ai`；侧栏/抽屉无「我发布的活动」「发布者后台」 | 通过 |
| R-02 大厅对比 | 活动 1（跨组织不可见）、顶层任务 1（任务 2 为子任务，不重复铺满） | 通过 |
| R-04 管理者入口 | 侧栏含「我发布的活动」「发布者后台」 | 通过 |
| R-03 发布范围 | 列表只含本人活动，不含跨组织「外语角筹备」 | 通过 |
| R-07 发布活动 | 预览为空态标题；填名称与地点提交后进入 `/activities/5`，详情标题与地点一致 | 通过 |
| R-03 发布后 | 列表 3→4，含新活动 | 通过 |
| R-02 管理者我的任务 | 4 个本人发布活动出现；任务区 0（语义见 §6） | 通过（语义已记录） |
| R-21 桌面深色 | `data-theme=dark`，背景 `rgb(15,17,21)` | 通过 |
| R-04 移动抽屉 | 菜单按钮 46×44；抽屉项最小高度 44；含我的任务、我发布的活动、最近条目、查看全部 | 通过 |
| R-21 移动我的任务 | 390×844：`scrollWidth=390`、无横向溢出；底部四项文字完整 | 通过 |
| R-21 移动深色 | `data-theme=dark` | 通过 |

## 4. 发现的问题与处置

| 编号 | 现象 | 处置 |
|---|---|---|
| S27-I01 | 首次测试断言非法 `scope` 返回 HTTP 422，实际为项目统一口径 HTTP 200 + code=4001 | 修正测试断言，保留「非法参数被拒」语义；重跑 8 passed |
| S27-I02 | 8000 端口仍是 stage26 旧后端进程，`scope=published` 被旧代码按非法参数拒绝，页面进入错误态 | 按纪律不终止历史进程；复制隔离库到 `work/aiw08/demo.db`，在 8020 启动新实例后重测 |
| S27-I03 | 桌面脚本首次 `before===1` 断言失败（副本库已含前次走查创建的活动） | 改为 `before>=1` 且只含本人活动；重跑通过 |
| S27-I04 | 移动深色脚本在抽屉内点击 `theme-toggle` 超时（按钮位于抽屉底部，未滚入视口） | 新增 `aiw08_theme.mjs`，先 `scrollIntoViewIfNeeded` 再点击，通过 |
| S27-I05 | 走查在 8000 与 8020 各创建了 1 条「AIW-08 桌面走查活动」 | 仅存在于 Git 忽略的本地库，不进入提交与结论 |
| S27-I06 | 审查 I-1：`TaskDetail.vue` 返回仍硬编码 `/tasks`，从「我的任务」进入详情后丢失来源与筛选 | 改为 `history.state.back` + 站内白名单回退，否则落大厅；`stage27_browser_evidence_fixes.json` 的 R-02 用例通过 |
| S27-I07 | 审查 I-2：CI 逐文件登记 pytest，新套件未纳入，`run_all` 也不含 pytest 用例 | `.github/workflows/ci.yml` 新增 AIW-08 步骤（PyYAML 实测 12 steps、末项即该套件）；本地复跑 8 passed。**真实 CI 尚未运行**，提交推送后再核对 |
| S27-I08 | 审查 I-3：`ActivityDetail` 回退目标无站内校验、按钮文案固定「返回事务列表」 | 同白名单回退，文案改「返回列表」；R-07 用例返回 `/published-activities` |
| S27-I09 | 审查 Suggestion：时间区间缺一端显示「未设置 至 X」、`titleTag` 过宽、详情残留死代码 | 拆为「举办开始」「截止」两项；`titleTag` 收窄为 `'h1'|'h2'|'h3'`；删除 `activityStatusText` 与详情头部死样式；design 契约文本同步 |

## 5. 独立审查

- 审查者：独立 Review Agent（只读，读取需求、diff、门禁与浏览器证据）。
- 第一轮：**0 Critical / 3 Important / 10 Suggestion**。Important：① 任务详情返回硬编码；② CI 未登记新测试、`run_all` 不执行 pytest；③ 活动详情回退目标无校验、文案固定。已确认无问题的点包括：`scope=published` 为 SQL 条件叠加可见性、published ⊆ mine、未登录/非法参数口径、路由守卫与 `canAdmin` 一致、最近条目复用权限摘要、`variant="mine"` 锁范围与存储键分离、发布页预览同源、无 `v-html`、共享区块无新增 hex 或 12px。
- 第一轮处置：三条 Important 全部修复（S27-I06～I08），并顺带处理时间字段、`titleTag`、死代码与契约文本（S27-I09）。
- 第二轮（只复核修复 diff 与未关闭项）：**0 Critical / 0 Important / 15 Suggestion**，三条 Important 全部闭环；剩余为建议项，含 `isInternalBack` 两处重复、最近条目仅挂载时拉取、两处「查看全部」同跳 `/my-tasks`、无障碍分组语义、`POST /api/activities` 无 org_id 时属既有契约口径、测试反例缺口、证据 id 映射与 HANDOFF 待更新。
- 结论：审查在两轮内收敛，无未关闭 Critical / Important；剩余建议项不阻断本阶段增量，转入后续阶段或记录为已知限制。

## 6. 未完成 / 未验证

- 「我的任务」任务区按既有 `my_task_condition`（发布者/受派/报名通过）过滤；本人发布活动下的他人任务需进入活动详情查看。活动负责人代管任务是否纳入任务区属后续语义扩展，本轮不改 AIW-02 冻结契约。
- 返回来源回归已覆盖「我发布的活动 → 活动详情」「我的任务 → 任务详情」；直开深链（`history.state.back` 为空 → 回大厅）与「大厅 → 详情 → 大厅」未单独写浏览器用例，保持未实测口径。
- 真机、真实模型、部署未验证；本轮浏览器为桌面 1440×900 与移动模拟 390×844，均为 mock 后端。
- 真实 CI 未运行（截至本地收口）；提交推送后按完整 SHA 核对，不把本地 YAML 解析当作 CI 通过。
- 安全红线 B5b 为忽略目录运行产物，本地口径失败；未修改检查规则或删除证据。

## 7. 提交与 CI

- 提交与 CI：完成后回填。

## 8. 并发写入者与工具归属

- 本轮开工核对：工作区仅 `AGENTS.md` 一处 stage26 遗留差异，最后修改早于本轮，无其他会话写入迹象。
- 8000/8010 为 stage26 遗留演示服务，本轮未终止、未改写其数据结论；本轮浏览器证据全部来自 8020 + `work/aiw08/demo.db`。
- 浏览器工具为本地 Playwright CLI，未使用 MCP；结果不写成 MCP 产出。