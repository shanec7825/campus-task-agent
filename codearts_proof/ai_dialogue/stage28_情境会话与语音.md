# stage28：AIW-09 情境会话与语音（增量 r1）

> 开工日期：2026-11-14。本记录随实际执行补全，未执行的项不预写为通过。
> 上一阶段 stage27（AIW-08）已收口：`694a53b` / CI `43565975450`，回填 `ca74de1`。

## 1. 需求、基线与范围

- 需求来源：用户本轮每小时定时指令继续推进 AIW-07～AIW-13；AIW-08 已收口，接续 AIW-09。
- 计划入口：`.codeartsdoer/plans/aiw09-context-voice/design.md`、`task.md`、本轮细化 `design-r1.md`（本地忽略目录）。
- 基线：`main` / `ca74de1bbcd5a67142cf8b8c0fcbc74787491495`，与 `origin/main` 一致。
- 工作区既有差异：`AGENTS.md` 两行（stage26 用户要求保留，未提交、本轮不修改）。
- 本轮范围（增量 r1）：`C-AI-SCOPE@1` 会话作用域与归属、`C-FE-AI-SCOPE@1` 按目标隔离与乱序归属、入口作用域传递。语音跨形态（`C-VOICE-COMPOSER@2`）不在 r1，留待下一次触发。
- 判定依据：现有 `ParseSession` 无所有者字段且 `stream/parse` 按客户端 `session_id` 直接读取；`AiConversation` 只绑定 `user_id`，无活动/任务作用域；前端 store 只有单一会话视图，无法证明 A 的晚到回复不进入 B。以上为代码事实，未据此宣称已复现漏洞。

## 2. 决策与边界

- 不做旧库/副本迁移；用全新隔离库验证。`parse_sessions.user_id` 允许 NULL 以兼容旧行，但 NULL 视为无主、任何账号不得续写。
- 作用域对象可见性由服务端 `authz.can_view_activity` / `can_view_task` 判定；客户端 ID 不授权。
- 撤权后拒绝读取/续写，保留历史行不删。
- 不新增依赖、不更换模型供应商、不扩大额度计量范围（D-03）、不做自动验收/多级审批（D-01/D-02）。

## 3. 实际执行与派工

- 主 Agent 串行实现（单写入者），独立 Review Agent 审查；不使用第二个并行写入者。
- 实际工具与模型：平台显示 `deepseek-v4.1-flash-1017`，未独立核验。

## 4. 验证

工作目录：仓库根 `D:\Users\Lenovo\Downloads\campus-task-agent-delivery\campus-task-agent`；所有后端测试使用临时隔离库（`tempfile.mkdtemp` + `DATABASE_PATH`），不触碰 `backend/campus.db`；演示库 `outputs/aiw09/demo.db`（Git 忽略），服务 `127.0.0.1:8030`，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`。

| 检查 | 命令 | 结果 |
|---|---|---|
| 新增会话作用域套件 | `python -m pytest tests/backend/test_aiw09_context_scope.py -q` | 8 passed（含不存在对象 4040、outsider 对 org A 4040、撤权后列表不出现、ParseSession 跨账号/无主拒绝） |
| 既有会话隔离回归 | `python -m pytest tests/backend/test_ai_console.py -q` | 11 passed |
| 后端完整门禁 | `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh` | EXIT=0（23 表 + 6 脚本），日志 `outputs/aiw09/backend-runall2.log` |
| 前端完整门禁（修复后） | `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh` | EXIT=0（构建 4/4、契约 25/25、语音 21/21），日志 `outputs/aiw09/frontend-runall3.log`；T5 后复跑 `frontend-runall4.log` 同样 EXIT=0 |
| 浏览器主链路 | `BASE_URL=http://127.0.0.1:8030 node work/aiw07/runner/aiw09_scope.mjs` | 8/8；证据 `codearts_proof/reports/stage28_browser_evidence.json`，截图 `codearts_proof/screenshots/stage28/` |
| 浏览器晚到响应 | `node work/aiw07/runner/aiw09_late.mjs` | 3/3；证据 `reports/stage28_browser_late_response.json` |
| 浏览器 401 换账号 | `node work/aiw07/runner/aiw09_account_switch.mjs` | 3/3；证据 `reports/stage28_browser_account_switch.json` |
| 浏览器完整页作用域 | `node work/aiw07/runner/aiw09_full_page.mjs` | 3/3（断言 `.scope-target` 含“场地准备”、切回通用后目标为“通用助手”且按钮消失、任务会话仍可 API 取到）；证据 `reports/stage28_browser_full_page.json` |
| 安全红线 | `bash tests/security/test_security_redline.sh` | 12 通过 / 1 失败（B5b 忽略目录历史运行产物 `work/aiw08/serve.log` 等，历史口径，未放宽门禁） |
| CI 配置 YAML | `python -c "import yaml;..."` | 解析通过（3 jobs），已登记 AIW-09 套件 |

真实问题与处理：

1. **前端门禁首次 EXIT=2**：静态契约检查退出码 49，日志无断言输出。根因是 WindowsApps `python3` 存根；显式 `PYTHON_BIN="$(command -v python)"` 后 EXIT=0。未改门禁。
2. **浏览器脚本首版 4/8 失败**：A3 输入未恢复、A4 发送按钮 disabled、A5/A6 级联。根因是脚本用整页 `page.goto` 切换页面，Pinia 内存缓存被重置；改为应用内（大厅卡片 / 浏览器返回）导航后 8/8。不是业务代码缺陷，但据此明确边界：未发送输入只跨 SPA 切页保留，整页刷新只恢复已持久化会话。
3. **首轮独立审查 1 Critical / 6 Important**：C1 账号 401 后换账号不清 `aiChat` 缓存；I1 恢复中发送可能错配；I2 旧库缺列；I3 列表未校验可见性；I4 新测试未进 CI；I6 完整页强制 general 丢当前会话。已由原实现者修复并补回归；第二轮复核 0 Critical / 1 Important（完整页保留作用域却不显示目标、无回通用入口），T5 修复后第三轮 0 Critical / 0 Important。
4. 审查 I5 指前端乱序无自动化：新增 `aiw09_late.mjs` 用 `page.route` 延迟活动会话请求，切任务页后断言晚到内容不进入任务作用域、回活动页可见；`aiw09_account_switch.mjs` 覆盖 C1 的 401 换账号路径。
5. **完整页脚本首次 2/3 失败**：等待发送按钮变为可用超时。原因是发送后输入清空，按钮按设计保持 disabled；改为仅在面板未展开时点击展开后 3/3。第三次按审查建议收紧 `.scope-target` 与按钮计数断言后仍 3/3。

## 5. 未完成与未验证

- 语音跨形态（`C-VOICE-COMPOSER@2`）未开工，AC-06 语音场景未验证。
- 真实模型、真机、部署与线上验收未执行；mock 回答不能替代真实模型质量证明，390×844 模拟视口不能替代真机。
- `AGENTS.md` 工作区改动仍等待用户单独授权处置。
- 三轮审查共 18 条 Suggestion 未全部处理（scopeKey 重复实现、非法 scope 行 4001 语义、AiChatOut 注释、ScopeView 未保存 historyError、无作用域列表逐条查询的 N+1、失败回填分支无自动化）。其中“浏览器完整页断言偏弱”已在证据脚本收紧；“契约检查未覆盖新增两条契约”和“完整页文案前缀重复（当前目标：任务：场地标题）”留在后续增量（r2 语音或单独小修）处理，不阻断 r1。