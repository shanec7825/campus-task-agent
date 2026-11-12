# 阶段 2 · 文字版双 Agent 闭环（保底核心）

> **归档口径**：本文件是「AI 交互对话整理版」（官方硬性要求 md 格式）。
> 当前状态：**结构已建立，对话原文尚未归档 —— 待该阶段收尾由哨兵整理**。
> 下方「产出」清单全部为本仓库中**真实存在**的文件；「输入 Prompt」只摘录《校园任务协同AI-Agent-开发方案》第 12 章已有的指令要点，**不臆造任何对话内容**。

## 阶段

阶段 2：实现「提炼助手 + 审核助手」双 Agent 的文字闭环，这是项目的保底核心（不依赖语音也能完整演示）。

- 能力目标：一段自然语言 → 结构化任务草稿（含动态 extras 标签）→ 歧义逐条提问 + 润色建议 → 人工确认后落库 → 自动入库知识库并提示相似任务。
- 契约依据：`C-AGENT@1`、`C-KB@1`、`C-FEAPI@1`、`C-STORE@1`。
- 降级要求：`MAAS_MOCK=1` 或未配置 Key 时走 `mock_fixtures`，全流程离线可演。

## 使用的 Agent

| Agent | 模型 | 本阶段职责 |
|---|---|---|
| 领航员（Leader） | GLM-5.3-Flash | 冻结 Agent 输出 Schema 与 mock 规则，划定后端 Agent 层与前端发布页的写集 |
| 构造师 | **DeepSeek-V4.1-Flash-1017** | `llm_client`（OpenAI 兼容 + json_object + 校验重试）、业务 Prompt 落地、`/extract`、`/review`、`/kb/similar`、发布后入库 |
| 画师 | **DeepSeek-V4.1-Flash-1017** | 统一发布页 AI 模式：字段面板、问号气泡、风格标签、润色一键替换、拆解确认卡片、相似提示条 |
| 哨兵 | **DeepSeek-V4.1-Flash-1017** | Prompt 是否逐字一致、mock 与真实分支是否解耦、JSON 字段读写是否正确、前端是否出现硬编码色值 |

## 输入 Prompt

- 下发方式：接阶段 1 的连续会话，向 Leader 下发阶段 2 指令（**原文待归档**）。
- 要点（摘自《开发方案》第 12 章阶段 2）：
  1. `llm_client.py`：OpenAI SDK 兼容调用 MaaS，`chat_json()` 强制 JSON 输出，Pydantic 校验失败重试一次（temperature 0.3）；
  2. `prompts.py`：按方案 5.1 / 5.2 **原文**写入两段 System Prompt，并在输出 Schema 中并入 `spans` 数组；
  3. 实现 `POST /api/agent/extract` 与 `POST /api/agent/review`；
  4. 实现 `GET /api/kb/similar`（jieba 分词 + tags 加权重叠打分，top3），`POST /api/tasks` 成功后自动写 `kb_entries`；
  5. 画师实现发布页 AI 模式：解析前先查相似（top1 > 0.6 显示提示条）；解析后面板自动填字段并同色联动；`unresolved` 渲染问号气泡可一键采纳；`style_prompt` 显示为"风格要求"；审核歧义同样出气泡；`polished` 可一键替换；`suggested_sub_tasks` 出确认卡片；
  6. LLM 失败 / 超时（30s）必须友好报错并可重试，不能白屏；
  7. 验收：示例句式解析出正确字段、`措辞严谨` 进入 `style_prompt`、出现"下午几点"类问号、给出子任务卡片、二次发布出现相似提示。
- **对话原文：待该阶段收尾由哨兵整理（占位，禁止编造）。**

## 产出

| 文件 | 说明 |
|---|---|
| `backend/app/agents/llm_client.py` | OpenAI 兼容客户端；`is_mock_mode()` 为 mock 判定唯一权威；JSON 输出 + 校验重试 |
| `backend/app/agents/prompts.py` | 提炼助手 / 审核助手 System Prompt（逐字复制方案 §5.1 / §5.2，仅追加 `spans`） |
| `backend/app/agents/extractor.py` | 提炼助手编排：渲染 Prompt → 调用 → 校验 → 返回结构化草稿 |
| `backend/app/agents/reviewer.py` | 审核助手编排：歧义检查 + 风格润色 |
| `backend/app/agents/mock_fixtures.py` | 离线 mock 规则与示例结果（不发外部请求） |
| `backend/app/routers/agent.py` | `/api/agent/extract`、`/api/agent/review`（本阶段）、`/stream/parse`（阶段 3） |
| `backend/app/routers/kb.py` | `GET /api/kb/similar` |
| `backend/app/services/kb_service.py` | 任务入库、jieba 分词、相似度打分 |
| `frontend/src/views/PublishPage.vue` | 统一发布页：手动表单 + AI 模式双轨 |
| `frontend/src/stores/draft.ts` | 草稿状态机：`applyExtract` / `applyStream` / `applyReview` / `setField` / `toTaskPayload` |
| `frontend/src/api/agent.ts`、`api/kb.ts` | Agent 与知识库接口封装 |
| `frontend/src/components/VoiceComposer/FieldPanel.vue` | 任务数据面板（与文字块同字段同色） |

## 问题

1. **Prompt 正文含大量 JSON 花括号**：不能用 `str.format` / f-string 渲染，否则抛 `KeyError`。处置：改用 `str.replace("{CURRENT_TIME}", ...)` 单点替换，并在文件头写明禁止项（详见 `readme/码道应用总结.md` 与 `prompts/prompt迭代记录.md`）。
2. **风格要求误入正文**：若 `措辞严谨一点` 被写进 `details`，会污染任务内容。处置：Prompt 中单列第 5 条「风格剥离」规则并强制放入 `style_prompt`，前端单独渲染为"风格要求"标签。
3. **动态字段扩展**：标准字段之外的要求（如"信息学院要带电脑"）放入 `extra_tags`，前端面板支持增删任意键值对行，避免把字段写死在代码里。
4. **mock 与真实分支耦合风险**：约定 mock 分支不读取渲染后的 Prompt、不实例化 OpenAI 客户端，保证离线演示与真实调用的行为边界清晰。
5. **对话与截图未归档**：本阶段会话原文、解析结果截图待补，位置为 `prompts/业务Agent/`、`debug/`、`screenshots/`。