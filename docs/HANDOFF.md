# 当前开发交接

> 更新日期：2026-11-14（Asia/Shanghai，stage26 / AIW-07 既有验收补齐）。当前结论：AIW-00～06 阶段实现与 CI 已通过；stage25 规划已入库（`19eda9f` / CI `43553685701`，回填 `d1ceab2` / CI `43554038152`）；AIW-07 的 AC-01/03/09/14/15 已用 CLI 浏览器实际复现通过，AC-16 固定评测输入集已建立并在 mock 下验证 E-01/E-02/E-05。业务代码本轮未改。真实模型、真机与部署仍未验证，最终产品验收未完成。

## 1. 当前基线与本轮授权

- 分支：`main`；本轮基线 `d1ceab2a24dce38a46cf4ef764a4c6599cf9d9e8`，开工后工作区仅有本轮 stage26 文档改动。
- 用户本轮决策：针对授权边界选择 `1`（扩大授权至 AIW-07～13）；选择「先收口 stage25 再开工」；明确要求停止 8000 历史演示服务并重试；选择方案 A，允许在 `work/` 独立目录安装 Playwright CLI（不进入项目依赖）。
- stage25 收口：`19eda9f`（CI `43553685701` 四 job success）；回填 `d1ceab2`（CI `43554038152` success）。
- 本轮记录编号：stage26；未修改业务 Prompt，无新 P 编号。Codex 桌面端完成工具中断核对并新增 [浏览器单步协议](BROWSER_VALIDATION.md)；华为云码道（CodeArts）先用 MCP 首轮验证 AC-01/03/15，后改用 CLI 落盘复核并完成 AC-09/14/16、门禁与记录。定时任务 `75f554a4` 为 active。

## 2. 本轮产出与阅读顺序

1. [AGENTS.md](../AGENTS.md) 与 [开发记录规则](DEVELOPMENT_RECORDS.md)。
2. 本地总计划 [roadmap.md](../.codeartsdoer/plans/ai-workbench/roadmap.md)，版本 `2026-11-14-0d45809-r2`。
3. 本地 [需求覆盖表](../.codeartsdoer/plans/ai-workbench/requirements.md)：R-01～R-22；[共同约束](../.codeartsdoer/plans/ai-workbench/execution-contract.md)。
4. 本地 [待确认决策](../.codeartsdoer/plans/ai-workbench/decisions.md)：D-01～D-07；[验收矩阵](../.codeartsdoer/plans/ai-workbench/acceptance-matrix.md)：AC-01～AC-17。
5. 下一执行入口 [AIW-07 design.md](../.codeartsdoer/plans/aiw07-validation-closure/design.md) 与 [task.md](../.codeartsdoer/plans/aiw07-validation-closure/task.md)。AIW-08～13 也分别已有 design/task，通过 roadmap 索引读取。
6. [stage25 过程记录](../codearts_proof/ai_dialogue/stage25_完整功能规划与验收口径修订.md) 与 [可携带计划摘要](../codearts_proof/reports/stage25_完整功能实施计划摘要.md)。

详细计划仍被 `.codeartsdoer/` 忽略，仅本地保存，未远程备份。修订前总计划原样保存在本地 `ai-workbench/history/roadmap-2026-11-13-r1.md`；旧阶段历史清单未被批量勾选或重写。换电脑/worktree 缺计划时先补齐，摘要不能冒充完整契约。

## 3. 已有实现与历史验证

- AIW-00～06 对应 stage18～24：活动下发布与权限、统一 AI 入口/持久问答、网格/预览/共享助手、依赖时间图、资料与文本成果版本/预审、提醒失效/人工影响卡/问答额度、完整 API 验收链路。
- 最近业务提交 `a728788`：CI run [43532974986](https://github.com/shanec7825/campus-task-agent/actions/runs/43532974986) 四个 job success。
- 文档提交 `2439154`：CI run [43533483789](https://github.com/shanec7825/campus-task-agent/actions/runs/43533483789) 四个 job success。
- 文档提交 `0d45809`：CI run [43533843104](https://github.com/shanec7825/campus-task-agent/actions/runs/43533843104) 四个 job success。
- stage25 收口 `19eda9f` / CI `43553685701`，回填 `d1ceab2` / CI `43554038152`，均四 job success。
- stage26 浏览器验收：AC-01 未登录与会话失效均回跳 `/login?redirect=/admin`、成员被拒管理页落 `/ai`、通知深链到 `/tasks/1`；AC-03 大厅/预览/Esc/快速划过/返回保位 92→92；AC-09 v1 预审 fail→退回→v2 重提→旧稿 4090→同页验收 +4 积分→跨组织 4040；AC-14 零额度 0/0、AgentDock 三形态、390 视口；AC-15 深色 light→dark、移动无溢出。证据见 [stage26 过程](../codearts_proof/ai_dialogue/stage26_既有验收补齐.md)、[浏览器证据 JSON](../codearts_proof/reports/stage26_browser_evidence.json)、[AC-09/14/16 证据 JSON](../codearts_proof/reports/stage26_acceptance_evidence.json)、[评测输入集](../codearts_proof/reports/stage26_model_eval_inputs.json) 与 [截图](../codearts_proof/screenshots/stage26/)。
- 本轮后端 `run_all` EXIT=0、前端 `run_all` ALL PASS；安全红线 12 通过 / 1 失败（B5b 忽略目录产物）；交付校验 39 / 1（D19 规划契约路径缺失，历史问题）。
- 历史命令/审查/截图详情见 [stage24 验收报告](../codearts_proof/reports/stage24_整体验收.md) 和 [stage24 过程](../codearts_proof/ai_dialogue/stage24_整体验收.md)，不将历史通过数字算作本轮测试。
- `test_aiw06_acceptance.py` 应单文件运行；全量 pytest 可能因已有 engine 而模块级 skip，执行时核对。当前新库验证约束继续有效。
- 历史本地安全 B5b 因忽略目录运行产物失败，保留该事实；CI 干净检出成功不等于本地那次检查成功。不删证据或放宽门禁。

## 4. 为什么不能再写“完整计划全部完成”

- 未完成验证：部分桌面同页验收/跨组织浏览器操作，移动完整提交/退回/重提/验收，零额度/AgentDock、深色主题、真实模型与真机。
- 未落地主线：独立我的任务/我发布活动与最近条目；情境语音和对象级会话；活动/任务整体原子发布；文件正文与定位引用；初稿检查点、接单推荐与 AI 可确认业务提案；成就与额度并发准确性。
- 待决定条件：最终自动验收、多级审批、扩大计量/真实收费、文件边界/依赖、成就规则、模型费用/设备条件、部署范围。具体只阻塞决策清单中的相关子任务。
- 更正依据是实际源码、原始目标和未勾选验收条目；stage24 已发生的实现、测试与 CI 保持历史有效。

## 5. 下一步与执行边界

- AIW-07 的浏览器验收已补齐（AC-01/03/09/14/15），AC-16 固定评测输入集已建立；真实模型与真机条件仍缺，只挂起对应证据行，不用 mock 或 API 成功代替。
- 下一次定时运行进入 AIW-08「导航与角色」：先读 `.codeartsdoer/plans/aiw08-navigation-roles/design.md`、`task.md`，核对工作区与当前实现，再开工。
- 每小时任务 `75f554a4` 当前为 active；不删除、不新建重复任务。阶段收口后若全部完成再暂停。
- 当前未部署。提交/推送/发布/付费/删除均按当轮明确授权处理；详细计划不强制提交，不改忽略规则。

## 6. 新 Agent 的最短接手指令

```text
先读 AGENTS.md、docs/HANDOFF.md、docs/DEVELOPMENT_RECORDS.md、
本地 ai-workbench/roadmap.md、需求覆盖/共同约束/决策/验收矩阵，
再读本轮选定阶段的 design.md 和 task.md，核对 Git 与实际实现。
AIW-00～06 为历史阶段交付，不等于完整产品验收完成；AIW-07～13 仍是计划。
本轮工作范围由用户明确指定；不得恢复定时任务或继承旧轮次提交授权。
按需求逐项实现/验收并留真实证据；缺条件保持待验证，不静默缩小原目标。
```

## 7. stage26 工具中断与最终续接（2026-11-14）

- Codex 桌面端 12:04–12:05 核对：`d1ceab2` CI `43554038152` success；8000/8001/5173 健康；新增 [浏览器单步协议](BROWSER_VALIDATION.md) 并由 AGENTS.md 引用；未改业务代码、未提交。原始证据见 [工具核对](../codearts_proof/reports/stage26_浏览器工具恢复核对.md)。
- 用户随后明确要求停止 8000 历史演示服务并重试，选择方案 A 安装本地 Playwright CLI。环境因此变更为：8000 = `work/aiw07/demo2.db`（主流程），8010 = `work/aiw07/demo3.db`（零额度），8001 已停止；5173 仍代理到 8000。Codex 原文中「保留 8000 历史库/8001」的断点已被用户本轮指令覆盖。
- MCP 通道触发 doom loop 后停止使用；全部浏览器证据来自 `work/aiw07/runner/` 的 Playwright CLI 脚本（Git 忽略，不提交）。脚本顺序错误导致 `demo.db` 中 v1 被误验收，已另建 `demo2.db` 重跑，旧库仅作问题证据。
- 未登录 `/admin` 的应用侧守卫已由 CLI 复现为回跳 `/login?redirect=/admin`，不再列为待复现异常。
- stage26 过程记录、浏览器证据 JSON、评测输入集、截图与 LOG 行均已归档；提交与对应 CI 结果在提交后回填，不提前写成通过。