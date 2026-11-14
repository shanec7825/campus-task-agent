# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai）。当前计划 `v1-baseline`（本地）：按用户《校园任务助手：功能需求整理（V1）》拆为 S1～S6，每阶段一次提交 + 推送 + CI，最后部署验收。
> **stage40（S1 活动 + 多任务整批原子发布）已在本地完成并通过独立审查修复**；提交/推送/CI 状态以回填提交为准（本行先记为「未提交」）。
> 上一轮已完成 AIW-14 r1/r2/r4、AIW-09 历史增量、AIW-10 文件与预审、AIW-12 额度并发、AIW-13 收口，提交 `15e7e48`，CI `43592712459` 四 job success；未部署。
> AIW-10 可执行增量已完成（预审资料版本 + 过期验收拒绝）；附件上传/解析仍按 D-04 挂起。
> stage38 已收口：侧栏初始化请求复测 25/25 正常；后台验收补过期预审标记与禁用，契约 38/38、浏览器 18/18。
> stage39 已完成：全局壳层（图标折叠/最近活动·最近聊天/New chat 发布/右上搜索折叠）、AI 三栏右通知与归档箱、全局悬浮输入三态、成果文件上传/下载（TXT/MD/PDF/DOCX ≤10MB）、成就空窗；契约 43/43、浏览器 42/42、后端 run_all EXIT=0。
> AIW-13 可执行部分已完成（视觉收口、门禁、角色与 1440/390 场景 24/24）；真机/真实模型/人工晚会链路按 D-06/D-07 保持待验收。

## 1. 当前事实与授权

- 分支 `main`，上一提交 `15e7e48895068a339776143955c8469c91429327`（CI `43592712459` 四 job success）。stage40 改动当前在本地工作区，尚未提交。
- 本轮用户授权：按用户 V1 需求连续推进 S1 → S6，每阶段验证、独立审查、留痕后提交并推送，检查对应 SHA 的 CI；**最后阶段做部署验收**。部署目标（远程主机/本地生产模式）在 S6 开工前确认；不得用旧 CI 结果代替本次。
- AIW-11 整个取消的决定继续有效；stage40 只按 V1 P0-1 恢复「整批原子发布」，不恢复其自动推荐、业务动作卡等能力。
- 缺 D-04（文件格式）、D-05（成就规则）、D-06（真机/真实模型）时只挂起直接相关子任务。

## 2. 先读这些实际文件

1. [AGENTS](../AGENTS.md)、[记录规则](DEVELOPMENT_RECORDS.md)、[浏览器单步协议](BROWSER_VALIDATION.md)。
2. 本地 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)、[需求](../.codeartsdoer/plans/ai-workbench/requirements.md)、[共同约束](../.codeartsdoer/plans/ai-workbench/execution-contract.md)、[决策](../.codeartsdoer/plans/ai-workbench/decisions.md)、[矩阵](../.codeartsdoer/plans/ai-workbench/acceptance-matrix.md)。
3. 阶段计划：V1 基线 [roadmap](../.codeartsdoer/plans/v1-baseline/roadmap.md)、[S1 design](../.codeartsdoer/plans/v1-baseline/s1-batch-publish/design.md) / [S1 task](../.codeartsdoer/plans/v1-baseline/s1-batch-publish/task.md)、[S2 design](../.codeartsdoer/plans/v1-baseline/s2-submission-policy/design.md) / [S2 task](../.codeartsdoer/plans/v1-baseline/s2-submission-policy/task.md)；历史计划：[AIW-14 design §8/§9](../.codeartsdoer/plans/aiw14-workbench-library-search/design.md)、[UI r4](../.codeartsdoer/plans/aiw14-workbench-library-search/ui-reference-r4.md)、[AIW-09 design §5](../.codeartsdoer/plans/aiw09-context-voice/design.md)、[AIW-12 design §4](../.codeartsdoer/plans/aiw12-assets-quota/design.md)、各自 `task.md`。
4. 阶段记录：[stage40 V1-S1 整批发布](../codearts_proof/ai_dialogue/stage40_活动与多任务整批发布.md)、[stage32 AIW-14 实施](../codearts_proof/ai_dialogue/stage32_AIW-14浏览与Library实施.md)、[stage33 AIW-09 历史](../codearts_proof/ai_dialogue/stage33_AIW-09历史会话.md)、[stage34 AIW-12 额度](../codearts_proof/ai_dialogue/stage34_AIW-12额度并发.md)、[stage35 AIW-14 r4](../codearts_proof/ai_dialogue/stage35_AIW-14r4头像短卡与分工表.md)、[stage36 AIW-10 预审资料版本](../codearts_proof/ai_dialogue/stage36_AIW-10预审资料版本.md)、[stage37 AIW-13 产品级验收](../codearts_proof/ai_dialogue/stage37_AIW-13产品级验收.md)、[stage38 AIW-13 遗留缺陷收口](../codearts_proof/ai_dialogue/stage38_AIW-13遗留缺陷收口.md)、[stage39 全局壳层与成果文件](../codearts_proof/ai_dialogue/stage39_全局壳层AI三栏与成果文件.md)。

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

## 4. 问题与待条件

- **AIW-14 已完成 r1/r2/r4**；r4 的浏览器证据为模拟视口（1440/390），深色主题与真机未在 r4 重测。
- **V1 基线进度**：S1 已完成本地实现与审查；S2 起为待实施（契约已冻结 S1/S2）。P0 剩余：成果提交策略（S2）、组织资料检索开关（S3）；P1：文档解析（S3）、个人 Library 引用（S4）、AI 任务查询增强（S4）、AI 任务树草案（S5）；P2：文件正文预审、优秀成果归档（S5）。
- **AIW-10 文件链路（stage39）**：成果文件上传/下载与 TXT/MD 预审取文已落地；PDF/DOCX 仍只存储不解析；未引入解析依赖；Library 仍只存链接。
- **AIW-12 成就空窗**：D-05 规则未确认；未新增规则、展示或发奖写路径。
- **AIW-13 可执行部分完成**：令牌化、角色/模拟视口、过期预审 UI、390 完整成果链路、移动搜索/Library/历史与键盘焦点已验；真机语音/安全区/键盘、固定真实模型评测、人工晚会链路与录屏未验；部署/提交未授权。
- 遗留观察：整页直连侧栏请求已复测 25/25 正常（原监听路径口径错误）；搜索前端分页 UI 数据量不足未验；关闭详情滚动恢复在数据不足时 N/A；`resetFilters` 未清选中（低）。
- 未验证：后台验收在「预审状态加载失败/延迟」时退回可用的浏览器注入场景（仅表达式与提示断言）。
- 安全红线本轮未重跑；历史 B5b 失败事实保留。真实模型、真机、部署均未验证。

## 5. 本轮交付状态与下一次最短步骤

- stage40（S1）本地完成并已通过独立审查修复；提交 SHA、推送与对应 CI 在紧随其后的回填提交中登记（本段写作时尚未提交，不预填结果）。上一轮 `15e7e48` 的 CI `43592712459` 四 job success 只代表上一轮。历史证据：`codearts_proof/reports/aiw14-browser.md`、`codearts_proof/screenshots/aiw14-*.png`、`codearts_proof/reviews/stage30_review_r{1,2,3}.md`、`stage31_quota_review.md`、`work/aiw14/browse/{verify-browse-r4.cjs,r4-report.json}`、`work/aiw14/backend-runall-aiw10-final.log`（本地忽略）。
- 下一次最短可执行步骤：按 `.codeartsdoer/plans/v1-baseline/s2-submission-policy/task.md` 派工 S2（后端 `C-SUBMISSION-POLICY@1` + 前端表单），完成后同样验证、独立审查、提交推送并检查 CI；S3 起在开工前补 design/task。
- 本地运行：后端 `python -m uvicorn app.main:app --port 8000`（`backend/`），前端 `npm run dev`（`frontend/`，5173）；当前两端口均在运行，迁移列已补齐。
- 回填提交只更新交接/记录，不改变代码；其自身 CI 另行跟踪。