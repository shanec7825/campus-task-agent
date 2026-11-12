# 阶段 8 · 第三轮体验修复（B1~B11）

> **归档口径（与 `C-DELIVERY@2` 真实性红线一致）**
> 1. 第 1/2/3 节为 **A 段**，内容来自**用户第三轮实机反馈原文要点**与 **Leader 已拍板/已下发的决策**（含两处技术核验修正），不含推测。
> 2. 第 4/5 节为 **B 段**，已在 T5 实机回归出结论后由本任务（书记官）按 **T5 实测数字**补写完毕；数字原样引自 `tests/security/ACCEPTANCE.md`，路径经 `[ -f ]` 逐一核验，未填写任何未发生的路径与结论。
> 3. 未发生的对话、截图与命令输出**不写入本文**；无法自动验证的浏览器/麦克风项如实标注 DEFERRED 并指向 `tests/frontend/MANUAL_CHECKLIST.md`，禁止编造。
> 4. 模型口径：文档中的 `DeepSeek-V4.1-Flash` 一律指 **`DeepSeek-V4.1-Flash-1017`**。
> 5. 本轮反馈编号为 **1~11**，对应修复编号 **B1~B11**（映射见 §2.1 与 §3）。

---

## 1 用户反馈（第三轮，11 项）

> 说明：以下逐条保留用户原话中的**诉求、现场细节与复现条件**，不改写为「优化体验」这类空话。每条末尾标注对应修复编号与承担任务。

1. 右侧字段只能改名额，文字打不进去（输入被异步 review 重置）。
2. 增量解析按钮太小、易与全量解析误点。
3. 纯语音模式说了一段话，左侧不出现彩色文字块（只有一行小字），必须先点过解析才显示。
4. 「清空草稿」弹窗没说清会清掉什么、也没给替代做法。
5. 点击文字块想改字，编辑框秒关，根本改不了。
6. 后台放一会儿页面自动刷新，AI 草稿全丢。
7. 语音流式解析每片都重发累计全文，越说越慢、还重复解析前句。
8. 语音说「温柔一点」再补「严谨一点」，风格要求互相覆盖丢失；且语音结束后不会再出审核/润色建议。
9. 点结束录音后底部弹出悬浮确认层，点「取消」会把已说内容全部清空——要求彻底删除该模块。
10. 说「帮我生成一个温柔的活动介绍」，没有生成介绍；且润色不能被自动塞进字段。
11. 小任务也被拆成一堆子任务，且发布时默认带着子任务一起发。

### 1.1 反馈 1 · 右侧文字字段打不进字（对应 B1 / T3）

**用户原话要点**：「右侧字段只能改名额，文字打不进去。」括号内补充：输入被异步 `review` 重置。

- **现场表现**：右侧字段面板中，文字类字段无法正常输入；用户敲入的内容会被随后返回的异步 `review` 结果重置，仅有名额这类数字字段可以改成功。
- **诉求**：输入期间不得被异步审核结果覆盖，用户已敲入的内容必须保留。
- **归属（B1 / T3）**：移除 store 中 `corrections` 的静默写值路径，字段值以 `payload.draft` 为准（连带确认见 §2.3）。

### 1.2 反馈 2 · 「增量解析」按钮太小、易与「全量解析」误点（对应 B2 / T2）

**用户原话要点**：「增量解析按钮太小、易与全量解析误点。」

- **现场表现**：增量解析入口尺寸偏小，且与全量解析入口距离近、主次区分弱，存在误点风险。
- **诉求**：增量解析按钮**放大**，并与全量解析在视觉与文案上明确区分，降低误点概率。
- **归属（B2 / T2）**：`AiPanel.vue` 中两个入口做显式层级区分。

### 1.3 反馈 3 · 纯语音模式不出彩色文字块（对应 B3 / T2）

**用户原话要点**：「纯语音模式说了一段话，左侧不出现彩色文字块（只有一行小字），必须先点过解析才显示。」

- **现场表现**：纯语音模式下说完一段话后，左侧只有一行小字，没有出现按字段染色的彩色文字块；必须先手动点过解析才会显示。
- **诉求**：语音结束后**直接**渲染彩色文字块（按字段染色、与右侧字段同色），不需要用户再点一次解析。
- **归属（B3 / T2）**：语音结束（含 `finishStreaming` 收尾）后把解析结果落到 `blocks`，`kind=raw` 按字段染色。

### 1.4 反馈 4 · 「清空草稿」弹窗语义不清（对应 B4 / T2）

**用户原话要点**：「『清空草稿』弹窗没说清会清掉什么、也没给替代做法。」

- **现场表现**：确认弹窗未说明清空范围（哪些内容会被清掉），也未提供替代做法，用户只能确认或放弃。
- **诉求**：弹窗明确列出将清空的对象，并提供替代做法，让用户不必在「全清」与「不清」之间二选一。
- **归属（B4 / T2）**：弹窗改为清单式说明 + 明确确认文案，并给出替代路径。

### 1.5 反馈 5 · 点文字块改字，编辑框秒关（对应 B5 / T2）

**用户原话要点**：「点击文字块想改字，编辑框秒关，根本改不了。」

- **现场表现**：点击文字块后编辑框刚弹出就立即关闭，用户来不及输入任何字符。
- **诉求**：点击后编辑框稳定保持打开，直到「确定」/「取消」/点击外部才关闭。
- **根因与修正**：根因是 `el-popover` 同时配置 `v-model:visible` 与 `trigger="click"` 的**双控冲突**，详见 §2.2 修正一；**不是** `displayBlocks` 新建对象导致的抖动。

### 1.6 反馈 6 · 后台放一会儿页面自动刷新，草稿全丢（对应 B6 / T3）

**用户原话要点**：「后台放一会儿页面自动刷新，AI 草稿全丢。」

- **现场表现**：页面在后台停留一段时间后自动刷新，AI 草稿内容全部丢失，用户只能重说/重打。
- **诉求**：草稿**自动本地持久化**，刷新或回到前台后恢复，恢复后可继续编辑并直接发布。
- **归属（B6 / T3）**：草稿快照写入本地存储并在初始化时恢复；清空草稿时同步清除快照。

### 1.7 反馈 7 · 语音流式每片重发累计全文，越说越慢（对应 B7 / T1 + T3）

**用户原话要点**：「语音流式解析每片都重发累计全文，越说越慢、还重复解析前句。」

- **现场表现**：语音流式解析的每一片都重发累计全文，句子越长越慢，并重复解析前句。
- **诉求**：只发**本片新增文本**，与**当前草稿**合并；不要重发历史全文，也不要重复解析前句。
- **归属（B7 / T1 + T3）**：改为**顺序增量链式**——第 N 片 = `{text: 本片 chunk, base_draft: 当前草稿}`，上一片结果合并进草稿后才发下一片；`finishStreaming` 只补发最后一片。

### 1.8 反馈 8 · 风格要求互相覆盖、语音结束不出审核/润色（对应 B8 / T1 + T2）

**用户原话要点**：「语音说『温柔一点』再补『严谨一点』，风格要求互相覆盖丢失；且语音结束后不会再出审核/润色建议。」

- **现场表现**：多次说出的风格要求互相覆盖丢失（后一次覆盖前一次）；语音结束后不再出现审核/润色建议。
- **诉求**：多次风格要求**叠加保留**；语音结束**自动**触发审核/润色并给出建议。
- **归属（B8 / T1 + T2）**：`style_prompt` 采用**叠加拼接**（按出现顺序连接，不判语义矛盾）；语音结束自动调用 review，建议以建议条展示。

### 1.9 反馈 9 · 悬浮确认层「取消」清空已说内容（对应 B9 / T2）

**用户原话要点**：「点结束录音后底部弹出悬浮确认层，点『取消』会把已说内容全部清空——要求彻底删除该模块。」

- **现场表现**：点结束录音后底部弹出悬浮确认层，点「取消」会把已说内容全部清空。
- **诉求**：**彻底删除**该悬浮确认模块；结束录音直接回到编辑态，已说内容保留。
- **归属（B9 / T2）**：删除组件、挂载、确认函数与 `markSuspended`；语音结束直接回编辑态并自动审核（详见 §2.1 B9 与 §2.2 修正二）。

### 1.10 反馈 10 · 说「生成活动介绍」没生成，且润色被自动塞进字段（对应 B10 / T1 + T2）

**用户原话要点**：「说『帮我生成一个温柔的活动介绍』，没有生成介绍；且润色不能被自动塞进字段。」

- **现场表现**：说「帮我生成一个温柔的活动介绍」时没有生成介绍；同时润色结果被自动塞进字段。
- **诉求**：能生成活动介绍；介绍与润色**只以建议条展示**，由用户点击采纳，**永不自动落值**。
- **归属（B10 / T1 + T2）**：`polished` / 活动介绍作为独立建议条数据下发；前端只渲染建议条与「采纳」按钮，采纳后才写值并生成追溯块。

### 1.11 反馈 11 · 小任务被过度拆解、发布默认带子任务（对应 B11 / T1 + T2）

**用户原话要点**：「小任务也被拆成一堆子任务，且发布时默认带着子任务一起发。」

- **现场表现**：简单小任务也被拆成一堆子任务；发布时默认带着子任务一起发布。
- **诉求**：拆解收紧，小任务不拆；子任务数量不足时不渲染；发布**默认不勾选**子任务。
- **归属（B11 / T1 + T2）**：拆解前置条件收紧；拆解结果 **≥2 条**才渲染子任务区；发布页子任务复选框默认**未勾选**，随主任务发布需用户显式勾选。

---

## 2 Leader 决策与核验（5 项拍板 + 2 处技术修正）

> 本轮 11 项反馈收敛为 **B1~B11**，其中 5 项由 Leader 拍板定调（B9 / B10 / B11 / B8 / B7），另 2 处为 Leader 对开发方案的技术核验修正（§2.2）。所有结论均已实际下发，非事后推测。

### 2.1 五项拍板

| 编号 | 议题 | 拍板结论 | 影响落点 |
|---|---|---|---|
| **B9** | 是否保留「悬浮确认」 | **彻底删除** `SuspendedConfirm` 模块：组件、`AiPanel.vue` 挂载、`onSuspendedConfirm` 函数、`draft.ts` 的 `markSuspended` 全部删除；语音结束**直接回编辑态并自动审核**；`DraftMode` 的 `'suspended'` 枚举值保留并标注 `deprecated`（不再置位） | T2（`AiPanel.vue`、`SuspendedConfirm.vue`）、T3（`draft.ts`） |
| **B10** | 润色 / 活动介绍是否落值 | **永不自动填充**：`polished` 与「活动介绍」类生成结果只作为**建议条**展示，用户点击「采纳」才写值并生成追溯块，任何路径都不得自动塞进字段 | T1（下发建议条数据）、T2（建议条 UI） |
| **B11** | 拆解粒度与子任务发布 | **拆解收紧**（小任务不拆）；子任务 **≥2 条才渲染**；发布时子任务**默认不勾选**，随主任务发布须显式勾选 | T1（拆解前置校验）、T2（渲染与勾选） |
| **B8** | 风格要求与语音结束审核 | `style_prompt` 采用**叠加拼接**（按顺序连接，**不判语义矛盾**）；语音结束后**自动 review**，产出审核/润色建议条 | T1（拼接与 review）、T2（自动触发与展示） |
| **B7** | 语音流式请求形态 | **顺序增量链式**：第 N 片只发 `{text: 本片 chunk, base_draft: 当前草稿}`，上一片结果合并后才发下一片；**不发累计原文**，不重复解析前句 | T1（链式合并）、T3（`finishStreaming` 收尾） |

#### B9 · 彻底删除 SuspendedConfirm（用户可见行为）

- **删除范围**：`frontend/src/components/VoiceComposer/SuspendedConfirm.vue`（组件文件）、`AiPanel.vue` 中的 import 与模板挂载、`onSuspendedConfirm()` 函数、`stores/draft.ts` 的 `markSuspended()` 及其导出。
- **保留项**：`DraftMode` 联合类型中的 `'suspended'` 保留并标注 `@deprecated`，**任何路径不再置位**；`mode === 'suspended'` 的存量判断不删除（见 §2.2 修正二）。
- **新的用户路径**：点「结束录音」→ 尾片按 `FINAL_DELAY_MS` 发送 → 回到编辑态 → 自动触发审核/润色 → 显示建议条。**不存在**「取消清空」路径，已说内容始终保留。

#### B10 · 润色 / 介绍只出建议条、永不自动落值

- **数据下发**：审核结果中的 `polished` 与活动介绍类文本作为**独立建议条**字段下发，**不进入** `draft` 的任何字段值，也不进入 `changes`（延续第二轮 D5：润色含建议语，违反纯值红线）。
- **前端行为**：只渲染建议条 + 「采纳」按钮；未点击前字段值保持不变；点击采纳后才写值并生成 `ai_applied` 追溯块。
- **验收口径**：生成介绍指令有可见产出；未点击采纳时，所有字段值与 `extra_tags` 均不含建议语整句。

#### B11 · 拆解收紧 + ≥2 条才渲染 + 默认不勾选

- **后端**：拆解前置条件收紧——任务信息过短 / 单动作 / 无需协作时不拆；拆解结果少于 2 条按「不拆解」处理。
- **前端**：子任务区仅在拆解结果 **≥2 条**时渲染；发布页子任务复选框**默认未勾选**，用户显式勾选后才随主任务一并发布。

#### B8 · style_prompt 叠加拼接 + 语音结束自动 review

- **拼接规则**：多次风格要求按出现顺序**连接**（如「温柔一点」+「严谨一点」⇒ 两条并存），**不做**语义矛盾检测、不覆盖、不去重。
- **自动审核**：语音流结束（尾片发送完成）后**自动**调用审核/润色接口，无需用户手动再点解析；建议以建议条展示（与 B10 口径一致）。

#### B7 · 顺序增量链式

- **请求形态**：每片只发本片文本 + `base_draft=当前草稿`；`mode="incremental"`。
- **串行约束**：上一片返回并合并进草稿后，才发送下一片，保证链式顺序与字段最终值一致；禁止并发乱序。
- **收尾**：`finishStreaming` 只补发最后一片，不发累计全文；结束后进入自动审核（B8）。

### 2.2 两处技术修正确认

#### 修正一 · 文字块编辑框秒关：不是 displayBlocks 抖动，是 el-popover 双控

- **方案原判断**：开发方案称「`displayBlocks` 每次 `map` 都新建对象，导致节点重建、编辑框抖动并被关闭」。
- **Leader 核验结论**：**该判断不成立**。实测 `AiPanel.vue` 的 `displayBlocks` 已复用原 block 引用，仅在存在编辑覆盖值时才新建对象，写法为：

  ```ts
  const override = blockOverrides.value[block.id]
  return override === undefined ? block : { ...block, text: override }
  ```

  即 `override` 为 `undefined` 时**原样返回原 block**，不会造成全量节点重建。
- **真实原因**：`BlockText.vue` 的 `el-popover` **同时**配置了 `v-model:visible="editing"` 与 `trigger="click"`（双控）。点击文字块时 `trigger` 把弹层打开，而同一次点击的外部事件/焦点切换又立刻把 `visible` 置回 `false`，表现为「刚弹出就关闭」。
- **修正动作**：**只去掉 `trigger="click"`**，保留 `v-model:visible` 单控（由 `onSelect` 显式置 `editing=true`）；**不改 `displayBlocks`**，避免无收益的渲染层改动。

#### 修正二 · 保留 `DraftMode` 的 `'suspended'` 枚举值（标注 deprecated）

- **方案原要求**：删除 `DraftMode` 中的 `'suspended'` 值。
- **Leader 裁定**：**保留该枚举值并标注 `deprecated`（不再置位）**。原因：`mode` 在多处参与模式判断与分支渲染，直接删除枚举值会连带改动多处 `mode === 'suspended'` 判断，风险大于收益；保留一个永不置位的枚举值，对用户可见行为没有任何影响。
- **实际删除范围**：组件、挂载、确认函数、`markSuspended` **全部删除**；用户可见行为与常规编辑态一致（不回退、不清空）。
- **验证口径**：全局检索 `markSuspended` 无调用；`mode` 永远不会被置为 `'suspended'`；语音结束后界面直接回编辑态。

### 2.3 连带确认 · B1 不影响「教三→教四」既有验收

- **背景**：B1 移除的是 `corrections` 的**静默写值**路径（异步 review 返回后直接改字段，覆盖用户输入）。
- **确认结论**：移除后，字段值仍以 `payload.draft` 为准，后端合并/更正链路不变；因此第二轮已验收的「说『哎不对，是教四』⇒ `location` 由 `教三` 更正为 `教四`」**既有验收不受影响**，无需回退或重写该用例。
- **边界**：本次只改「前端是否静默写值」，不改后端 `corrections` 的 `target` 覆盖语义。

---

## 3 派工 Prompt 要点（T1~T5）

> 以下为本轮实际下发/生效的派工要点（每条对应任务 `objective`）。T4 即本文件的 A 段，**只写文档、不改代码**；T5 在 T1~T4 完成后做回归终验。

| 任务 | 派工 Prompt 要点（1~2 句） | 覆盖反馈 | 前置 |
|---|---|---|---|
| **T1** · 后端 | 关闭 DeepSeek 思考模式以降低首字延迟；语音流式改**顺序增量链式**（只发本片 + 当前草稿）；`style_prompt` 改**叠加拼接**；`polished` / 活动介绍改为**建议条**独立下发且不进字段值；拆解前置收紧、少于 2 条视为不拆 | B7、B8、B10、B11 | 无（关键路径起点） |
| **T2** · 前端面板与语音 | 增量解析按钮放大并与全量解析区分（B2）；纯语音结束直接渲染彩色块（B3）；清空草稿弹窗清单化并给替代路径（B4）；修复文字块编辑框秒关（B5，只去 `trigger`）；语音结束自动审核并按 B8 展示建议条；**彻底删除** `SuspendedConfirm`（B9）；子任务 ≥2 条才渲染、发布默认不勾选（B11） | B2、B3、B4、B5、B8、B9、B11 | T1 |
| **T3** · 状态层与输入 | 修复右侧文字字段被异步 review 重置（B1，移除 `corrections` 静默写值）；草稿自动本地持久化、刷新不丢（B6）；`finishStreaming` 串行补发最后一片、不重发累计全文，并衔接自动审核 | B1、B6、B7（收尾） | T1 |
| **T4** · 留痕（本任务） | 只写文档：新建 `stage8_第三轮体验修复.md` 第 1~3 节；同步 `LOG.md` 阶段 8 行、`prompt迭代记录.md` 的 P-007/P-008、两份 README 的四件事；第 4/5 节在 T5 出结论后补写（B 段已完成）；**不改源码 / tests / plan** | 全部（留痕） | 无（A 段即时可写） |
| **T5** · 回归与终验 | 在实机上逐条回归 11 项反馈并执行既有套件；回归后把真实结果交给 T4 补写第 4/5 节；发现未修复项如实记录，禁止以计划代替结果 | 全部（验证） | T1~T4 产物 |

> 纪律：T4 仅可修改 `stage8_第三轮体验修复.md`、`LOG.md`、`prompt迭代记录.md`、`readme/README.md`、根 `README.md` 这 5 个文件；未发生的事项不得写入正文（无法自动验证的项标 DEFERRED）。

---

## 4 产出（T1~T5 真实文件与命令）

> **口径**：下列路径均为仓库内真实文件，2026-11-11 由书记官用 `[ -f ]` / `grep` 逐一核验（`SuspendedConfirm.vue` 为已删除的历史路径）；下列计数为 **T5 终验在实机执行的原样输出**（`tests/security/ACCEPTANCE.md` §4），数字未改写、未四舍五入。本文不另立终验结论，`VERDICT` 只以 `ACCEPTANCE.md` 第十一节为唯一来源。

### 4.1 T1 · 后端 Agent 链路

| 路径 | 实际产出 |
|---|---|
| `backend/app/agents/llm_client.py` | `THINKING_DISABLED_EXTRA_BODY = {"thinking": {"type": "disabled"}}`，唯一实际下发点在 `_create_completion`；`_is_unsupported_thinking()` 仅在服务端以 **400** 明确拒绝 thinking 参数时命中 ⇒ 去掉 `extra_body` **显式降级**、`logger.warning` 记录原始异常、置 `_thinking_disabled_supported=False` 并重试一次；非 thinking 的 400 仍走 `5001` |
| `backend/app/agents/extractor.py` | `extract_stream(before_draft: Draft, chunk: str, is_final: bool)` **三参**（无 `accumulated_text` / `draft`）；user payload **恰好三键**：`本次新增片段` / `当前已合并草稿` / `是否最终`，**不含**「累计原文」 |
| `backend/app/routers/agent.py` | `session.accumulated_text += chunk` **仅留痕写库**，不再进入 prompt（`parse_sessions` 保留累计原文供审计） |
| `backend/app/agents/diffing.py` | `join_style_prompt(base_style, incoming_style)`：按出现顺序**去重拼接**、不判语义矛盾；`needs_intro(draft)`：`details` 为空且带风格/介绍诉求时为真 |
| `backend/app/agents/reviewer.py` | 介绍**强制校验**：`intro_requested=diffing.needs_intro(draft)`，为真时即使无 `style_prompt` 也**必须**产出完整介绍，结果只作建议条下发、不写字段 |
| `backend/app/agents/prompts.py` | **P3 追加段**两处：语音顺序增量链式（只认上述三键）+ 介绍文案兜底（覆盖「无 style_prompt 则 polished 为 null」） |
| `backend/app/agents/mock_fixtures.py` | 跨片更正保留：`教三` 出现在 `教四` 之前 ⇒ `corrections` 追加 `教三 → 教四`（`old_value` 取 `base_draft.location`） |

**实测结果**：`test_agent_incremental.py` **358 断言 PASS**、`test_agent_mock.py` **229 PASS**（随 `run_all.sh` EXIT=0）。

### 4.2 T2 · 前端面板与语音

| 路径 | 实际产出 |
|---|---|
| `frontend/src/components/Publish/AiPanel.vue` | **B2** 增量按钮改默认尺寸实心（去 `size="small"` / `plain`）并与追加输入框同组；有块时主按钮文案变「重新全量解析」+ `ElMessageBox.confirm` 二次确认。**B3** 纯语音切块：`watch(blocks.length)` 0→非空且 `mode==='streaming'` 时关闭原文编辑器，另补 `onMounted` 恢复即切块。**B4** 清空文案明示「左侧彩色文字块 / 右侧字段值 / AI 建议 / 拆解建议都会消失且无法恢复」并给替代做法。**B8** 语音结束注册 `runReview`（卸载注销）。**B11** 子任务 `≥2` 条才渲染、`includeSubtasks=ref(false)`、仅用户勾选才 `publishAll` |
| `frontend/src/components/Publish/SubTaskCard.vue` | `include?: boolean` **受控**（`:model-value` + `update:include` + 变化复位），默认 `false`；勾选是唯一开启路径 |
| `frontend/src/composables/useVoiceComposer.ts` | 新增 `onAllChunksSent(handler)` 注册表 + `finalizeIfIdle()`：尾片成功后队列排空时**恰好一次**收尾回调，作为「语音结束自动 review」的唯一入口 |
| `frontend/src/components/VoiceComposer/BlockText.vue` | **B5** 单控：`:trigger="[]"` + `:trigger-keys="[]"`，仅 `v-model:visible` 由 `onSelect` 置位；`if (editing.value) return` 守卫；`document` 的 `mousedown`（capture）实现外部点击关闭，`popperClass` 排除浮层内部 |
| `frontend/src/components/VoiceComposer/VoiceButton.vue` | **未改**（保留 P2 基线 `liveHint` 行为） |
| `frontend/src/components/VoiceComposer/SuspendedConfirm.vue` | **本轮删除**（B9；历史路径，源码与测试全仓 0 引用） |

**实测结果**：`check_contracts.py` **16 PASS**（含 ⑫~⑯ 五项第三轮契约）、`check_voice_slicer.cjs` **13 PASS**。

### 4.3 T3 · 状态层与输入

| 路径 | 实际产出 |
|---|---|
| `frontend/src/stores/draft.ts` | **B6** 持久化：`cta_draft_v1` + `DRAFT_VERSION=1`，**300ms** 防抖写盘、版本不符直接丢弃、`resetDraft()` 清键、空草稿不写回、瞬态字段（`streaming` / `warned` 等）不落盘、`blockSeq` 与恢复块对齐；**B7 收尾** `finishStreaming()` 取代 `markSuspended`（`DraftMode` 收窄，`'suspended'` 保留并标 `@deprecated`、永不置位）；**B1** `mergeCorrectionsInternal` 只置 `warned=true`，不再静默写值 |
| `frontend/src/components/VoiceComposer/FieldPanel.vue` | 文本字段本地缓冲 + `TEXT_COMMIT_DEBOUNCE_MS=400` 防抖提交（输入即时可见、落 store 延迟 400ms）；字段聚焦期间**不回填**外部值，失焦立即提交 |

**实测结果**：`check_contracts.py` ⑬ 项 PASS（`cta_draft_v1` / `DRAFT_VERSION=1` / 300ms / `DraftMode` / `finishStreaming` / corrections 只警示 6 条子断言）；B1 的 store 侧 **15 组**字段/更正直言断言通过（浏览器交互侧记 DEFERRED）。

### 4.4 T4 · 留痕产出（本段）

- `codearts_proof/ai_dialogue/stage8_第三轮体验修复.md`（本文件：第 1~3 节 A 段 + 第 4/5 节 B 段）
- `codearts_proof/LOG.md`（阶段 8 行：产出列补第 4/5 节 B 段，问题列改「已收口」）
- `codearts_proof/prompts/prompt迭代记录.md`（P-007 顺序增量链式 / P-008 建议条不自动落值，效果列补真实结果）
- `readme/README.md`、根 `README.md`（第三轮四项功能说明：悬浮确认已删除 / 子任务默认不随主任务发布 / 草稿自动本地持久化 / 关闭 DeepSeek 思考模式）

### 4.5 T5 · 三套件真实计数

| 套件 | 命令 | 真实结果 |
|---|---|---|
| 后端 | `bash tests/backend/run_all.sh` | **EXIT=0**：`verify_tables` 41、`test_applications` 413、`test_api_e2e` 257、`test_agent_mock` 229、`test_agent_incremental` 358、`test_sse_and_reminder` 106 ⇒ **主验证合计 1404 PASS / 0 FAIL**（含 KB 观测 25 共 1429 行） |
| 前端 | `bash tests/frontend/run_all.sh` | **EXIT=0**：构建门禁 4 PASS、`check_contracts` 16 PASS、`check_voice_slicer` 13 PASS |
| 安全红线 | `bash tests/security/test_security_redline.sh` | EXIT=0：**11 PASS + 2 PASS-LOCAL / 0 FAIL** |
| 交付物 | `python tests/security/verify_delivery.py` | EXIT=0：**34 PASS / 0 FAIL**（含 D32 stage8 五节、D33 LOG 阶段 8、D34 README 四项） |
| 无头 E2E | `python tests/security/e2e_headless.py` | EXIT=0：**46 PASS / 0 FAIL** |
| **合计** | — | **1555 通过 / 0 FAIL / 32 DEFERRED / 1 后置** |

- **打包自检**（`tests/security/pack_delivery.py`）：`PACKED_FILES=153`、`ZIP_SIZE_MB=0.92`、`SENSITIVE_IN_ZIP=0`、`DIST_FILES_IN_ZIP=20`，结论 PASS。
- **口径注 1**：上表「1 后置」即本 B 段；本次已按其要求补写，转 PASS 的前置条件已满足，但**整轮 `VERDICT` 仍以 `ACCEPTANCE.md` 第十一节为准**，本文件不另立结论。
- **口径注 2**：打包四项为 T5 记录值；书记官收口时用同一脚本复跑（`--out` 指向临时路径）得 `PACKED_FILES=153` / `SENSITIVE_IN_ZIP=0` / `DIST_FILES_IN_ZIP=20` 与之一致，`ZIP_SIZE_MB` 为 **0.91**（与 0.92 之差 0.01 来自 zip 条目时间戳与 deflate 窗口，不影响文件数与敏感命中两项判据）。

### 4.6 关键实测证据（5 条）

1. **B0 真实 DeepSeek**：关闭思考模式后 `reasoning_content=None`、耗时 **0.89s**（默认 **1.08s** / reasoning **185 字**）。该项为真实 Key 环境的一次实测记录，未纳入自动化判据 —— `ACCEPTANCE.md` §7 O-T5-5 明确记为 DEFERRED（终验环境无 `MAAS_API_KEY`，不伪造 PASS）。
2. **三片链式**：片 2 `changes=['location']`（**不含 `time`**）、片 3 `changes=['quota','extra_tags.工作内容']`（**不含 `time` / `location`**），`extra_tags` 不重复；空尾片 `changes==[]` 且不清空已有 `time`。
3. **review 介绍**：`polished.details` 为完整活动介绍（≥20 字、含标题），**入参 `draft.details` 仍为 `None`**，介绍**不进入** `changes`（`details` / `notes` 均无）—— 证明「只出建议条、永不自动落值」。
4. **payload 三键**：monkeypatch 截获真实 payload 恰为 `本次新增片段` / `当前已合并草稿` / `是否最终`；`backend/app` **32 个 `.py`** 文件中「累计原文」**0 命中**（原文串同样 0 命中）。
5. **前端 16 项契约**含：悬浮确认组件与旧 `markSuspended` action **全仓 0 引用**（扫描 88 个源码/测试文件，历史 markdown 除外）、`cta_draft_v1` + `DRAFT_VERSION=1` + **300ms** + 瞬态字段不落盘、`include` 默认 `false` 且仅勾选才调 `publishAll(mainTask.id)`、`onMounted` 恢复切块 + `streaming` 自动切块 + 语音结束自动 review、`trigger=[]` + `editing` 守卫 + document 外部点击。

---

## 5 问题与修复（真实发生）

> 下列 **11 条**均为本轮真实出现并被处置的问题，按「现象 / 原因 / 让码道怎么修 / 结果」逐条记录；未发生的项不虚构，浏览器/麦克风相关项在 `ACCEPTANCE.md` 中如实标 DEFERRED。

### P1 右侧文字字段打不进字

- **现象**：右侧字段面板中只有名额这类数字字段能改，文字字段敲入后立即被异步 `review` 结果覆盖回原值。
- **原因**：受控输入在失焦时提交，而异步 `review` 返回的 `corrections` 会**静默写值**（直接改 store 字段），两条路径互相踩踏。
- **让码道怎么修**：T3 —— `FieldPanel.vue` 改为本地缓冲 + **400ms** 防抖提交、聚焦期间不回填；`draft.ts` 的 `corrections` 只置 `warned=true`（警示角标），**不再写字段值**，字段值一律以 `payload.draft` 为准。
- **结果**：**15 组** store 断言通过（字段值以 `payload.draft` 为准、corrections 不写值）；真实浏览器交互记 DEFERRED（`MANUAL_CHECKLIST.md` 第 6 节 B1）。

### P2 「增量解析」按钮太小、易与「全量解析」误点

- **现象**：增量解析入口为 `size="small"` + `plain`，且与主按钮不在同一区块，用户常点错后误触发全量重建。
- **原因**：主次层级未定义，两个入口尺寸接近且位置分散；全量解析无二次确认，误点即重建块与字段。
- **让码道怎么修**：T2 —— 增量按钮改默认尺寸实心、去掉 `plain`，与追加输入框同组；主按钮在有块时改文案「重新全量解析」，并加 `ElMessageBox.confirm` 二次确认（明示会丢失已采纳建议与手改记录）。
- **结果**：契约 ⑮/⑯ 项 PASS（`type="primary"`、无 `size`/`plain`、「重新全量解析」+ 确认弹窗均命中）。

### P3 纯语音模式不显示彩色文字块

- **现象**：纯语音说一段话后左侧只有一行小字，必须再点一次解析才出现按字段染色的彩色块。
- **原因**：块容器被 `showEditor = showRawEditor || blocks.length === 0` 门控 —— 截图/原文编辑器优先，`blocks` 从空变非空时不会自动切回块容器。
- **让码道怎么修**：T2 —— `watch(blocks.length)`，0→非空且 `mode==='streaming'` 时把 `showRawEditor` 置 `false`（切到块容器）；另补 `onMounted` 时若已有恢复块则直接切块。
- **结果**：契约 ⑮ 项 PASS（`watch(blocks.length)` 自动切块 + `onMounted` 恢复切块均命中）；真实麦克风侧记 DEFERRED（B3）。

### P4 「清空草稿」提示不清

- **现象**：确认弹窗只问「是否清空」，没说会清掉哪些内容，也没给替代做法，用户只能全清或放弃。
- **原因**：文案未声明清空范围，且未提供「只想改一部分」的替代路径。
- **让码道怎么修**：T2 —— 弹窗改为清单式明示「左侧彩色文字块 / 右侧字段值 / AI 建议 / 拆解建议都会消失且无法恢复」，并补充替代做法：点左侧文字块修改或在右侧字段面板编辑。
- **结果**：契约断言 PASS（文案含「无法恢复」「只想修改部分内容」）。

### P5 文字块编辑框秒关

- **现象**：点击文字块，编辑框刚弹出就关闭，来不及输入。
- **原因**：`el-popover` 同时配置 `v-model:visible="editing"` 与 `trigger="click"` 形成**双控** —— `trigger` 打开后同一次点击的外部事件/焦点切换又立即把 `visible` 置回 `false`。**不是** `displayBlocks` 新建对象导致的抖动（Leader 核验已否定该判断，见 §2.2 修正一）。
- **让码道怎么修**：T2 —— 只去掉 `trigger`（改 `:trigger="[]"` + `:trigger-keys="[]"`），保留 `v-model:visible` 单控、由 `onSelect` 显式置 `editing=true`；补 `if (editing.value) return` 守卫（规划者提出，避免重复打开互相抵消）；`document` 的 `mousedown`（capture）做外部点击关闭，`popperClass` 排除浮层内部点击。
- **结果**：契约 ⑯ 项 PASS（`trigger=[]` + `editing` 守卫 + document 外部点击三项全命中）。

### P6 后台放一会儿刷新，草稿全丢

- **现象**：页面在后台停留后自动刷新，AI 草稿（块、字段、建议）全部丢失。
- **原因**：store 只存在于内存，没有任何落盘路径。
- **让码道怎么修**：T3 —— `localStorage` 持久化，键 `cta_draft_v1` + `DRAFT_VERSION=1`，**300ms** 防抖写盘；版本不符直接丢弃；`resetDraft()` 清键；空草稿不写回；瞬态字段（`streaming` / `warned` 等）不落盘；恢复时 `blockSeq` 与块 id 对齐避免新增块冲突。
- **结果**：契约 ⑬ 项 PASS（`cta_draft_v1` / `DRAFT_VERSION=1` / 300ms / 瞬态不落盘 / 清键 / 版本校验 6 条子断言）；真实刷新恢复记 DEFERRED（B6）。

### P7 语音越说越慢、前句被重复解析

- **现象**：语音流式解析每片都重发从开口到当前的累计全文，句子越长越慢，字段/文字块出现重复。
- **原因**：请求体携带「累计原文」，模型每片都重新解析全部历史。
- **让码道怎么修**：T1 + T3 —— 改为**顺序增量链式**：第 N 片只发 `{本次新增片段, 当前已合并草稿, 是否最终}`，上一片合并进草稿后才发下一片（串行禁并发）；`parse_sessions.accumulated_text` 仅留痕；`finishStreaming()` 只补发最后一片。
- **结果**：三片链式**不重复产出**（片 2 仅 `location`、片 3 仅 `quota` + `extra_tags.工作内容`，`extra_tags` 不重复）；`backend/app` 32 个 `.py` 中「累计原文」**0 命中**；`test_agent_incremental.py` **358 PASS**。

### P8 风格要求互相覆盖 + 语音结束不出 review

- **现象**：先说「温柔一点」又说「严谨一点」，前一条丢失；语音结束后不再出现审核/润色建议。
- **原因**：`style_prompt` 采用**非空即覆盖**，后一次直接替换前一次；语音结束没有触发 review 的入口，只有手动点解析才出建议。
- **让码道怎么修**：T1 + T2 —— `join_style_prompt` 改**去重拼接**（按出现顺序连接、同词不重复、不判语义矛盾）；`useVoiceComposer` 增 `onAllChunksSent` + `finalizeIfIdle()`，队列排空时**恰好一次**回调，`AiPanel.vue` 注册 `runReview`（卸载注销），失败沿用 ErrorState + 重试且不清草稿。
- **结果**：`join_style_prompt` **8 组**纯函数断言 PASS（含 `温柔一点、措辞严谨一点` 重复补充不叠加）；HTTP 层拼接断言 PASS；语音结束自动出 review（契约 ⑮ 项命中 `runReview` 注册/注销）。

### P9 悬浮确认层「取消」清空已说内容

- **现象**：点结束录音后底部弹出悬浮确认层，点「取消」把已说内容全部清空。
- **原因**：`SuspendedConfirm` 的取消分支直接调 `resetDraft()`；同时 P1 的「静默写值」残留让该路径更难察觉已丢数据。
- **让码道怎么修**：T2 + T3 —— **彻底删除**该模块：组件文件、`AiPanel.vue` 的 import/模板挂载、`onSuspendedConfirm()` 函数、`draft.ts` 的 `markSuspended` 全部删除；以 `finishStreaming()` 取代（回到 `'typing'` 并自动 review）；放弃内容只经「清空草稿」这一条显式路径。`DraftMode` 的 `'suspended'` 按 Leader 裁定保留并标 `@deprecated`、永不置位。
- **结果**：契约 ⑫ 项 PASS（组件名与 `markSuspended` 全仓 **0 引用**，扫描 88 个源码/测试文件）；`EXPECTED_DRAFT_ACTIONS` 已由 `markSuspended` 改为 `finishStreaming`。

### P10 说「生成活动介绍」没生成，且润色被自动塞进字段

- **现象**：说「帮我生成一个温柔的活动介绍」没有生成介绍；而润色结果被自动写进字段。
- **原因**：`polished` 仅在有 `style_prompt` 时才产出（`details` 为空时被跳过）；润色/介绍结果与会落值的字段写回路径未分离。
- **让码道怎么修**：T1 + T2 —— `diffing.needs_intro()` 判定「`details` 为空且带风格/介绍诉求」，`prompts.py` 追加介绍兜底段，`reviewer.py` **强制校验**产出完整介绍；介绍与 `polished` **只作建议条**下发，不进入 `draft` 任何字段、也不进入 `changes`；前端 `adoptPolished` 是唯一落值入口，点击「采纳」才写值并生成 `ai_applied` 追溯块。
- **结果**：mock 与 HTTP 双层实测 —— `polished.details` ≥20 字且含标题，**入参 `draft.details` 仍为 `None`**，`changes` 无 `details`/`notes`；纯值红线 4 组断言 PASS。

### P11 小任务也被拆一堆子任务 + 发布默认带子任务

- **现象**：简单任务（如「明天下午搬桌椅」）也被拆成多条子任务；发布时默认勾选子任务一起发。
- **原因**：拆解前置条件未收紧；前端 `includeSubtasks` 无条件为 `true`/未受控，子任务随主任务直接提交。
- **让码道怎么修**：T1 + T2 —— 拆解前置收紧：信息过短/单动作/无需协作时不拆，少于 **2 条按不拆解**处理（返回空数组）；前端子任务区 **≥2 条才渲染**，`include` 改为受控且默认 `false`，只有用户勾选才调 `publishAll(mainTask.id)`，发布后复位。
- **结果**：简单任务 `suggested_sub_tasks == []`、晚会类 2~6 条且 `depends_on=[null,0,1]`（`test_agent_mock.py` **229 PASS** 含此断言）；契约 ⑭ 项 PASS（`include` 默认 `false` + `update:include` + `>=2` 渲染 + 仅勾选才 `publishAll`）；真实勾选交互记 DEFERRED（B11）。