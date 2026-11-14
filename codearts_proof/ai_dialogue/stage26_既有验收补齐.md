# stage26 · AIW-07 既有验收补齐（2026-11-14）

## 1. 需求来源与授权

- 触发方式：每小时定时任务（`75f554a4`）。上一轮运行止步于授权边界，未启动写入者。
- 用户 2026-11-14 在本会话中明确选择「先收口 stage25 再开工」，并把阶段开发授权扩大至 **AIW-07～13**；随后选择方案 A：允许在 `work/` 独立目录安装 Playwright 运行时，不进入项目依赖、不改生产依赖清单。
- 本阶段目标：按 `.codeartsdoer/plans/aiw07-validation-closure/design.md`、`task.md` 复现 AC-01/03/09/14/15 的未验证场景，建立 AC-16 固定评测输入集；无业务代码缺陷时不改生产代码。
- 边界：未新增功能、未改模型供应商/API 契约/主题令牌/权限实现；未提交、未推送、未部署（提交在最终步骤按授权执行）。

## 2. 基线与环境

| 项目 | 实际值 |
|---|---|
| 基线 HEAD | `d1ceab2`（stage25 回填）；工作区干净 |
| stage25 收口 | `19eda9f`，CI run `43553685701` 四 job success |
| stage25 回填 | `d1ceab2`，CI run `43554038152` success |
| 主流程库 | `work/aiw07/demo2.db`（seed 脚本新建，未触碰 `backend/campus.db`；该文件不存在） |
| 零额度库 | `work/aiw07/demo3.db`（独立 seed） |
| 主服务 | `http://127.0.0.1:8000`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`、`AI_DAILY_QUOTA=50` |
| 零额度服务 | `http://127.0.0.1:8010`，`AI_DAILY_QUOTA=0` |
| 浏览器工具 | Playwright CLI 1.65.1 + Chromium 1255，位于 `work/aiw07/runner/`（Git 忽略目录，仅本地验证） |

## 3. 实际执行与结果

### 3.1 门禁

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端门禁 | `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | EXIT=0，日志末「T5 全部主验证通过（23 表 / 报名审批 / 链式增量 / SSE 催办）」 |
| 前端门禁 | `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh` | EXIT=0，ALL PASS（构建 + 契约 + 语音 21/21） |
| 安全红线 | `PYTHON_BIN="$(command -v python)" bash tests/security/test_security_redline.sh` | 12 通过 / 0 PASS-LOCAL / 1 失败；失败项 B5b「发现运行产物残留」，均位于 Git 忽略的 `outputs/`、`work/` |
| 交付校验 | `python tests/security/verify_delivery.py` | 39 PASS / 1 FAIL；D19 因规划契约路径 `.../campus-task-agent-delivery/.codeartsdoer/plans/campus-task-agent/plan.md` 不存在而失败，非本轮引入 |

### 3.2 浏览器验收（CLI 脚本，真实交互）

主流程脚本：`work/aiw07/runner/proof.mjs`、`proof2.mjs`、`ac09_rest.mjs`、`ac14.mjs`、`ac03_notify.mjs`、`ac16.mjs`、`ac16_e05.mjs`。AC-01/03/15 的首轮由 MCP `browser_run_code_unsafe` 执行（`browser_check.mjs`，返回值未落盘），随后用 `proof.mjs`/`proof2.mjs` 在 `demo2.db` 上重新执行；AC-09/14/16 为 CLI 执行。脱敏证据已归档为 `codearts_proof/reports/stage26_browser_evidence.json` 与 `stage26_acceptance_evidence.json`，原始文件仍保留在 `work/aiw07/`。

| 验收项 | 实际结果 | 判定 |
|---|---|---|
| AC-01 未登录访问 `/admin` | 回跳 `/login?redirect=/admin`，登录表单存在（`stage26_browser_evidence.json` + `aiw07-proof-ac01-redirect.png`） | 通过 |
| AC-01 会话失效访问 `/admin` | 登录后保存 Cookie → 退出登录撤销服务端会话 → 恢复旧 Cookie 访问 `/admin`，仍回跳 `/login?redirect=/admin`（`stage26_browser_evidence.json` + `aiw07-proof2-session-expired.png`；截图画面与未登录页相同，判定以 JSON 的 `afterLogoutUrl`/`expiredUrl` 为准） | 通过 |
| AC-01 成员直连管理页 | `member01` 登录落 `/ai`；再直连 `/admin` 仍落 `/ai`，组织名可见（`stage26_browser_evidence.json` + `aiw07-proof-ac01-member.png`） | 通过 |
| AC-01 通知深链 | `/messages` 中「验收通过，积分到账」→ `/tasks/1`（`ac03_notify_result.json`） | 通过 |
| AC-03 大厅 + 悬浮预览 | 活动 1 / 任务 1 / 筛选面板存在（`stage26_browser_evidence.json`）；悬停打开、Esc 关闭、快速划过不弹 | 通过 |
| AC-03 返回保位 | 390×844、滚动 92px → 详情 → 返回后仍为 92px（`proof_result.json`，两次独立运行一致） | 通过 |
| AC-09 提交 v1 | 注入错误时间 `2026-12-01 08:00`，提交成功，`submission id=1` | 通过 |
| AC-09 规则预审 v1 | `verdict=fail`，摘要「时间一致性」不通过 | 通过 |
| AC-09 退回 | 成员状态 `rejected`，退回原因写入并通知；重提后 `rejection_reason` 被清空，证据以当次通知与 `aiw07-ac09b-rejected.png` 为准 | 通过 |
| AC-09 重提 v2 | 正确时间 `2026-11-20 08:00`，`submission id=2` | 通过 |
| AC-09 旧稿拒绝 | 对 v1 发起验收返回 `4090`「该成果版本已不是最新版本」 | 通过 |
| AC-09 预审 v2 + 验收 | 预审 `unknown`（无明确冲突、缺可引用资料依据）；人工验收通过，+4 积分 | 通过（预审≠验收） |
| AC-09 积分与通知 | `member01.credits=4`，通知含「验收通过，积分到账」 | 通过 |
| AC-09 跨组织 | `outsider` 访问任务 1：API `4040`，UI 显示无权限 | 通过 |
| AC-14 零额度 | 配额「0 / 0」、警示条显示、输入框与发送禁用；任务大厅仍可访问 | 通过 |
| AC-14 AgentDock 三形态 | 长条存在、输入禁用；展开出现「最近对话 / 打开完整页」；完整页 `/ai` 可达 | 通过 |
| AC-14 移动视口 | 390×844：`scrollWidth=390`、无横向溢出、AgentDock 可见 | 通过 |
| AC-15 深色主题 | `data-theme` light→dark，背景 `rgb(245,247,251)`→`rgb(15,17,21)`（`proof_result.json` + `aiw07-proof-dark.png`） | 通过 |
| AC-15 移动 AI 页 | 390×844：`scrollWidth=390`、底部导航可见、无小于 44px 的可见按钮（`proof_result.json`） | 通过 |
| AC-16 E-01 | 仅列「2026 迎新志愿活动」，引用「搬运桌椅 / 场地准备」，无外院泄露 | 通过（mock） |
| AC-16 E-02 | 列出 2 项可见事务，引用正确，无外院 | 通过（mock） |
| AC-16 E-05 | `outsider` 只看到「外语角筹备」，未泄露组织 A | 通过（mock） |
| AC-16 E-03 | mock 返回固定「最需要关注」文本，未体现只读拒答 | **未验证**（真实模型未运行） |

截图位于 `codearts_proof/screenshots/stage26/`（23 张）。7 张已移到 `work/aiw07/obsolete_screens/` 且不提交：2 张来自 `demo.db` 错误批次（`aiw07-ac09-submit-v1.png`、`aiw07-ac09-cross-org.png`），5 张来自 MCP 首轮 `demo.db`（`aiw07-ai-desktop/dark/mobile.png`、`aiw07-hall-desktop/peek.png`）。首版 `browser_ac09.mjs` 的另外 4 张 `ac09-*` 截图因脚本超时未生成；当前提交截图均来自 `demo2.db` / `demo3.db` 的 CLI 结果。

## 4. 发现的问题与处置

| 编号 | 现象 | 处置 |
|---|---|---|
| S26-I01 | 8000 端口被历史演示服务占用（PID 37680，连接 `outputs/aiw06/demo.db`），本轮实例启动失败 `WinError 10048` | 经用户明确指示停止旧进程；8000 由 demo2 隔离服务接管 |
| S26-I02 | MCP `tool_call` 重复调用触发 doom loop，多次中断验证 | 改用 `work/aiw07/runner/` 下 Playwright CLI 脚本，单次执行完整流程；MCP 通道停止使用 |
| S26-I03 | 首版脚本在 v2 尚未创建时执行「旧稿拒绝」，实际把最新 v1 验收通过（demo.db 出现 `verified` 与 4 积分） | 未将 demo.db 结果当作通过；另建 demo2 重跑，旧稿拒绝改到 v2 之后；旧库保留为证据，不提交 |
| S26-I04 | v2 预审 `unknown` 而人工验收通过 | 与契约「预审≠验收、人工可覆盖」一致，不视为缺陷；记录为需人工确认 |
| S26-I05 | mock 对「帮我验收」返回固定任务列表，未体现只读拒答 | 标为未验证，不据此判定真实模型行为 |
| S26-I06 | 首次返回保位在 390×844 下页面高度不足（`scrollHeight=936` 但 `scrollTo(0,420)` 后 `scrollY=0`） | 保持 390×844、改滚动 92px 重测，前后一致 |
| S26-I07 | `ac09_result.json` 的 v2 预审 `verdict` 为空（选择器采集过早），记录不能只依据该 JSON 判通过 | 以 `demo2.db` 的 `submission_prechecks#2`（`verdict=unknown`）为准；本文件已注明采集失效 |
| S26-I08 | `ac16.mjs` 首次运行在切换 outsider 时登录超时，JSON 含 `script-error` | 补写 `ac16_e05.mjs`（先清 Cookie）重跑 E-05 成功；原失败保留在 JSON，不删除 |
| S26-I09 | 首轮 AC-01/03/15 证据仅存在于 MCP 返回值，未落盘且无对应截图 | 新增 `proof.mjs` 在 demo2 重跑，写 `proof_result.json` 与 6 张 `aiw07-proof-*.png` |
| S26-I10 | 验证脚本含明文测试口令 | 仅存在于 Git 忽略的 `work/aiw07/runner/`；不归档、不再截图引用 |
| S26-I11 | 退回原因在 `demo2.db` 重提后被清空（`rejection_reason=NULL`） | 退回证据以当次预审记录、通知（`验收未通过`）与 UI 截图为准，不把当前字段当作唯一证据 |
| S26-I12 | 首版 `browser_ac09.mjs` 超时，另 4 张 `ac09-*` 截图从未生成 | 以 `ac09b-*`/`ac09c-*` 与 JSON 为证据；本文件已说明未生成，不把缺失截图当已归档 |

## 5. 独立审查

- 审查者：独立 Review Agent（只读，读取本记录、验证 JSON、数据库与相关源码）。
- 第一轮结论：2 Critical（AC-01 证据未落盘且截图声明不符；`BROWSER_VALIDATION.md` 仍写 8001/保留旧进程）、7 Important（v2 预审 JSON 矛盾、ac16 脚本失败未说明、AC-16 执行范围、工具归属、数值证据未落盘、错误库截图、AGENTS 修改授权依据）。
- 第一轮处置（逐条）：C1→新增 `proof.mjs` 落盘；C2→修正单步协议端口与断点；I1→S26-I07；I2→S26-I08；I3→§6 与评测集 `status`；I4→HANDOFF/LOG 改为「MCP 首轮 + CLI 落盘复核」；I5→`proof.mjs` 与归档 JSON；I6→移出错误批次截图；I7→启动指令决策补授权说明。
- 第二轮结论：1 Critical（AC-01「会话失效」实际未验证）、5 Important（证据 JSON 未归档、大厅明细无落盘、5 张首轮截图来源不符、首版截图去向缺失、AGENTS 授权依据为推断）。
- 第二轮处置：新增 `proof2.mjs` 真实会话失效用例并归档 `stage26_browser_evidence.json`；移出 5 张首轮截图；说明首版 4 张未生成（S26-I12）；AGENTS 条款标注为推断授权、提交前请用户确认。
- 第三轮结论：无 Critical，C-1 与 I1–I5 已关闭；剩 2 项 Important——AC-09/14/16 证据仍在忽略目录、§5 第三轮结论未回填。
- 第三轮处置：新增 `stage26_acceptance_evidence.json` 归档 AC-09/14/16 脱敏结果；本节回填第三轮结论；说明 proof2 截图与未登录页同画面、判定以 JSON 为准。
- 最终结论：独立审查三轮收敛，无未关闭 Critical / Important；`AGENTS.md` 新增条款属推断授权，提交前由用户确认是否保留。

## 6. 未完成 / 未验证

- AC-16 已执行 mock：E-01、E-02、E-05。
- AC-01 的未登录回跳、会话失效回跳、成员被拒管理页与通知深链均已取得 CLI 证据；不再列为未验证。
- AC-03 的 `metrics.y=0` 采集于滚动前，`before/after=92` 采集于滚动后；两者不矛盾，`proof2` 的大厅明细与 `proof` 的预览/返回分别落盘。
- `proof.mjs` 的 `ok` 字段只覆盖主要 URL/主题/滚动判定；`orgShown`、`smallVisibleButtons` 作为页面取值记录，不与 `ok` 合并，结论以记录中逐项数值为准。
- AC-16 未验证 / 未执行：E-03（mock 固定回复未覆盖只读拒答，未取得证据）；E-04、E-06、E-07 未执行；E-08 的零额度 UI 已由 AC-14 覆盖，但未按该 prompt 单独执行。
- D-06 真实模型：未运行；上述 mock 结果不能代替真实模型行为。
- 真机与部署：未验证。
- D19 交付校验失败（规划契约路径缺失）属历史问题；B5b 安全红线失败包含本轮 `work/aiw07` 日志与 `outputs/phase19` 等历史残留，均为 Git 忽略目录，未修改检查规则。
- `demo.db` 中因脚本顺序错误产生的「v1 已验收」仅作问题证据，不进入结论与提交。
- 本轮门禁（11:56）早于浏览器验证（12:18–12:40）；本轮无业务代码变更，门禁结论仍对应当前代码。

## 7. 提交与 CI

- 待回填：提交 SHA、推送结果、对应 CI run。
- 回滚：文档与评测输入集可 `git revert`；验证脚本与隔离库位于 Git 忽略目录，不随提交分发。

## 8. 并发写入者与工具归属

- Codex 桌面端在 12:04–12:05 写入：`AGENTS.md` 浏览器单步协议条款、`docs/BROWSER_VALIDATION.md`、`codearts_proof/reports/stage26_浏览器工具恢复核对.md`、`docs/HANDOFF.md` §7 与 `LOG.md` 的 stage26 行。其记录的实际动作是 CI 核对、端口健康检查与 MCP 服务重启，未改业务代码、未提交。
- CodeArts 在后续运行中执行 CLI 浏览器验收、前后端门禁、安全红线与交付校验，并把 LOG 的 stage26 行接续为同一阶段的最终结果，未另分配 stage 编号。
- 用户明确要求「停止 8000 历史演示服务并重试」并选择方案 A，使环境与 Codex 原文断点不同：8001 已停止，8000 由 `demo2.db` 接管，8010 为零额度实例；Codex 的「保留 8000 历史库/8001」不再适用。
- 冲突处理：保留 Codex 的恢复核对报告原文；本章与 §2–§7 记录本轮实际验证结果与差异，不覆盖其已发生事实。