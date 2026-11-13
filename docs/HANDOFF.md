# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage20 / AIW-02 实现与本地验证完成，提交与 CI 待回填）。这是当前状态入口，不替代历史阶段记录。交接前后都应重新核对 Git 与实际文件。

## 1. 当前基线与本轮授权

- 分支：`main`。
- 开工基线：`9ad625f725d8667f4f86cab4201708d224415a95`（stage19 文档回填）；开工时工作区干净。
- 本轮代码尚未提交；提交 SHA、推送与 CI 结果待回填。
- 本轮授权范围：AIW-02「浏览与情境助手」；不新增路由/表/依赖，不做受控业务动作、AI 额度、语音原生、依赖图谱、成果上传与自动验收。
- 本轮使用编号：留痕 **stage20**；未新增 P 编号（业务 Prompt 正文未改）。

## 2. 本轮实际变更与状态

| 对象 | 当前核对结果 | 接手规则 |
|---|---|---|
| `backend/app/services/authz.py` | 新增 `my_task_condition` 与 `APPROVED_STATUS`；任务与活动范围共用 | 不要为活动另写一套「我的任务」判定 |
| `backend/app/routers/tasks.py` | `scope=mine` 复用 `my_task_condition`；行为与原 publisher/assignee/approved 条件一致 | 不得只看 `assignee_id` |
| `backend/app/routers/activities.py` | `GET /api/activities?scope=all|mine`；`mine` 叠加 `visible_task_filter` 与我的任务条件；同一查询复用同一 CTE | 新增条件必须先过可见性；不要在路由内取全表过滤 |
| `tests/backend/test_aiw02_activity_scope.py` | 6 用例：all/mine、负责人、approved、pending 不命中、无关成员、协作者、跨组织、未登录 | 已接入 CI backend-reliability；修改范围时必须重跑 |
| `.github/workflows/ci.yml` | backend-reliability 增加 AIW-02 pytest step | 保留只读权限与既有 job |
| `frontend/src/stores/aiChat.ts` | 三种 Agent 形态共享会话与草稿；登出 epoch 拦截迟到响应 | 保留发送中不刷新、刷新失败不清空消息、失败回填输入 |
| `frontend/src/components/ai/AgentDock.vue` | 活动/任务详情底部；长条 + 微展开 + 完整页入口 | 当前活动/任务只作界面标签，不进入模型上下文 |
| `frontend/src/components/common/HoverPeek.vue` | 200ms、精确指针、Esc、焦点、触摸设备禁用、面板限高 | 快速划过与间隙场景仍需浏览器复验 |
| `frontend/src/views/TaskHall.vue` | 任务区含活动下第一层任务与独立任务；活动 `scope`；筛选/滚动恢复；requestId 防竞态 | 子任务不铺满；活动与任务范围必须一致 |
| `frontend/src/layouts/AppLayout.vue` | 手机菜单按钮与左侧抽屉；退出清空 AI 会话与 `cta_hall_view` | 底部四项导航保留；44×44 |
| `frontend/src/views/AiConsole.vue` | 改用 `aiChat` store；通知卡与 mock 提示保留 | 刷新按钮 force=true |

## 3. 验证、审查与提交状态

- 后端（隔离临时库）：`test_aiw02_activity_scope.py` **6 个测试函数 / 8 类场景，6 passed（最终代码）**；活动层级 **13**、活动流程 **8**、认证权限 **47**、可靠性 **11** passed；`tests/backend/run_all.sh` **EXIT=0、1412 条 PASS**（`backend-runall-final.log`；首次复跑因 `tasks.py` 语法错误失败，已定位修复）。
- 前端：`npm run typecheck` **EXIT=0**、`npm run build` **EXIT=0**；最终代码 `tests/frontend/run_all.sh` **EXIT=0**（构建 4/4、契约 25/25、语音 21/21，`frontend-runall-final.log`）。
- 独立审查：首轮 **0 Critical / 5 Important / 8 Suggestions**；第二轮 **0 Critical / 3 Important**；第三轮 **0 Critical / 2 Important**（加载期离开可能滚动新页面、聚合门禁早于最后后端改动），已处置并完成最终回归；按最多三轮未开第四轮，最后修复未经独立复核。**端到端浏览器验收未完成**（返回位置、AgentDock、手机抽屉、深色主题、真实模型）；不把未验证写成通过。
- 浏览器（Playwright MCP，8000 同源 dist + phase2 demo.db，`MAAS_MOCK=1`）：`/ai` 默认入口、通知卡、历史 mock 会话与来源；`/tasks` 活动下任务与「所属活动」可见；悬浮预览 100ms=0 / 320ms=1 / 离开=0。MCP 重复调用后停止，未产出阶段截图。
- 归档证据：[stage20 验证记录](../codearts_proof/reports/stage20_验证记录.md)、[case4 排错实例](../codearts_proof/debug/case4_活动范围递归CTE同名冲突.md)。
- **提交/推送/CI**：未执行；不得提前写成完成。

## 4. 计划阅读入口

1. [AGENTS.md](../AGENTS.md)：长期约束与开工必读。
2. [开发记录规则](DEVELOPMENT_RECORDS.md)：编号、事实来源与写入约束。
3. 本地总计划 [roadmap](../.codeartsdoer/plans/ai-workbench/roadmap.md)。
4. 本轮计划 [design.md](../.codeartsdoer/plans/aiw02-browse-context/design.md) 与 [task.md](../.codeartsdoer/plans/aiw02-browse-context/task.md)：冻结 6 份契约。
5. [stage20 过程与验证](../codearts_proof/ai_dialogue/stage20_浏览与情境助手.md)、[stage20 验证记录](../codearts_proof/reports/stage20_验证记录.md)、[浏览器走查](../outputs/aiw02/walkthrough.md)（本地忽略）。
6. 上一阶段 [stage19 过程](../codearts_proof/ai_dialogue/stage19_统一入口与只读问答.md)。

本地计划缺失时，先告知用户并请求提供文件或明确新的设计依据；不要从历史 HTML、旧 phase2 计划或文件名推导完整需求。

## 5. 下一步

- 先完成 stage20 的审查复核、必要的端到端浏览器复验、提交/推送与对应 CI 回填；CI 通过后才标记 AIW-02 完成。
- AIW-02 完成后，下一阶段为 **AIW-03：真实任务全景**（多前置依赖、时间区间、活动与任务共用图谱、发布页共享内容区块）。开始前重新扫描 stage 编号（当前最大 20）并读取本地总计划。
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