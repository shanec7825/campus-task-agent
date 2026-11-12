# 阶段 3 · 语音流式 + 彩色文字块

> **归档口径**：本文件是「AI 交互对话整理版」（官方硬性要求 md 格式）。
> 当前状态：**结构已建立，对话原文尚未归档 —— 待该阶段收尾由哨兵整理**。
> 下方「产出」清单全部为本仓库中**真实存在**的文件；「输入 Prompt」只摘录《校园任务协同AI-Agent-开发方案》第 12 章已有的指令要点，**不臆造任何对话内容**。

## 阶段

阶段 3：语音流式实时发布 + 彩色文字块（本项目最有展示效果的高光功能）。

- 体验目标：边说话边看到任务被填好 —— 已解析的原文片段按字段染色，同时对应数据面板用**同一颜色**标注；说到"哎不对，是教四"时识别为更正并打红问号；停止录音后进入悬浮确认态，**不自动落地**。
- 契约依据：`C-VOICEUI@1`、`C-STORE@1`、`C-AGENT@1`（`StreamParseOut`）、`C-SHELL@1`（颜色池）。

## 使用的 Agent

| Agent | 模型 | 本阶段职责 |
|---|---|---|
| 领航员（Leader） | GLM-5.3-Flash | 冻结切片阈值、组件 props/emits、`sliceByPunctuation` 纯函数签名；明确"禁止自动落地"红线 |
| 画师 | **DeepSeek-V4.1-Flash-1017** | `useVoiceComposer` 切片与录音状态机、5 个 VoiceComposer 组件、颜色联动与悬浮确认态 |
| 构造师 | **DeepSeek-V4.1-Flash-1017** | `POST /api/agent/stream/parse`：`parse_sessions` 状态维护与全量草稿合并、`corrections` 覆盖旧值 |
| 哨兵 | **DeepSeek-V4.1-Flash-1017** | 切片边界用例（三个标点 / 无标点）、`is_final` 顺序、浏览器兼容降级、无硬编码色值 |

## 输入 Prompt

- 下发方式：接阶段 2 的连续会话，向 Leader 下发阶段 3 指令（**原文待归档**）。
- 要点（摘自《开发方案》第 12 章阶段 3）：
  1. `composables/useVoiceComposer.ts` 严格按方案 6.4 实现：`webkitSpeechRecognition`（`continuous:true`、`interimResults:true`、`lang:'zh-CN'`）；
  2. 标点切片：`pendingText` 中标点数达到阈值时，取倒数第二个标点前的内容作为 `chunk` 发 `POST /api/agent/stream/parse {session_id, chunk, is_final:false}`；
  3. 停止录音后延迟 800ms 发送剩余文本（`is_final:true`），防转写滞后；
  4. 输入区用自定义块容器（非原生 `textarea`）：解析片段按字段染色（使用 `color-pool.css` 映射），文字块与数据面板同色边框联动；
  5. `corrections` 命中字段打红问号角标 + "检测到更正 X→Y"气泡；
  6. `unresolved` 挂在待确认列表，停止后回填输入区尾部，下次继续切片；
  7. 停止后进入悬浮确认态：块加浮起阴影、可点击弹出修改 popover，点"确认发布"才落地；
  8. 界面提供浏览器兼容提示（仅 Chrome / Edge）；
  9. 构造师实现 `/stream/parse`，按方案 6.5 做 `parse_sessions` 状态维护与全量草稿合并（`corrections` 按 `target` 覆盖并记 `old_value`）；
  10. 验收：说"帮我发个任务，明天下午两点，地点教三，5个人搬桌椅，哎不对是教四"→ 教三被染绿后出现更正问号，最终草稿地点为教四；停止后块悬浮可改，确认发布成功，全程无 JS 报错。
- **对话原文：待该阶段收尾由哨兵整理（占位，禁止编造）。**

## 产出

| 文件 | 说明 |
|---|---|
| `frontend/src/composables/useVoiceComposer.ts` | 录音控制、标点切片（`sliceByPunctuation`）、`is_final` 尾句延迟、兼容性探测 |
| `frontend/src/components/VoiceComposer/VoiceButton.vue` | 录音按钮（不支持时禁用并提示"仅支持 Chrome / Edge"） |
| `frontend/src/components/VoiceComposer/BlockText.vue` | 彩色文字块容器（按 span 染色，禁止硬编码色值） |
| `frontend/src/components/VoiceComposer/FieldPanel.vue` | 任务数据面板，与文字块同字段同色 |
| `frontend/src/components/VoiceComposer/WarnBubble.vue` | 问号气泡（未解析 / 更正 / 审核歧义统一展示，可一键采纳） |
| `frontend/src/components/VoiceComposer/SuspendedConfirm.vue` | 停止录音后的悬浮确认态（块可单点修改，确认才落地） |
| `backend/app/routers/agent.py`（`/stream/parse`） | 流式解析端点：按 `session_id` 累积文本与合并草稿 |
| `backend/app/models.py`（`parse_sessions` 表） | 会话态持久化：`accumulated_text`、`draft`（JSON） |
| `frontend/src/views/PublishPage.vue` | 挂载语音组件与发布确认流程 |
| `frontend/src/utils/colorPool.ts` | `colorForField` 前缀匹配（`extra_tags.` 归入 extra 色） |

## 问题

1. **切片边界**：必须在纯函数层面覆盖「标点数达到阈值」「无标点返回 null」两类用例，避免把半句话提前发给 LLM 造成字段抖动。
2. **尾句滞后**：语音识别回调滞后于说话，停止后立即发送会把最后半句截断；处置为固定 800ms 延迟 + `is_final:true`。
3. **禁止自动落地（红线）**：语音结束不等于任务发布；所有路径必须经过悬浮确认态，防止误发。
4. **更正覆盖语义**：`corrections` 必须按 `target` 覆盖并保留 `old_value`，否则界面无法展示"教三→教四"的对比。
5. **浏览器安全上下文**：Web Speech API 仅在 `localhost` 或 https 下可用，需显式提示而非静默失败；手动发布与文字解析必须保持可用（保底路径）。
6. **对话与截图未归档**：本阶段会话原文、语音联动录屏待补，位置为 `prompts/agent_team_启动指令/`、`screenshots/`、`video/`。