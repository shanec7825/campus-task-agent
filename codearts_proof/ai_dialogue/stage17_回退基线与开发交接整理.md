# 阶段 17：回退基线与开发交接整理

> 状态：本地完成（仅文档，未提交）。日期：2026-11-13（Asia/Shanghai）。本阶段不是前次讨论的业务 phase3 收尾，不恢复已回退代码。

## 1. 需求来源与现场

用户说明目前已回退到上次提交，要求核对方案变化、写入 AGENTS 的计划读取要求、澄清计划是否上传，并先整理开发与问题记录。[本轮启动指令原文](../prompts/agent_team_启动指令/2026-11-13_stage17_回退与计划整理_启动指令.md) 已保存。

- 开工 `git status --porcelain=v1 --branch` 仅输出 `## main...origin/main`，无文件差异。
- `git rev-parse HEAD`：`af43dc7e15120ebb85f90e5f39879d080c2715c1`。
- 前次的 `.codeartsdoer/plans/phase3-activity-workflow` 和 `tests/backend/test_activity_workflow.py` 实际不存在。未执行任何回退或删除。
- 原有最大 stage 为 16，最大 P 为 P-016。本轮取 stage17 / P-017；不把历史缺号补成新阶段。

## 2. 决策与边界

- 产品方向保留；实施起点改为从已提交基线确认缺口。此前“收口 7 个修改文件与 1 个测试”的指令不再适用。
- 详细总计划放在本地忽略目录；AGENTS 只保存必读入口和缺失时的处理要求。本轮不上传、不改 `.gitignore`、不强制提交计划。
- HANDOFF 保存当前事实；stage 文档保存当时历史；LOG 只索引。phase/AIW、stage、P 与问题编号分开。
- 本轮不改应用、测试、配置、依赖和业务 Prompt，不调用真实业务模型，不提交、推送或部署。
- 旧 stage15、stage16 文档与历史失败保留原文。当前已出现的本地提交与旧“待提交”状态的差异写进 HANDOFF，不虚构远端 CI。

## 3. 实际工具与派工

| 项目 | 本轮实际情况 |
|---|---|
| 平台 | Codex 桌面聊天；不归因于 CodeArts |
| 工具 | PowerShell、Git 只读检查、文件读写、Python 标准库文档一致性检查、Node 本地说明页渲染；OpenAI 官方文档核对 AGENTS 读取机制 |
| 执行角色 | 当前主 Agent 整理文档；未派出子 Agent |
| 模型 | 具体可核验运行模型标识未取得，不沿用历史模型声明 |
| 独立审查 | 无代码修改，未执行独立代码 Review；文档自检不冒充独立审查 |

## 4. 产出与问题

| 产出 | 作用 |
|---|---|
| [AGENTS.md](../../AGENTS.md) | 开工必读与计划缺失处理 |
| [HANDOFF.md](../../docs/HANDOFF.md) | 回退基线、失效接手指令、下一步边界 |
| [DEVELOPMENT_RECORDS.md](../../docs/DEVELOPMENT_RECORDS.md) | 编号、问题归档、单一记录负责人和回退说明 |
| `.codeartsdoer/plans/ai-workbench/roadmap.md`（本地忽略） | 完整产品方案，按回退起点修订 |
| `.codeartsdoer/plans/handoff-baseline-cleanup/{design,task}.md`（本地忽略） | 本轮文档整理契约与任务状态 |
| 本阶段原文、LOG 与 P-017 | 实际输入、过程与流程 Prompt 变化 |

| 问题编号 | 实际问题与依据 | 处理 | 状态 |
|---|---|---|---|
| S17-I01 | 旧接手提示要求收尾的文件和 phase3 计划，在回退现场已不存在 | 交接明确失效，路线改从已提交基线确认缺口 | 已澄清，未恢复业务代码 |
| S17-I02 | 完整方案只在仓库外，AGENTS 无明确入口 | 保存本地总计划并增加必读链接与缺失处理 | 文档检查通过；入口与忽略状态已核对 |
| S17-I03 | phase、stage、P 与 LOG 行数混用容易造成接手误判 | 分离标识、按最大编号分配、记录单一负责人 | 文档检查通过；本轮无重号，未承诺所有工具自动执行 |
| S17-I04 | 旧阶段写“提交待回填”，本地 Git 已包含后续提交 | HANDOFF 标注历史口径差异，只报告本轮可核对的 Git 事实 | 已澄清；远端 CI 未查询 |
| S17-I05 | 收尾的一条合并 shell 命令被执行工具拒绝：`approval required by policy, but AskForApproval is set to Never` | 未调整权限、配置或忽略规则；缩小为独立的 `git diff --check` 与本地 Node 渲染命令，分别执行 | 两条独立命令均 exit 0；拒绝不是独立代码审查结论 |

以上为本轮文档与接手问题，不冒充产品 Bug 或已通过的功能测试。本轮没有新增真实产品排错实例，既有 debug 四节模板与三个实例保持原样。

## 5. 验证与未完成项

工作目录均为项目根目录。校验使用系统 Python 的 `python -X utf8 -`（通过 stdin 传入标准库检查，不添加项目测试或运行时依赖）。真实输出见 [stage17 文档检查报告](../reports/stage17_document_check.json)。

| 命令或检查 | 退出码与真实结果 | 范围 |
|---|---|---|
| `git status --porcelain=v1 --branch`、`git rev-parse HEAD` | exit 0；开工工作区干净，HEAD 为 `af43dc7e15120ebb85f90e5f39879d080c2715c1` | 本地 Git；远端跟踪引用未刷新 |
| `git diff --check` | exit 0 | 文档 diff 无空白错误；Windows 提示未来 LF/CRLF 转换，不是检查失败 |
| `git diff --exit-code HEAD -- backend frontend tests .github .gitignore scripts readme README.md` | exit 0 | 业务、测试、配置、忽略规则与交付说明未改动 |
| `git check-ignore`：总计划及本轮 design/task 三条路径 | exit 0；三条路径全部仍被忽略 | 详细计划未进入 Git 跟踪，不等于远端备份 |
| Python 标准库文档一致性检查 | exit 0；首轮 **19/19**、**20** 个本地链接有效；新增报告链接后的收尾复核 **19/19**、**22** 个本地链接有效 | 必读入口、唯一编号、原文、历史行保留、文档写集合、计划状态与 Git 边界 |
| Node `am.mjs render`（本地说明页，`--no-open`） | exit 0；4 panels，STE 0 warnings | 输出在本机 `.codex/visualizations/`，仅供阅读；权威入口仍是项目 AGENTS、HANDOFF 与本地总计划 |

未运行：前后端业务测试、浏览器、真机、真实业务模型、迁移验证或独立代码 Review；未查询 CI。本轮只修改文档，不为纯文档变更强造业务测试。本报告不证明未来 Agent 必然遵守所有说明，也不证明产品功能已实现。

## 6. 提交与后续

本轮仅本地落盘，未提交、未推送、未部署。完整计划受既有忽略规则保护；过程记录与交接是可随未来授权提交的文档，但本轮没有暂存。下一轮功能开发范围尚未选定。
