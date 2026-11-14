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
## 6. 增量 r2：语音跨形态收口（2026-11-14 接续）

> 本节由 stage29 交付后的单写入接管者补记，只覆盖 r2 语音；r1 会话作用域结果保留在第 1～5 节，不重算。r2 计划见本地 `.codeartsdoer/plans/aiw09-context-voice/design-r2.md`，状态：**本地完成、未提交、未推送、无新 CI、未部署**。

### 6.1 范围与最小写集合

- 范围：AI 完整页 / 长条 / 微展开共用语音录入，定稿写入当前作用域输入；发布页语音保持原行为；切目标停止并保留原目标文本；录音中禁用文字输入与发送，避免手打被 interim/定稿覆盖。
- 写集合：`frontend/src/composables/useVoiceComposer.ts`、`useAiVoiceSink.ts`（新）、`components/ai/AgentVoiceButton.vue`（新）、`AgentDock.vue`、`views/AiConsole.vue`、`stores/aiChat.ts`、`tests/frontend/check_contracts.py`、`work/aiw07/runner/aiw09_voice*.mjs`。
- 不做：录音持久化、外部识别供应商、自动发送、语音执行业务写动作、额度口径变更；AIW-11 取消项未恢复。

### 6.2 审查轮次与关闭状态

| 轮次 | 结论 | 处置 |
|---|---|---|
| 首轮（原执行者） | 1 Critical / 2 Important / 6 Suggestion | 本轮接管后按 design-r2 §6 修复，不重做 |
| 第二轮独立复核 | 0 Critical / 2 Important（新残留）/ 若干 Suggestion | 首轮 1C/2I 已关闭；修复 finalize 单槽与录音中发送按钮 |
| 第三轮独立复核（末轮） | 0 Critical / 3 Important（前轮修复引入）/ 建议 | 已修复 start 清空 finalizeSinks、live timer 本地状态丢失、resumeTimer 早退；轮次上限内未再开第四轮独立复核 |

- Critical 修复：`currentSink()` 只返回 `configuredSink ?? draftSink`；`QueuedChunk` 固定 `sink` + `round`；`start()` 非续接先 `settlePreviousSession()` 再递增轮次；`drain` 用 `item.sink.applyStream`；失败回滚与缓冲清空仅作用于当前轮。
- Important 2 修复：`flushLiveText/clearLiveText` 使用 `activeSink()`；尾片收尾用 `finalizeSinks: VoiceSink[]` 逐轮 `finishStreaming()`；`commitStoppedSession` 先固定发起轮 sink；发布页录音切 AI 页停止后 `draft.mode` 回 `typing`。
- Important 3 修复：AI 输入框与发送按钮绑定 `voiceRecording`，语音按钮在录音中保持可停止；`send`/`sendMessage` 增加录音中 guard。
- 第三轮遗留 Suggestion 未处理：2000 截断静默丢字提示、语音写回未纳入 aiChat epoch、模块级 `configuredSink` 依赖 setup 顺序、失败请求后同轮后继切片不重发。均非本轮阻断项。

### 6.3 实际验证

工作目录：仓库根；后端隔离库 `work/aiw09/demo.db`（由 `work/aiw08/demo.db` 复制，`MAAS_MOCK=1`、`RUN_SCHEDULER=0`），服务 `127.0.0.1:8030`；未触碰 `backend/campus.db`。

| 检查 | 命令 / 证据 | 结果 |
|---|---|---|
| 前端完整门禁 | `PYTHON_BIN="$(command -v python)" bash tests/frontend/run_all.sh`；日志 `outputs/aiw09/frontend-runall-r2-round3e.log` | EXIT=0（构建 4/4、契约 26/26、语音 21/21） |
| 后端完整门禁 | `PYTHON_BIN="$(command -v python)" bash tests/backend/run_all.sh`；日志 `outputs/aiw09/backend-runall-r2.log` | EXIT=0（23 表 / 6 脚本；后端未改动，此结果在最终前端修复前取得） |
| AI 三形态语音 | `node work/aiw07/runner/aiw09_voice.mjs`；日志 `outputs/aiw09/voice-r2-round3b.log`，证据 `reports/stage28_browser_voice_r2.json` | 8/8：V1 实时/定稿、V2 切目标保留、V5 不重复、V3 不支持兜底、V4 麦克风拒绝、V6 网络失败、V7 旧轮尾片窗口切目标再开录、V8 录音中禁用输入 |
| 发布页与跨页收尾 | `node work/aiw07/runner/aiw09_voice_publish.mjs`；日志 `outputs/aiw09/voice-publish-r2-round3b.log`，证据 `reports/stage28_browser_voice_publish_r2.json` | 3/3：P1 原发布页；P2 `modeBefore=streaming → modeAfter=typing`；P3 旧轮尾片晚到 + 新轮在队，`modeAfter=typing` |
| r1 四个浏览器场景 | `aiw09_scope/full_page/late/account_switch.mjs`；日志 `outputs/aiw09/*-r2-final.log`，JSON `reports/stage28_*_r2.json` | 合计 17 用例 / 0 失败 |
| 静态契约 | `tests/frontend/check_contracts.py` ㉖ | 26/26；固定 currentSink/队列 sink+round/start 结算/finalizeSinks/录音中禁用输入与发送 |

- 全部浏览器证据为伪造 `SpeechRecognition` + mock 后端，**不代表真实 Chrome/Edge 识别、真实模型或真机**。
- 控制台 401 来自登录探测，`ERR_FAILED` 来自 V6 故意断网；`apiErrors` 为空。

### 6.4 本轮真实问题

1. **AiConsole 模板误吞**：修复发送按钮时一处 `edit` 匹配到建议问题按钮，删除了额度条、`composer` 容器、输入框与语音按钮；前端契约检查 25/26 失败暴露。已按 HEAD 原文恢复整块并重新绑定 `voiceRecording`，恢复后 26/26、构建与浏览器回归通过。
2. **V6 首跑失败**：录音中禁用输入后，断网场景未先停止录音就尝试 `fill`，超时。判定为回归脚本前置状态错误，不是产品缺陷；脚本改为先停止录音再验证文字兜底。
3. **P2 返回导航失败**：侧栏没有 `/publish` 导航项；改用顶部 `data-testid="publish-button"`，P2 通过。

### 6.5 未完成与未验证

- AIW-09 新增历史对话（T09-09～T09-12）未实施；本轮只收口 r2 语音。
- 第三轮修复后未再开第四轮独立审查（项目上限三轮）；该修复只经本轮回归与静态契约覆盖。
- 真机、真实模型、部署未验证；提交/推送/CI 未发生，等待用户当轮具体授权。
- `stage29` 计划、LOG、Prompt 与过程记录保留原样，未为解除写者互斥先行提交。