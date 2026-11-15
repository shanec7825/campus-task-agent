# 当前开发交接

> 更新日期：2026-11-15（Asia/Shanghai）。当前计划 `v1-ui-detail-refine`（本地）：详情页信息架构与视觉一致性（图标/比例/布局 + 活动与任务详情），只改前端展示层。
> **stage40（S1 活动 + 多任务整批原子发布）已完成并推送 `54bc81e`**，CI `43594367179` success。
> **stage43（V1 S5 预审正文/成果归档/AI 任务树草案）已提交 `41fe2ac`**，CI `43600000028` success；同时修复 stage42 CI 失败（表基线 24→26）。
> **stage44（UI 壳层改版、Library 收敛与 AI 上下文）已提交 `85805ed` 并推送**，CI `43707123572` success；契约 **51/51**、`vue-tsc` 0 error、`vite build` 成功、`test_v1_avatar.py` **12 passed**。
> **stage45（详情页信息架构与视觉一致性）已完成并仅本地落盘（未提交）**：统一图标 1.6 线宽与 14/16/20/24 尺寸、详情页 1200px + 1fr/304px 双栏、活动详情「摘要+3 指标+分组任务+属性侧栏」、任务详情「头部+属性侧栏+分区主区」、卡片等高；契约 **57/57**、`vue-tsc` EXIT=0、`npm run build` EXIT=0；独立审查 0 Critical/5 Important 全部修复，6 条 Suggestion 未处置。浏览器验收已完成：1440 活动/任务详情 `840px 304px`、390×844 单列 `343.2px`、两档横向溢出 **0**、按钮 44px，5 张截图在 `codearts_proof/screenshots/stage45/`；验收中修 4 项（全站时间去 `T`、组织名回退、未分配头像、`0/0` 子任务噪音）。计划 `.codeartsdoer/plans/v1-ui-detail-refine/`（本地忽略）。
> **S6 部署验收：本机生产形态 14/14 通过**（[报告](../codearts_proof/reports/v1-deploy-acceptance.md)）；远程部署未做（无目标与凭据）。
> stage42（S3+S4）已推送 `504f1a5`，其 CI `43598431620` 曾失败，已由 `41fe2ac` 修复；S1 `54bc81e`、S2 `1584e9d` CI success。
> 上一轮已完成 AIW-14 r1/r2/r4、AIW-09 历史增量、AIW-10 文件与预审、AIW-12 额度并发、AIW-13 收口，提交 `15e7e48`，CI `43592712459` 四 job success；未部署。
> AIW-10 可执行增量已完成（预审资料版本 + 过期验收拒绝）；附件上传/解析仍按 D-04 挂起。
> stage38 已收口：侧栏初始化请求复测 25/25 正常；后台验收补过期预审标记与禁用，契约 38/38、浏览器 18/18。
> stage39 已完成：全局壳层（图标折叠/最近活动·最近聊天/New chat 发布/右上搜索折叠）、AI 三栏右通知与归档箱、全局悬浮输入三态、成果文件上传/下载（TXT/MD/PDF/DOCX ≤10MB）、成就空窗；契约 43/43、浏览器 42/42、后端 run_all EXIT=0。
> AIW-13 可执行部分已完成（视觉收口、门禁、角色与 1440/390 场景 24/24）；真机/真实模型/人工晚会链路按 D-06/D-07 保持待验收。

## 1. 当前事实与授权

- 分支 `main`，HEAD `85805ed`；stage45 的 24 个代码修改（含验收后 18 个时间格式化文件）+ 3 个新增组件（`frontend/src/components/detail/DetailHeader.vue`、`frontend/src/components/detail/PropertyList.vue`、`frontend/src/components/task/TaskGroupList.vue`）+ 5 张浏览器截图（`codearts_proof/screenshots/stage45/`）+ 2 份阶段文档修改（`codearts_proof/LOG.md`、本文件）+ 2 份新增记录（`codearts_proof/ai_dialogue/stage45_详情页信息架构与视觉一致性.md`、`codearts_proof/prompts/agent_team_启动指令/2026-11-15_stage45_UI详情页优化_用户原文摘录.md`）仍在工作区，**未提交**（需用户针对提交动作单独授权）。上一阶段提交 `85805ed`（stage44，CI `43707123572` success）。
- 本轮用户授权：按用户 V1 需求连续推进 S1 → S6，每阶段验证、独立审查、留痕后提交并推送，检查对应 SHA 的 CI；**最后阶段做部署验收**。部署目标（远程主机/本地生产模式）在 S6 开工前确认；不得用旧 CI 结果代替本次。
- AIW-11 整个取消的决定继续有效；stage40 只按 V1 P0-1 恢复「整批原子发布」，不恢复其自动推荐、业务动作卡等能力。
- 缺 D-04（文件格式）、D-05（成就规则）、D-06（真机/真实模型）时只挂起直接相关子任务。

## 2. 先读这些实际文件

1. [AGENTS](../AGENTS.md)、[记录规则](DEVELOPMENT_RECORDS.md)、[浏览器单步协议](BROWSER_VALIDATION.md)。
2. 本地 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)、[需求](../.codeartsdoer/plans/ai-workbench/requirements.md)、[共同约束](../.codeartsdoer/plans/ai-workbench/execution-contract.md)、[决策](../.codeartsdoer/plans/ai-workbench/decisions.md)、[矩阵](../.codeartsdoer/plans/ai-workbench/acceptance-matrix.md)。
3. 阶段计划：V1 基线 [roadmap](../.codeartsdoer/plans/v1-baseline/roadmap.md)、[S1 design](../.codeartsdoer/plans/v1-baseline/s1-batch-publish/design.md) / [S1 task](../.codeartsdoer/plans/v1-baseline/s1-batch-publish/task.md)、[S2 design](../.codeartsdoer/plans/v1-baseline/s2-submission-policy/design.md) / [S2 task](../.codeartsdoer/plans/v1-baseline/s2-submission-policy/task.md)；历史计划：[AIW-14 design §8/§9](../.codeartsdoer/plans/aiw14-workbench-library-search/design.md)、[UI r4](../.codeartsdoer/plans/aiw14-workbench-library-search/ui-reference-r4.md)、[AIW-09 design §5](../.codeartsdoer/plans/aiw09-context-voice/design.md)、[AIW-12 design §4](../.codeartsdoer/plans/aiw12-assets-quota/design.md)、各自 `task.md`。
4. 阶段记录：[stage41 V1-S2 成果要求](../codearts_proof/ai_dialogue/stage41_成果提交策略与验收要求.md)、[stage40 V1-S1 整批发布](../codearts_proof/ai_dialogue/stage40_活动与多任务整批发布.md)、[stage32 AIW-14 实施](../codearts_proof/ai_dialogue/stage32_AIW-14浏览与Library实施.md)、[stage33 AIW-09 历史](../codearts_proof/ai_dialogue/stage33_AIW-09历史会话.md)、[stage34 AIW-12 额度](../codearts_proof/ai_dialogue/stage34_AIW-12额度并发.md)、[stage35 AIW-14 r4](../codearts_proof/ai_dialogue/stage35_AIW-14r4头像短卡与分工表.md)、[stage36 AIW-10 预审资料版本](../codearts_proof/ai_dialogue/stage36_AIW-10预审资料版本.md)、[stage37 AIW-13 产品级验收](../codearts_proof/ai_dialogue/stage37_AIW-13产品级验收.md)、[stage38 AIW-13 遗留缺陷收口](../codearts_proof/ai_dialogue/stage38_AIW-13遗留缺陷收口.md)、[stage39 全局壳层与成果文件](../codearts_proof/ai_dialogue/stage39_全局壳层AI三栏与成果文件.md)。

详细计划被 Git 忽略，仅本地。换机器/worktree 缺计划时报告，不用摘要冒充完整契约。

## 3. 已完成与验证（本轮实跑）

1. **AIW-14 r1/r2（stage32）**
   - 分组 SVG 图标侧栏、搜索入口、Library 路由与私有链接（GET/POST/PATCH，无 DELETE，owner 只按会话）、最近活动/任务、AI 历史真实列表。
   - 大厅/我的任务双段胶囊 `?type=`、三列短卡、选中左 1 右 2 分栏、`selectedType/selectedId` 深链与滚动恢复、返回不堆历史。
   - HoverPeek 联合区：8px 间隙桥接 + 120ms 关闭缓冲；真实浏览器先复现失败（2/5）后 16/16。
   - mine 搜索（活动/任务分组、跨组织不返回）、`cta_search_return` 恢复关键词。
   - 门禁：后端 `run_all` EXIT=0（1446 PASS，24 表）；前端 `run_all` EXIT=0（构建 4/4、契约 32/32、语音 21/21）。
   - 浏览器：首轮 152 条 149 PASS；修复后 AC-18（侧栏叠压）与 AC-22（搜索返回）复验 PASS。
   - 审查：r1 0 Critical/7 Important；r2 关闭 5/7；r3 0C/0 阻塞（N-6 在 r3 后修复，未开第四轮）。
2. **AIW-09 历史（stage33）**
   - 列表 `offset` 分页 + `total`；侧栏最近 5 条；AI 完整页历史抽屉（最近/全部/加载更多/失败重试）；旧会话续聊、新对话、`?conversation=` 刷新恢复；同 scope 多会话与晚到回包按 conversationKey+epoch 隔离；读历史不调模型/不扣额度。
   - `test_aiw09_history.py` 通过；浏览器历史项通过，抽屉点击会话 URL 未写回缺陷已修，R3 定向复验 13/13 PASS。
3. **AIW-12 额度并发（stage34）**
   - `ai_usage_ledger` 增加 `pending` 预留，`BEGIN IMMEDIATE` 内原子统计+插入，模型调用不持锁；失败对称释放；同键异内容/异作用域 4090；超时只清本用户 10 分钟前的 pending；`used` 含 pending、`items` 只列 settled。
   - 并发测试 6 passed；`test_aiw05_proactive_quota.py` 旧二次检查用例按授权改为「预留争用」，合并 18 passed；收口后后端 `run_all` 再跑 EXIT=0（1446 PASS）。
   - 审查第 1 轮曾判不通过（1 Critical/4 Important），已全部处置（C-1 用例改写、I-1 重放校验、I-2 释放事务、I-3 口径）。
4. **AIW-14 r4（stage35）**
   - 浏览活动/任务卡改为柔和彩色短矩形 + 32px 头像主行；活动树节点补 `start_time/assignees/completed_children/total_children/activity_id`。
   - 新增共用 `ActivityTaskTable`：活动详情、浏览右栏、发布者后台复用；父子展开、子任务徽标、`router-link` 进详情、`#meta` 摘要（后台恢复分配方式/报名/积分/催办）。
   - 活动详情标题区切换器走 `router.assign` 等价的 `router.replace`，保留 `from/q`、切换清空展开与资料检索、晚到响应按 `requestSeq` 丢弃。
   - 门禁：新测试 5 passed、活动回归 21 passed、后端 `run_all` EXIT=0、前端 `run_all` ALL PASS（构建 4/4、契约 37/37、语音 21/21）、`vue-tsc` 0 error；r4 浏览器 **41/41 PASS**（1440/390，含后台父子组装与筛选）。
   - 独立审查 0 Critical / 3 Important 全部修复后复跑门禁；未开第二轮独立复审。
5. **AIW-10 可执行增量（stage36）**
   - 预审 digest 纳入被引用资料版本；`submission_prechecks.resource_snapshot` 幂等迁移（不回填）；资料视角固定为成果提交者。
   - `pass=true` 时过期预审返回 4090，校验先于成员/积分/通知写入；退回与无预审保持兼容。
   - 任务详情过期标签改「要求或资料已变化」，待验收「通过」在 stale 时 disabled。
   - 门禁：`test_aiw10_precheck_version.py` **8 passed**、资料/整体验收回归 **15 passed / 1 skipped**、前端 ALL PASS、`vue-tsc` 0 error；后端 `run_all` EXIT=0 但不覆盖 pytest，不作为本条证据。
   - 独立审查 0 Critical / 3 Important（I1 证据口径、I2/I3 回归缺口）全部处置；9 条 Suggestion 记录未处置。
6. **AIW-13 可执行验收（stage37）**
   - T13-00 两处令牌化：`UserAvatar` xs 字号回 `--app-font-aux`、`AppLayout` 徽标 `#fff` → `--el-color-white`。
   - T13-04/05：未登录/成员/发布者角色、活动任务表与依赖图、表格链接应用内跳转与返回、搜索保留 `q`、深浅主题、390 四页无溢出、AI 额度 **24/24**；AC-09 过期预审 UI **15/15**；390 报名→审批→提交→退回→重提→验收链路 **15/15**；390 搜索/Library/历史与键盘 **11/11**。
   - 安全红线 12 通过 / 1 失败（B5b 仅 `.codeartsdoer/temp` 工具日志残留），未放宽门禁。
   - 待条件：真机（D-06）、真实模型评测（D-06）、人工晚会链路与录屏（T13-08）、提交/CI（T13-11）与部署（D-07）。
7. **stage38 遗留缺陷收口**
   - 「整页直连侧栏最近/AI 历史不请求」复测：5 路由 × 5 次整页直连 25/25 均发起（此前监听路径写错），当前不可复现。
   - 后台验收对话框按成员最新成果 `precheck.stale` 显示「预审已过期」并禁用「确认通过」，加载中禁用、失败提示、迟到响应按 `verifyStaleSeq` 丢弃；退回不受影响。
   - 门禁：契约 **38/38**（新增 ㊳，含空转防护）、前端 run_all **ALL PASS**、typecheck/build EXIT=0、浏览器 **18/18**。
   - 独立审查 1 Critical/2 Important 全部关闭，第二轮复核「可提交」。
8. **stage39 全局壳层 / AI 三栏 / 归档 / 成果文件**
   - 壳层：折叠仅图标、右上搜索/折叠、New chat 发布、最近活动/最近聊天、归档通知导航；`/messages` 重定向 AI 页。
   - AI：左问答 + 右通知/归档（`?panel=archive`）；归档幂等、未读数不含归档；删除「查看全部消息」。
   - 全局悬浮输入：小条 → `^` 中框（部分问答）→ AI 页；任意页提问与语音；非 AI 页显示。
   - 成果文件：JSON base64 上传（TXT/MD/PDF/DOCX ≤10MB）、提交者/审核者下载、TXT/MD 参与预审、PDF/DOCX 仅存储。
   - 门禁：后端 3+4+15 passed、前端 ALL PASS（契约 43/43）、浏览器 **42/42**、后端 `run_all` EXIT=0（1446 PASS）。
   - 首轮审查 3 Critical/15 Important 已修复并复跑；**第二轮复核请求后审查会话未返回新结论，最后一批修复未经独立复核**（如实登记）。移动端通知抽屉改为堆叠、MIME 非双检等登记未处置。
   - 成就保持空窗（D-05 未确认）。

9. **stage40 V1-S1 活动 + 多任务整批原子发布**
   - 新增 `POST /api/activities/publish-batch`（`C-BATCH-PUBLISH@1`）：活动 + 0..N 任务一次提交；批内 `key` 声明依赖与一层父任务；全部校验前置、单次 commit、失败整体回滚；`parent_id` 传值按 4001 拒绝。
   - 发布页新增多任务编辑区（增删行、依赖同层候选、父任务归一、成环/跨层/时间校验、`saving` 防重复提交、成功跳活动详情）。
   - commit 后复用 `_index_task_safe` 写知识库；索引失败不影响已发布结果。
   - 门禁：新测试 **12 passed**（含 flush 后异常回滚、KB 索引、边界 4001/4040）、活动/图/流程回归 **13+13+8 passed**、`vue-tsc` 0 error、build 成功、契约 **43/43**。
   - 独立审查 1 Critical / 2 Important 全部修复；9 条 Suggestion 记录未处置；未开第二轮复核。

10. **stage41 V1-S2 成果提交方式与验收要求**
   - `tasks.extras.acceptance`（`C-SUBMISSION-POLICY@1`）：提交方式 text/link/file、允许扩展名、AI 预审开关；未配置任务保持宽松。
   - 后端在创建/编辑/提交/上传四处强制；批量发布写库前归一；PATCH extras 改合并语义。
   - 前端：发布表单「成果要求」区块、任务详情按策略渲染（空扩展名回退四类）、后台任务操作区「成果要求」编辑对话框。
   - CI 新增 `test_v1_batch_publish.py` + `test_v1_submission_policy.py` 步骤。
   - 门禁：**10 + 14 + 4 + 1 passed**、`vue-tsc` 0 error、build 成功、契约 **43/43**。
   - 审查 1 Critical / 3 Important 全部修复；8 条 Suggestion 记录未处置；未开第二轮独立复审。

11. **stage42 V1-S3 + S4 组织资料库 / 文档解析 / AI 检索 / 引用收藏**
   - S3：`org_resources`（PDF/DOCX/TXT/MD 上传、正文解析、`allow_student_ai` 默认关闭、归档、全文检索）；新增 `pypdf` 依赖；解析与上传资源上限（页数/字符/解压比/base64 长度）。
   - S4：`library_refs` 引用式收藏（不复制文件，撤回后不可下载）；`/api/library/refs`；下载鉴权失败统一 4040；AI 任务上下文按意图检索并带 SOP/验收/最新成果（非审阅者只见本人成果）；doc 上下文与 citation，回答后自动收藏。
   - 前端：Library 组织资料区（开关+免责文案）与「我的引用资料」区；AI 来源标签为「任务 / 资料」二值，doc 可跳 Library。
   - CI：新增 4 个独立测试 step（document parse / org library / library refs / AI context）。
   - 门禁：**14 + 10 + 26 + 10 + 7 + 14 passed**、`vue-tsc` 0 error、build 成功、契约 **45/45**。
   - 审查：S3 1 Critical/3 Important、S4 1 Critical/5 Important 全部修复；Suggestion 记录未处置；未开第二轮独立复审。
   - 因共用文件无法干净拆分，S3 与 S4 合并为一次提交（偏离「一阶段一提交」，已登记）。

12. **stage43 V1-S5 预审正文 / 成果归档 / AI 任务树草案**
   - 预审取文扩到 PDF/DOCX（`document_service` 上限继承），AI payload 截断 8000，规则仍用全量。
   - `POST /api/org-resources/from-submission`：归档等同成果审核（`require_task_review` 窄口径），仅最新且 verified，`allow_student_ai=0`，重复归档生成新行。
   - `POST /api/ai/task-draft`：只读草案，资料检索限可管理组织，真实模型 60s/3 次限流，重复 key/环/跨层/多层父被丢弃并记 warning，剩余草案可直接整批发布。
   - 前端：发布页 AI 草案面板（不自动提交）、后台已验收成员持久归档入口。
   - 门禁：archive_precheck **8** + task_draft **14** + ai_context 14 + org_library 10 + batch 14 + policy 10 passed；`run_all.sh` 全流程通过；`vue-tsc` 0 error、build 成功、契约 **46/46**。
   - 审查 1 Critical / 6 Important 全部修复；Suggestion 记录未处置；未开第二轮独立复审。
   - 同时修复 stage42 CI 失败：表基线 24→26（真实新增 `org_resources`/`library_refs`，非放宽）。

## 4. 问题与待条件

- **AIW-14 已完成 r1/r2/r4**；r4 的浏览器证据为模拟视口（1440/390），深色主题与真机未在 r4 重测。
- **V1 基线进度**：S1 `54bc81e`、S2 `1584e9d`、S5 `41fe2ac` CI success；S3+S4 `504f1a5` 的 CI 曾失败（表基线）已由 `41fe2ac` 修复。S6 本机生产形态部署验收 **14/14** 通过（[报告](../codearts_proof/reports/v1-deploy-acceptance.md)）；远程部署未做。P0 三项、P1 四项、P2 两项均已实现。
- **已知限制**：AI 智能模式发布与活动整批发布页不提供成果要求控件；`saveLibraryRef` 无 UI 入口（AI 自动收藏为主）；检索为关键词打分非向量；`kind` 为 task/doc 二值；草案真实模型未接额度账本（仅进程内限流）；归档非幂等。
- **文件与解析**：成果文件上传/下载（TXT/MD/PDF/DOCX ≤10MB）与 PDF/DOCX 正文预审已落地（`pypdf` 纯 Python，DOCX 零依赖）；组织资料库 `org_resources` 支持同一批格式的解析与检索；OCR 仍未做。
- **AIW-12 成就空窗**：D-05 规则未确认；未新增规则、展示或发奖写路径。
- **AIW-13 可执行部分完成**：令牌化、角色/模拟视口、过期预审 UI、390 完整成果链路、移动搜索/Library/历史与键盘焦点已验；真机语音/安全区/键盘、固定真实模型评测、人工晚会链路与录屏未验；部署/提交未授权。
- 遗留观察：整页直连侧栏请求已复测 25/25 正常（原监听路径口径错误）；搜索前端分页 UI 数据量不足未验；关闭详情滚动恢复在数据不足时 N/A；`resetFilters` 未清选中（低）。
- 未验证：后台验收在「预审状态加载失败/延迟」时退回可用的浏览器注入场景（仅表达式与提示断言）。
- 安全红线本轮未重跑；历史 B5b 失败事实保留。真实模型、真机、部署均未验证。

## 5. 本轮交付状态与下一次最短步骤

- S1（`54bc81e`）、S2（`1584e9d`）、S5（`41fe2ac`）已推送且 CI success；S3+S4（`504f1a5`）CI 曾失败，已由 `41fe2ac` 修复。**S6 本机生产形态部署验收 14/14 通过**（`scripts/deploy_smoke.py`，证据 `work/deploy/smoke.json` 本地忽略 + [报告](../codearts_proof/reports/v1-deploy-acceptance.md)）。
- 下一次最短可执行步骤：如需远程部署，请提供目标主机/域名/凭据与回滚方式；否则 V1 交付范围到此收口。后续可选：浏览器手工回归（草案填入、归档入口、预审正文）、真实模型质量评测、移动端真机、OCR。
- 本地运行：后端 `python -m uvicorn app.main:app --port 8000`（`backend/`），前端 `npm run dev`（`frontend/`，5173）；当前两端口均在运行，迁移列已补齐。
- 回填提交只更新交接/记录，不改变代码；其自身 CI 另行跟踪。