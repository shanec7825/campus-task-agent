# stage26 浏览器工具恢复核对

> 环境口径说明（2026-11-14 后续追加）：本文件记录 12:04–12:05 当时的核对事实；随后用户明确要求停止 8000 历史演示服务并选择 CLI 方案，8001 已停止、8000 改由 `work/aiw07/demo2.db` 接管，未登录 `/admin` 也已由 CLI 复现。当前口径以 [HANDOFF §7](../../docs/HANDOFF.md) 为准，本节原文保留不改。

## 一、现象

2026-11-14 用户提供 CodeArts 回报：短时间多次导航 /admin、/login 后触发 doom loop 并禁用工具，要求修复。本轮在 Codex 桌面端核对；不是 CodeArts 原浏览器验证的续跑结果。

## 二、原因与实际证据

- 用户报告指向重复导航后的会话保护；缺少平台内部调用轨迹，不能独立证明“通道重试”或准确重复次数。
- 实际查看 CodeArts MCP 面板：Playwright-MCP 已启用、绿色连接；不能把 Agent 回答中的“工具禁用”直接当作 MCP 服务崩溃。
- 8000/8001/5173 的 `/api/health` 本轮均 HTTP 200、mock=true、23 表。8001 为当时 AIW-07 验证服务；5173 代理仍指向 8000，当时约定续接固定 8001（该口径已于同日失效，见顶部说明）。
- GitHub API 本轮核对：`d1ceab2a24dce38a46cf4ef764a4c6599cf9d9e8` → run [43554038152](https://github.com/shanec7825/campus-task-agent/actions/runs/43554038152)，completed/success。
- `work/aiw07/backend_run_all.log` 含主验证通过摘要，`frontend_run_all.log` 含 ALL PASS 和语音 21/21；本轮只核对旧日志，没有重跑套件。
- 未登录 /admin 的前端异常尚未在本轮浏览器复现，未改路由代码，不宣称已修复应用 Bug。（后续 CLI 已复现为回跳 `/login?redirect=/admin`，见顶部说明与 HANDOFF §7。）

## 三、处理方式

新增 `docs/BROWSER_VALIDATION.md`，由 AGENTS 引用，明确一次调用一判断、禁止导航轮询、未知结果先观察、保护触发后停止、恢复后只读快照。规则是操作约束，不是已验证的原生 Hook。

接续时保留已有服务/数据和完成结果，不重新跑同一阶段开工操作。通过 CodeArts 正常 MCP 重启检查连接，保留防循环保护；服务连接与会话工具权限分开核实。

## 四、结果与限制

单步规则和断点已落盘。本轮通过 CodeArts 设置 → MCP工具 → Playwright-MCP 的“重启”执行一次正常服务重启，界面先显示“正在重启 Playwright-MCP MCP 服务器...”，随后明确显示“Playwright-MCP MCP 服务器已连接”，状态点为绿色、开关保持启用。服务连接恢复已确认。

文档检查：`git diff --check` EXIT=0；一次性本地 Markdown 链接检查 23 个、0 断链。没有调用已禁用的 Playwright 导航、修改平台保护或通过其他浏览器客户端绕过禁用。

本轮未修改业务代码、未提交、未推送、未调用真实模型、未部署。当前会话能否再次使用 Playwright，必须在平台恢复后由一次只读调用确认，不能以绿色连接冒充全部工具恢复。
