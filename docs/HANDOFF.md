# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage27 / AIW-08 信息架构与角色页面）。当前结论：AIW-00～07 的实现与 CI 已通过；stage27 已完成 AIW-08 的核心增量（服务端本人发布活动范围、独立「我的任务」「我发布的活动」、管理者发布活动入口、侧栏/抽屉最近条目、活动字段共享区块），本地门禁、CLI 浏览器验证与两轮独立审查已通过；提交与对应 CI 在收口时回填。真实模型、真机与部署仍未验证，最终产品验收未完成。

## 1. 当前基线与本轮授权

- 分支：`main`；本轮基线 `0b325bdf11c1f86947d78bfa4858d3caeec53863`（stage26 回填），与 `origin/main` 一致。
- 工作区既有差异：`AGENTS.md` 的浏览器单步协议条款（stage26 用户要求保留在工作区，本轮未提交、未修改）。
- 用户授权：每小时定时任务继续推进 AIW-07～AIW-13；本轮接续 AIW-08，只做该阶段已确认范围。
- 本轮记录编号：stage27；未修改业务 Prompt，无新 P 编号。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。

## 2. 本轮产出与阅读顺序

1. [AGENTS.md](../AGENTS.md) 与 [开发记录规则](DEVELOPMENT_RECORDS.md)、[浏览器单步协议](BROWSER_VALIDATION.md)。
2. 本地总计划 [roadmap.md](../.codeartsdoer/plans/ai-workbench/roadmap.md)、[需求覆盖表](../.codeartsdoer/plans/ai-workbench/requirements.md)、[共同约束](../.codeartsdoer/plans/ai-workbench/execution-contract.md)、[待确认决策](../.codeartsdoer/plans/ai-workbench/decisions.md)、[验收矩阵](../.codeartsdoer/plans/ai-workbench/acceptance-matrix.md)。
3. 本阶段 [AIW-08 design.md](../.codeartsdoer/plans/aiw08-navigation-roles/design.md) 与 [task.md](../.codeartsdoer/plans/aiw08-navigation-roles/task.md)；下一执行入口 [AIW-09 design.md](../.codeartsdoer/plans/aiw09-context-voice/design.md) 与 [task.md](../.codeartsdoer/plans/aiw09-context-voice/task.md)。
4. [stage27 过程记录](../codearts_proof/ai_dialogue/stage27_信息架构与角色页面.md) 与 [LOG](../codearts_proof/LOG.md)。
5. 浏览器证据：[桌面](../codearts_proof/reports/stage27_browser_evidence.json)、[移动](../codearts_proof/reports/stage27_browser_evidence_mobile.json)、[主题](../codearts_proof/reports/stage27_browser_evidence_theme.json)、[修复补验](../codearts_proof/reports/stage27_browser_evidence_fixes.json)；截图 `codearts_proof/screenshots/stage27/`。

详细计划仍被 `.codeartsdoer/` 忽略，仅本地保存，未远程备份。换电脑/worktree 缺计划时先补齐，摘要不能冒充完整契约。

## 3. 已有实现与历史验证

- AIW-00～06 对应 stage18～24：活动下发布与权限、统一 AI 入口/持久问答、网格/预览/共享助手、依赖时间图、资料与文本成果版本/预审、提醒失效/人工影响卡/问答额度、完整 API 验收链路。最近业务提交 `a728788`，CI run 43532974986 四 job success。
- stage25 规划入库：`19eda9f` / CI `43553685701`；回填 `d1ceab2` / CI `43554038152`。
- stage26（AIW-07）：`f3fa0fb` / CI `43558695172`、回填 `0b325bd`，均四 job success。AC-01/03/09/14/15 与 AC-16 部分（mock）已取得 CLI 证据。
- stage27（AIW-08）本地新增：`scope=published`（SQL 叠加可见性）、`/my-tasks`（复用 TaskHall，范围锁定 mine）、`/published-activities`、`/activities/new`、`ActivityInfoSection` 共享字段区块、侧栏/抽屉最近条目（各 5 条 + 查看全部）；CI 登记 `test_aiw08_navigation_scope.py`。
- stage27 验证：新增测试 8 passed；与 AIW-02 合并 14 passed；前端 `run_all` 三跑 EXIT=0（构建 4/4、契约 25/25、语音 21/21）；后端 `run_all` EXIT=0（7 子脚本全部通过）；安全红线 12 通过 / 1 失败（B5b 忽略目录产物）；浏览器桌面/移动 15 项与补验 4 项通过；独立审查两轮 0 Critical / 0 Important（首轮 3 Important 已闭环）。
- 历史命令/审查/截图详情见 [stage26 过程](../codearts_proof/ai_dialogue/stage26_既有验收补齐.md)、[stage24 报告](../codearts_proof/reports/stage24_整体验收.md)；不把历史通过数字算作本轮测试。
- 本地安全 B5b 因忽略目录运行产物失败，保留该事实；CI 干净检出成功不等于本地那次检查成功。不删证据或放宽门禁。

## 4. 为什么不能再写“完整计划全部完成”

- 未完成验证：真实模型、真机、跨设备/深色之外的完整使用验收、部署。
- 未落地主线：情境会话与跨形态语音（AIW-09）、文件成果与正文证据（AIW-10）、整体原子发布与受控动作（AIW-11）、成就与额度并发（AIW-12）、完整使用验收（AIW-13）。
- 已记录语义边界：「我的任务」任务区沿用 `my_task_condition`（发布者/受派/报名通过），不含活动负责人代管的他人任务；进入活动详情可发现。该扩展需另行确认。
- 待决定条件：最终自动验收、多级审批、扩大计量/真实收费、文件边界/依赖、成就规则、模型费用/设备条件、部署范围（D-01～D-07）。

## 5. 下一步与执行边界

- 下一轮进入 AIW-09「情境会话与语音」：先读 `aiw09-context-voice/design.md`、`task.md`，核对工作区、当前实现与 AIW-08 的对象入口，再开工。
- AIW-08 剩余建议项（非阻断）：最近条目仅在挂载时拉取；两处「查看全部」同跳 `/my-tasks`；返回深链与「大厅→详情→大厅」未单独回归；`POST /api/activities` 无 `org_id` 时不校验角色属既有契约口径（R-03 行需注明）。
- 每小时任务 `75f554a4` 当前为 active；不删除、不新建重复任务。仅当所有可自动执行的开发工作完成后再暂停。
- 当前未部署。提交/推送/发布/付费/删除均按当轮明确授权处理；详细计划不强制提交，不改忽略规则。

## 6. 新 Agent 的最短接手指令

```text
先读 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md、
本地 ai-workbench/roadmap.md、需求覆盖/共同约束/决策/验收矩阵，
再读本轮选定阶段的 design.md 和 task.md，核对 Git 与实际实现。
AIW-00～07 为历史阶段交付，AIW-08 为 stage27 增量，均不等于完整产品验收完成；AIW-09～13 仍是计划。
本轮工作范围由用户明确指定；不得恢复定时任务或继承旧轮次提交授权。
按需求逐项实现/验收并留真实证据；缺条件保持待验证，不静默缩小原目标。
```

## 7. stage27 断点与历史衔接（2026-11-14）

- 8000 端口仍为 stage26 遗留后端进程（未终止）；8010 零额度实例保留。stage27 全部浏览器证据来自 `http://127.0.0.1:8020` + `work/aiw08/demo.db`（`work/aiw07/demo2.db` 的副本，未触碰 `backend/campus.db`）。8000 因运行旧代码会拒绝 `scope=published`，不得用它的结果判断本轮功能。
- 走查脚本位于 `work/aiw07/runner/aiw08_*.mjs`（Git 忽略）；本地结果保留 `outputs/aiw08/*.log`。
- stage26 的 MCP doom loop 已停止使用；本轮全部浏览器结果为 Playwright CLI 产出，不写成 MCP 产出。历史 Codex 桌面端在 stage26 的核对原文仍见 `codearts_proof/reports/stage26_浏览器工具恢复核对.md`。
- `AGENTS.md` 单步协议条款仍未提交，等待用户确认；不得随本阶段提交顺带带上。