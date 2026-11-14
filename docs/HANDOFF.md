# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage28 / AIW-09 增量 r1 情境会话与作用域）。当前结论：AIW-00～08 的实现与 CI 已通过；stage28 完成 AIW-09 的会话作用域、归属校验与前端按目标隔离/乱序归属（r1），本地门禁、CLI 浏览器验证与三轮独立审查已收敛到 0 Critical / 0 Important；语音跨形态（r2）尚未开工，真实模型、真机与部署未验证，最终产品验收未完成。

## 1. 当前基线与本轮授权

- 分支：`main`；本轮基线 `ca74de1bbcd5a67142cf8b8c0fcbc74787491495`（stage27 回填），与 `origin/main` 一致。
- 工作区既有差异：`AGENTS.md` 的浏览器单步协议条款（stage26 用户要求保留在工作区，本轮未提交、未修改）。
- 用户授权：每小时定时任务继续推进 AIW-07～AIW-13；本轮接续 AIW-09，只完成 r1 最小增量，未展开 r2。
- 本轮记录编号：stage28；未修改业务 Prompt，无新 P 编号。平台显示模型 `deepseek-v4.1-flash-1017`，未独立核验。

## 2. 本轮产出与阅读顺序

1. [AGENTS.md](../AGENTS.md) 与 [开发记录规则](DEVELOPMENT_RECORDS.md)、[浏览器单步协议](BROWSER_VALIDATION.md)。
2. 本地总计划 [roadmap.md](../.codeartsdoer/plans/ai-workbench/roadmap.md)、[需求覆盖表](../.codeartsdoer/plans/ai-workbench/requirements.md)、[共同约束](../.codeartsdoer/plans/ai-workbench/execution-contract.md)、[待确认决策](../.codeartsdoer/plans/ai-workbench/decisions.md)、[验收矩阵](../.codeartsdoer/plans/ai-workbench/acceptance-matrix.md)。
3. 本阶段 [AIW-09 design.md](../.codeartsdoer/plans/aiw09-context-voice/design.md)、[task.md](../.codeartsdoer/plans/aiw09-context-voice/task.md) 与 r1 执行细化 [design-r1.md](../.codeartsdoer/plans/aiw09-context-voice/design-r1.md)。
4. [stage28 过程记录](../codearts_proof/ai_dialogue/stage28_情境会话与语音.md) 与 [LOG](../codearts_proof/LOG.md)、[启动指令原文](../codearts_proof/prompts/agent_team_启动指令/2026-11-14_stage28_情境会话与语音_启动指令.md)。
5. 浏览器证据：[主链路](../codearts_proof/reports/stage28_browser_evidence.json)、[晚到归属](../codearts_proof/reports/stage28_browser_late_response.json)、[401 换账号](../codearts_proof/reports/stage28_browser_account_switch.json)、[完整页作用域](../codearts_proof/reports/stage28_browser_full_page.json)；截图 `codearts_proof/screenshots/stage28/`。

详细计划仍被 `.codeartsdoer/` 忽略，仅本地保存，未远程备份。换电脑/worktree 缺计划时先补齐，摘要不能冒充完整契约。

## 3. 已有实现与历史验证

- AIW-00～06 对应 stage18～24：活动下发布与权限、统一 AI 入口/持久问答、网格/预览/共享助手、依赖时间图、资料与文本成果版本/预审、提醒失效/人工影响卡/问答额度、完整 API 验收链路。最近业务提交 `a728788`，CI run 43532974986 四 job success。
- stage25 规划入库：`19eda9f` / CI `43553685701`；回填 `d1ceab2`。
- stage26（AIW-07）：`f3fa0fb` / CI `43558695172`、回填 `0b325bd`；AC-01/03/09/14/15 与 AC-16 部分（mock）有 CLI 证据。
- stage27（AIW-08）：`694a53b` / CI `43565975450`、回填 `ca74de1` / CI `43566318740`，均四 job success；未部署。
- stage28（AIW-09 r1）提交 `b13a349` / CI run `43569210554` 四个 job 全 success；未部署。本地新增：`ai_conversations.scope_type/scope_id`、`parse_sessions.user_id`；`POST /api/agent/chat` 作用域入参、`GET /api/agent/conversations` 作用域过滤与逐条可见性复核；`authz` 驱动的对象可见性（不存在与不可见统一 4040）、撤权后拒绝且保留行；前端 `aiChat` 按 `general/activity:<id>/task:<id>` 隔离视图、晚到结果只回原作用域、401/登录/退出三路径清理；`AgentDock` 作用域入口、完整页目标展示与「回到通用助手」。CI 登记 `test_aiw09_context_scope.py`。
- stage28 验证：新增 8 passed、既有会话隔离 11 passed；后端 `run_all` EXIT=0（23 表/6 脚本）；前端 `run_all` 两次 EXIT=0（构建 4/4、契约 25/25、语音 21/21）；CLI 浏览器四项 8/8、3/3、3/3、3/3；安全红线 12 通过 / 1 失败（B5b 忽略目录历史产物）；独立审查三轮 1 Critical+6 Important → 0/1 → 0/0。
- 历史命令/审查/截图详情见 [stage27 过程](../codearts_proof/ai_dialogue/stage27_信息架构与角色页面.md)、[stage24 报告](../codearts_proof/reports/stage24_整体验收.md)；不把历史通过数字算作本轮测试。
- 本地安全 B5b 因忽略目录运行产物失败，保留该事实；CI 干净检出成功不等于本地那次检查成功。不删证据或放宽门禁。

## 4. 为什么不能再写“完整计划全部完成”

- 未完成验证：真实模型、真机、跨设备/深色之外的完整使用验收、部署。
- 未落地主线：AIW-09 的语音跨形态（r2，`C-VOICE-COMPOSER@2`）、AIW-10 文件成果与正文证据、AIW-11 整体原子发布与受控动作、AIW-12 成就与额度并发、AIW-13 完整使用验收。
- 已记录语义边界：未发送输入只在 SPA 内切目标时保留；整页刷新只恢复已持久化会话，不持久化未发送草稿（r1 设计边界）。「我的任务」仍沿用 `my_task_condition`，不含活动负责人代管的他人任务。
- 待决定条件：最终自动验收、多级审批、扩大计量/真实收费、文件边界/依赖、成就规则、模型费用/设备条件、部署范围（D-01～D-07）。

## 5. 下一步与执行边界

- 下一轮接续 stage28 的 **AIW-09 r2 语音跨形态**：先读 `aiw09-context-voice/design.md` 的 `C-VOICE-COMPOSER@2` 与 `task.md` T09-04，核对 `useVoiceComposer`、发布页 `AiPanel` 与 `aiChat` 的边界；目标是完整页/长条/微展开共用同一会话与草稿，语音定稿进当前输入，原发布页保留，不支持识别时文字兜底。真实语音/真机仍受设备与授权限制。
- r1 遗留非阻断建议：`check_contracts.py` 尚未覆盖新增两条前端契约；完整页目标文案存在「当前目标：任务：场地准备」前缀重复；`ScopeView` 未保存 `historyError`；无作用域列表逐条查询的 N+1；失败回填分支无自动化。均不改变 r1 结论。
- 每小时任务 `75f554a4` 当前为 active；不删除、不新建重复任务。仅当所有可自动执行的开发工作完成后再暂停。
- 当前未部署。提交/推送/发布/付费/删除均按当轮明确授权处理；详细计划不强制提交，不改忽略规则。

## 6. 新 Agent 的最短接手指令

```text
先读 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md、
本地 ai-workbench/roadmap.md、需求覆盖/共同约束/决策/验收矩阵，
再读本轮选定阶段的 design.md、design-r1.md 和 task.md，核对 Git 与实际实现。
AIW-00～08 为历史阶段交付，AIW-09 只完成 r1（会话作用域），语音 r2 与 AIW-10～13 未完成；
均不等于完整产品验收完成。
本轮工作范围由用户明确指定；不得恢复定时任务或继承旧轮次提交授权。
按需求逐项实现/验收并留真实证据；缺条件保持待验证，不静默缩小原目标。
```

## 7. stage28 断点与历史衔接（2026-11-14）

- 本轮浏览器证据来自 `http://127.0.0.1:8030` + `outputs/aiw09/demo.db`（`scripts/seed_phase2_demo.py` 新建的隔离库，Git 忽略）。8000/8010/8091 仍是历史遗留进程，未终止；不得用旧进程结果判断 r1 功能。
- 走查脚本位于 `work/aiw07/runner/aiw09_scope.mjs`、`aiw09_late.mjs`、`aiw09_account_switch.mjs`、`aiw09_full_page.mjs`（Git 忽略）；日志在 `outputs/aiw09/`。脚本用应用内导航或浏览器返回，避免整页 `goto` 重置 Pinia 内存缓存。
- stage26 的 MCP doom loop 已停止使用；本轮全部浏览器结果为 Playwright CLI 产出，不写成 MCP 产出。
- `AGENTS.md` 单步协议条款仍未提交，等待用户确认；不得随本阶段提交顺带带上。
- 本轮业务提交 `b13a349` 已推送，CI run `43569210554` 四个 job 全 success；本文档回填提交的 CI 只核对结果，不再为回填自身反复生成新提交。