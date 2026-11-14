# stage33：AIW-09 历史会话增量（r3）

> 日期：2026-11-14（Asia/Shanghai）。本阶段只做「历史浏览/选择」增量，语音 r2 不重做；未提交、未推送、无 CI、未部署。

## 1. 需求与范围

- 用户指令接续：AIW-14 之后进入 AIW-09 历史对话。
- 需求：R-08/09/17/21/25；AC-05/06/23。
- 计划：`.codeartsdoer/plans/aiw09-context-voice/design.md` §5（C-AI-HISTORY@3）、`task.md` S29-1～S29-3（本地忽略）。
- 范围：会话列表 offset 分页与 total、侧栏最近历史、AI 完整页历史抽屉（最近/全部/加载更多）、旧会话选择续聊、新对话、`?conversation=` 刷新恢复、同 scope 多会话隔离、加载历史不触发模型/不扣额度。
- 不做：录音/草稿跨设备持久、删除会话、标题另调模型、另建聊天数据源。

## 2. 决策与边界

| 决策 | 口径 |
| --- | --- |
| 分页 | 稳定排序 `updated_at DESC, id DESC`，`offset` 分页，`total` 只计可见会话 |
| 视图隔离 | `conversationViews` 以 `c<id>` / `new<seq>` 为键，异步回包须同时匹配 conversationKey 与账号 epoch |
| 语音写回 | 保留 `setInputForScope(scopeKey, text)`，解析到该 scope 当前选中会话，不新增旁路 |
| 路由 | `?conversation=<id>` 保存选中；无该参数才回退最近一条 |
| 历史入口 | 侧栏最近 5 条 + `/ai?history=1` 抽屉；失败只清空该组 |
| 额度 | 读历史/切换/新对话均不发 `POST /api/agent/chat`，不写用量账本 |

## 3. 实际工具与派工

- 平台：华为云码道（CodeArts）；显示模型 `deepseek-v4.1-flash-1017`，未独立核验。
- 3 个 coding-engineer 并行（后端分页 / store / 界面），主 Agent 冻结契约、验证与留痕；审查并入 AIW-14 的 r2/r3 复核范围（AppLayout/AiConsole 改动）。
- 命令：`PYTHON_BIN="$(command -v python)" python -m pytest tests/backend/test_aiw09_history.py -q`、前后端 `run_all.sh`、`node work/aiw14/browse/verify-browse-r2.cjs`。

## 4. 产出

- 后端：`schemas.py`（`AiConversationListOut.total`）、`services/ai_service.py`（`list_conversations(offset,limit)`）、`routers/agent.py`（`offset`）、`tests/backend/test_aiw09_history.py`。
- 前端：`types/models.ts`（`total`）、`api/agent.ts`（offset）、`stores/aiChat.ts`（`loadHistory/openConversation/newConversation/selectConversation/activeConversationKey`、`conversationViews`）、`views/AiConsole.vue`（历史抽屉/路由恢复）、`layouts/AppLayout.vue`（侧栏真实历史）、`components/nav/HistoryEntry.vue`、`tests/frontend/check_contracts.py` ㉙。
- 证据：`work/aiw14/browse/verify-browse-r2.cjs`、`codearts_proof/reports/aiw14-browser.md` 第 2 次复验节、`codearts_proof/screenshots/aiw14-r2-history.png`。

## 5. 真实问题与处置

1. **首跑无失败**：`test_aiw09_history.py` 直接通过（62 条会话分页/同秒排序/scope/他人不可见/offset 越界）。
2. **同 scope 多会话隔离**：store 由「按 scope」细化为「按 conversationKey」，`byScope` 退化为当前选中镜像；语音写回签名保留。
3. **浏览器缺陷**：从抽屉点会话后地址栏仍为 `/ai`，刷新丢选中 → `AiConsole` 增加选中态写回 `?conversation=`；复验待补（见第 6 节）。
4. **整页直连观察**：整页刷新时侧栏最近/AI 历史有时不发起请求（登录后应用内导航正常），未定级，列入遗留观察。

## 6. 验证与未完成项

- `pytest tests/backend/test_aiw09_history.py` 通过（15 用例）；与 AIW-14 合并 29 passed。
- 后端全量 `run_all.sh` EXIT=0（1446 PASS）；前端 `run_all.sh` EXIT=0（构建 4/4、契约 32/32、语音 21/21）。
- 浏览器复验：侧栏真实会话、抽屉最近/全部、续聊、刷新恢复、用量不变（16→16）、新对话不扣额度、跨账号隔离 PASS；抽屉点击 URL 缺陷已修，最终复验结果以 `aiw14-browser.md` 追加节为准。
- 未验证：真机、真实模型、多设备同步、跨日边界（后端用例覆盖，浏览器未覆盖）。