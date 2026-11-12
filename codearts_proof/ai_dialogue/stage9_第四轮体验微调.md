# 阶段 9 · 第四轮体验微调（C1~C5）

> **归档口径（与 `C-DELIVERY@2` 真实性红线一致）**
> 1. 第 1 节为用户**第四轮实机反馈的原文要点**，逐条保留诉求与现场细节，不改写成「优化体验」这类空话。
> 2. 第 2 节为 **Leader 已下发的核验结论与方案演进**，不含事后推测。核验数字取自**第四轮开工前的基线快照**（标注为「核验时」）；T1~T4 落地后部分基线点已按方案变化，最终以 T6 回归与第 4 节为准。
> 3. 第 4/5 节为 **B 段**，已按 **T6 首轮回归的真实结果**回填：路径与计数**原样引用**回归报告，不修饰、不外推；最终 `VERDICT` 以 `tests/security/ACCEPTANCE.md` 为唯一来源，**本文不写结论**。
> 4. 模型口径：文中的 `DeepSeek-V4.1-Flash` 一律指 **`DeepSeek-V4.1-Flash-1017`**。
> 5. 本轮 5 项反馈收敛为 **C1~C5**；对应派工 **T1~T6**（映射见 §2.1 与 §3）。

---

## 1 用户反馈（第四轮，5 项）

> 说明：以下逐条保留用户原话中的**诉求、现场细节与复现条件**；每条末尾标注对应变更编号与承担任务。

1. 发布页每次都要先看到手动模式，想默认打开智能模式。
2. 全站字号偏小，整体 +1px，别破版。
3. 左侧文字块点击能编辑，但用户不想要这个入口（用右侧字段面板 + 增量解析修改即可）。
4. 每次解析后左侧自动堆一串「AI建议：xxx」紫块，观感冗余；应该只有真的采纳建议时才留痕。
5. 语音「说完最后一个字立刻停止」时，最后几个字会丢 / 重复，且停止后不再自动出审核建议；要求末批必达、不重复、两个 agent 顺序不变。

### 1.1 反馈 1 · 发布页默认先看到手动模式（C1 / T2）

- **用户原话要点**：「发布页每次都要先看到手动模式，想默认打开智能模式。」
- **现场表现**：进入 `/publish` 时默认停在同一页的**手动表单**页签，用户每次都要多切一次才能用到 AI 解析。
- **诉求**：**默认进入 AI 智能模式**；手动模式保留，但降级为**兜底**（AI 不可用或用户主动切换时使用）。
- **归属（C1 / T2）**：把发布页默认页签由 `'manual'` 改为 `'ai'`，并保留手动入口与切换提醒。

### 1.2 反馈 2 · 全站字号偏小，整体 +1px（C2 / T2 + T3）

- **用户原话要点**：「全站字号偏小，整体 +1px，别破版。」
- **现场表现**：全站正文与控件文案统一偏小（Element Plus 默认档位之上没有做任何全局抬升），长时间阅读与投影演示都吃力。
- **诉求**：**整体 +1px**，且**不得破版**（不允许逐处硬改导致行高、按钮宽度、表格列宽错位）。
- **归属（C2 / T2 + T3）**：以全局字号变量整体抬升为主，残留的硬编码 `font-size` 逐处 +1px 为辅；T2 负责主体与高频文件，T3 负责其改动文件内的剩余处。

### 1.3 反馈 3 · 不要左侧文字块点击编辑入口（C3 / T3）

- **用户原话要点**：「左侧文字块点击能编辑，但用户不想要这个入口（用右侧字段面板 + 增量解析修改即可）。」
- **现场表现**：点击左侧彩色文字块会弹出编辑浮层，可原地改字；入口本身可用（第三轮已修好「秒关」），但用户认为**不需要**。
- **诉求**：**移除**该入口；改字一律走**右侧字段面板**与**增量解析**两条既有路径。
- **归属（C3 / T3）**：删除块内编辑浮层、编辑态与外部点击监听，同时拆除 `AiPanel` 中与之成对的编辑回灌链路（详见 §2.4）。

### 1.4 反馈 4 · 解析后自动堆「AI建议：」紫块（C4 / T4）

- **用户原话要点**：「每次解析后左侧自动堆一串『AI建议：xxx』紫块，观感冗余；应该只有真的采纳建议时才留痕。」
- **现场表现**：每次解析（含增量解析）完成后，左侧都会自动追加若干 `ai_applied` 紫色追溯块，文案形如「AI建议：将…改为…」，但用户从未点击过任何「采纳」。
- **诉求**：**解析自动落值不留痕**；只有**真正采纳建议**时才留紫块，避免左侧被无意义的追溯块淹没。
- **归属（C4 / T4）**：删除 `applyExtract` / `applyExtractIncremental` 两处自动生成点，保留全部显式采纳动作的留痕（详见 §2.5）。

### 1.5 反馈 5 · 说完立刻停止会丢字 / 重复且不再出审核（C5 / T1）

- **用户原话要点**：「语音『说完最后一个字立刻停止』时，最后几个字会丢 / 重复，且停止后不再自动出审核建议；要求末批必达、不重复、两个 agent 顺序不变。」
- **现场表现**：用户读完最后几个字立即点停止，末尾内容出现**丢失**或**重复**；并且停止后不再自动产出审核/润色建议。
- **诉求**：**末批必达**（最后几个字不能丢）、**不重复**（同一段话不能被发两遍）、**两个 agent 顺序不变**（提炼助手 → 审核助手），且停止后**仍自动进入审核**。
- **根因与方案演进**：根因是收尾清缓冲与浏览器异步补发最后一帧相撞；方案经历 v1 → v2 两版，v1 被否决，详见 §2.3。

---

## 2 Leader 核验与 C5 方案演进（v1 → v2）

> 本轮 5 项反馈收敛为 **C1~C5**，Leader 逐项核验了代码基线（§2.2），并对 C5 的收尾方案做了 **v1 → v2** 的演进与否决（§2.3）。C3 涉及对第三轮 B5 的口径**反转**（§2.4），C4 给了明确的收紧口径（§2.5）。所有结论均已实际下发，非事后推测。

### 2.1 五项反馈 → C1~C5 收敛

| 编号 | 反馈 | 变更主题 | 承担任务 |
|---|---|---|---|
| **C1** | 反馈 1 | 发布页**默认进入 AI 智能模式**，手动模式降级为兜底 | T2 |
| **C2** | 反馈 2 | 全站字号**整体 +1px**，以全局变量抬升为主、硬编码逐处为辅，不破版 | T2（主体）+ T3（局部） |
| **C3** | 反馈 3 | **移除**左侧文字块点击编辑入口，改字走右侧字段面板 + 增量解析 | T3 |
| **C4** | 反馈 4 | 解析自动落值**不留痕**，只有**显式采纳**才生成紫块 | T4 |
| **C5** | 反馈 5 | 语音收尾改 **onend 驱动 + 保帧不丢 + `stopping` 守卫** | T1 |

### 2.2 Leader 核验确认（第四轮开工前基线快照）

| # | 核验点 | 核验时的基线事实 | 结论 |
|---|---|---|---|
| 1 | **C1** 默认模式 | `frontend/src/views/PublishPage.vue:27` 为 `const activeTab = ref<PublishMode>('manual')` | 默认停在手动页签，**确认** |
| 2 | **C2** 字号分布 | `frontend/src/styles/` 下**仅有** `color-pool.css`（无全局字号基线）；`grep -rno "font-size: 1[2-5]px"` 在 `src/` 的 `*.vue` + `*.css` 中**共 84 处**，散落在 20+ 文件（如 `Profile.vue`、`AiPanel.vue`、`TaskDetail.vue`、`SubTaskTree.vue` 等） | 无统一抬升入口、硬编码分散，**逐处手改有破版风险 ⇒ 需先建全局变量层** |
| 3 | **C3** 块编辑入口 | `components/VoiceComposer/BlockText.vue` 确有 `el-popover` + `v-model:visible="editing"` + `document` 的 `mousedown` 外部点击监听（第三轮 B5 修「秒关」后的形态） | 入口确实存在且成体系，**确认** |
| 4 | **C3** 编辑回灌链路 | `components/Publish/AiPanel.vue` 确有 `blockOverrides` / `resolveBlockFieldKey` / `onEditBlock` / `@edit` 一整套「块内改字 → 回写字段」链路 | 与 `BlockText` 成对，**移除须同时拆**，否则留下无出口的死链路 |
| 5 | **C4** 留痕生成点 | `stores/draft.ts` 的 `ai_applied` 生成点共 **5 处**：`applyExtract` **L1100**、`applyExtractIncremental` **L1130**、`adoptChange` **L1193**、`adoptSuggestion` **L1217**、`adoptPolished` **L1232** | 前 2 处是「解析即留痕」的来源，后 3 处是显式采纳，**确认** |

> **快照口径**：上表为 Leader 在**第四轮开工前**的核验结论，所列行号与计数以该时点为准。书记官撰写本文件时只读核对到：`PublishPage` 默认值、`styles/` 目录构成、`BlockText` 编辑入口、`AiPanel` 回灌链路与 `draft.ts` 的生成点均已按 C1/C3/C4/C5 方案变化。T1~T4 已落地，**实际路径、行号与计数以第 4 节（T6 首轮实测）为准**；A 段只记录开工前核验，不在 A 段断言落地结果。

### 2.3 C5 根因与 v1 → v2 演进

#### 2.3.1 根因定位

- **现象**：用户在**读完最后一个字立刻**停止录音时，末尾几个字**丢失或重复**；且停止后**不再**自动产出审核建议。
- **根因**：`stop()` 在 **800ms** 后调用 `resetLocalBuffer()` **清空本地缓冲**，而 `recognition.stop()` 是**异步**的——浏览器在这之后仍会补发**最后一帧**识别结果。该帧到达时缓冲已空，于是被当作**新内容**重新进入切片流程，与**已经发送的尾片重叠**：重叠部分表现为「重复」，而清空瞬间尚未落入缓冲的末段表现为「丢字」。同时尾片发送与审核触发**解耦**，尾片路径未成功闭合时审核不会被触发，表现为「停止后不出建议」。
- **关键约束**（用户明确要求，方案不得违背）：**末批必达**、**不重复**、**两个 agent 顺序不变**（提炼助手 → 审核助手）。

#### 2.3.2 v1「收尾锁丢弃晚到帧」——**已否决**

- **v1 思路**：`stop()` 后立刻上「收尾锁」，把锁窗口内到达的一切识别帧**直接丢弃**，只发锁前已缓冲的文本作为尾片，锁结束再清缓冲。这样能保证「不重复」，实现也简单。
- **否决理由（Leader 裁定）**：**与用户诉求正面冲突**。用户的复现条件恰恰是「读完最后一个字**马上**停止」——此时最后几个字的识别结果**正好**在锁窗口内到达，丢弃晚到帧 = **把最后几个字丢掉**，「末批必达」直接失守。此外「丢弃」这一动作在原理上无法区分「晚到帧是新说出的内容」还是「晚到帧是上一批的残留」，一刀切必然误伤有效内容。
- **结论**：v1 **作废**，不得以「丢帧」换取「不重复」。

#### 2.3.3 v2「保帧 + onend 结算」——**采用**

- **`stop()` 只做两件事**：置收尾窗口标记 `stopping = true`，并挂一个 **3s 兜底**定时器（`FORCE_FINALIZE_MS`）。**不再**由 `stop()` 自己发尾片，**不再**清空缓冲。
- **`onend` 后延迟 `FINAL_DELAY_MS` 结算**：浏览器 `onend` 到达后，再等一个 `FINAL_DELAY_MS` 窗口（给最后一帧转写留时间），然后把 `pendingText`（即 `fullText` 中尚未发送的部分）**全量**作为尾片发送——**晚到帧已被收进缓冲，因此一并发出去**。
- **期间 `scheduleSlices()` 守卫**：`stopping` 期间识别帧**照常写入缓冲**（保帧），但零散切片被 `if (stopping) return` 拦住，**不发送任何 `is_final=false` 的零散片**，避免「收尾窗口里又冒出一片」造成重复。
- **缓冲全程不清空**：`resetLocalBuffer()` 只在**尾片成功发送之后**（drain 内）执行一次，从根上消除「清空后晚到帧二次切片」。
- **兜底与顺序**：若个别内核丢失 `onend`，3s 兜底强制执行与 `onend` **相同**的结算逻辑（尾片必达）；尾片成功后仍按**提炼助手 → 审核助手**的既有顺序推进，并**自动进入审核**（停止后仍出审核建议）。
- **结论**：v2 同时满足「末批必达」（保帧 + 全量结算）、「不重复」（守卫 + 尾片后清缓冲）、「顺序不变」（沿用既有 agent 链路）三条约束，**采用**。

### 2.4 C3 是对第三轮 B5 的**用户反转**，本轮作废 B5 保留口径

- **第三轮 B5 的口径**：用户当时反馈「点击文字块想改字，编辑框秒关，根本改不了」⇒ 目标是**修好并保留**块内编辑入口（Leader 当时裁定只去掉 `el-popover` 的 `trigger` 双控，保留 `v-model:visible` 单控）。
- **第四轮的变化**：用户明确表示「**能编辑，但用户不想要这个入口**」⇒ 诉求由「修好它」变为「**去掉它**」。
- **本轮裁定**：**作废第三轮 B5「保留块编辑」的口径**。块内编辑入口（浮层 + 编辑态 + `document` 外部点击监听）**整体移除**，`AiPanel` 中与之成对的 `blockOverrides` / `resolveBlockFieldKey` / `onEditBlock` / `@edit` 链路**一并拆除**。改字统一走**右侧字段面板**与**增量解析**两条路径。
- **边界说明**：B5 的「秒关修复」并非被判定为错，而是**随入口一并退场**——不再保留、不再维护；读取与染色等**只读**能力不受影响。

### 2.5 C4 留痕口径

- **口径**：**解析自动落值不留痕 + 全部显式采纳动作留痕**。
  - 「自动落值」指 `applyExtract`（L1100）与 `applyExtractIncremental`（L1130）随解析结果直接写字段并生成 `ai_applied` 紫块 —— **删除这两处生成点**，解析不再产生「AI建议：」追溯块。
  - 「显式采纳」指 `adoptChange`（L1193）、`adoptSuggestion`（L1217）、`adoptPolished`（L1232）三处，分别对应用户点击 AI 建议、问号建议与润色建议的采纳 —— **全部保留**，紫块只在此时出现。
- **用户可见结果**：左侧不再被解析自动堆砌的紫块淹没；只有用户**真正采纳**（AI 建议 / 问号建议 / 润色）时，才留下一条紫块作为可追溯记录。
- **后续收紧口径（预留）**：若日后要收紧为「**仅问号建议采纳才留痕**」，只需改 `adoptChange` 与 `adoptPolished` **两处**（去掉其 `ai_applied` 生成），`adoptSuggestion` 保持不动——本轮**不**收紧到该程度。

---

## 3 派工 Prompt 要点（T1~T6）

> 以下为本轮实际下发的派工要点（每条对应任务 `objective`），并逐条标注该任务**提供（provides）的契约 ID**。T5 即本文件（A 段写第 1~3 节、B 段回填第 4/5 节），**只写文档、不改代码**；T6 在 T1~T4 完成后做回归终验与重打包，**消费上述全部契约**。

| 任务 | 契约（provides） | 派工 Prompt 要点（1~2 句） | 覆盖 | 前置 |
|---|---|---|---|---|
| **T1** · 语音收尾 | **`C-VOICEUI@4 §C`** | 按 **C5 v2** 重构收尾：`stop()` **只**置 `stopping` + 3s 兜底（`FORCE_FINALIZE_MS`），**不**自己发尾片、**不**清缓冲；`onend` 后延迟 `FINAL_DELAY_MS` 把 `pendingText` **全量**作为尾片发送（含晚到帧）；`stopping` 期间 `scheduleSlices()` **守卫**不零散发片、但识别帧照常入缓冲；缓冲只在尾片成功后清一次；尾片成功后仍自动进入审核，**两个 agent 顺序不变** | C5 | —（关键路径起点） |
| **T2** · 默认 AI + 字号主体 | **`C-VOICEUI@4 §A`** + **`C-TYPO@1`** | `PublishPage` 默认页签改 **`'ai'`**（手动降级为兜底，保留切换与未发布草稿提醒）；字号**先建全局层**（Element Plus `--el-font-size-*` 变量整体 +1px，且必须在 Element 样式之后引入），再改主体高频文件的硬编码处，**不得破行高 / 按钮宽 / 表格列宽** | C1、C2（主体） | — |
| **T3** · 删块编辑 + 两文件字号 | **`C-VOICEUI@4 §B` / `§D`**（字号部分消费 `C-TYPO@1`） | **整体移除** `BlockText` 的块内编辑（`el-popover` 浮层 + `editing` 编辑态 + `document` 外部点击监听），并**同步拆除** `AiPanel` 的 `blockOverrides` / `resolveBlockFieldKey` / `onEditBlock` / `@edit` 回灌链路（不留死链路）；同时把这两个文件内**剩余**的 `font-size` 逐处 +1px | C3、C2（局部） | — |
| **T4** · 解析不留痕 | **`C-TRACE@2`** | `draft.ts` 删除 `applyExtract` / `applyExtractIncremental` 两处 `ai_applied` **自动生成点**（解析自动落值不留痕）；**保留** `adoptChange` / `adoptSuggestion` / `adoptPolished` 三处显式采纳留痕；紫块只在真采纳时出现 | C4 | — |
| **T5** · 留痕（A+B 两段） | **`C-DELIVERY@4`** | 只写文档：A 段写本文件第 1~3 节；B 段（本任务）按 T6 首轮实测**回填第 4/5 节**；同步 `LOG.md` 阶段 9 行、`prompt迭代记录.md` 的 **P-009 效果列**、两份 README 的四件事；**不改源码 / tests / plan** | 全部（留痕） | 无（A 段即时可写；B 段依赖 T6 结论） |
| **T6** · 回归终验与重打包 | **消费 `C-VOICEUI@4` + `C-TYPO@1` + `C-TRACE@2` + `C-DELIVERY@4`** | 实机逐条回归 5 项反馈（含「读完马上停」的丢字/重复复现），复跑既有三套件并重新打包；回归后把真实结果交 T5 回填第 4/5 节；发现未修复项如实记录，禁止以计划代替结果 | 全部（验证） | T1~T5 产物 |

> **契约索引**：4 个契约 ID 与 T6 回归项一一对应——`C-VOICEUI@4`（§A 默认 AI / §B 块编辑移除 / §C 语音收尾 / §D 块字号）→ `check_contracts.py` ⑯⑰㉑；`C-TYPO@1` → ⑱⑲；`C-TRACE@2` → ⑳；`C-DELIVERY@4` → `verify_delivery.py` D35~D37。

> 纪律：T5 **A 段**可修改 `stage9_第四轮体验微调.md`、`LOG.md`、`prompt迭代记录.md`、`readme/README.md`、根 `README.md` 这 5 个文件；**B 段（本次收口）只修改前 3 个文件**，不改源码 / tests / plan。**未发生的事项不得写入正文**，禁止编造计数与路径；数字一律原样引用 T6 回归报告。

---

## 4 产出

> **数据口径**：本节路径、计数与结论**原样引用 T6 首轮回归报告**（`tests/security/ACCEPTANCE.md`），未做修饰与外推；两项首轮 FAIL 的成因与处置见 §5 的 **P6**。复核后的最终数字与唯一 `VERDICT` 见 `tests/security/ACCEPTANCE.md`，本文不写结论。
> **路径口径**：以下均为工程根 `campus-task-agent/` 的相对路径；行号以收口时点的实际文件为准。

### 4.1 T1 · 语音收尾（`C-VOICEUI@4 §C`）

`frontend/src/composables/useVoiceComposer.ts`：

- **`stopping`**：收尾窗口标记。`stop()` **只**置该标记并挂兜底定时器，**不再**自己发尾片、**不再**清缓冲；
- **`FORCE_FINALIZE_MS = 3000`**：`onend` 丢失时的 3s 兜底定时器，到点先 `detachRecognition()` 再 `commitStoppedSession()`；
- **`onend` → 延迟 `FINAL_DELAY_MS` → `commitStoppedSession()`**：给最后一帧转写留窗口后**全量**结算 `pendingText`，晚到帧已入缓冲故一并发出去（末批必达）；
- **`scheduleSlices()` 守卫**：首条 `if (stopping) return`，窗口内识别帧照常走 `applyFinal` / `applyInterim`（保帧），但**不**发任何 `is_final=false` 零散片（不重复）；
- **`detachRecognition()`**：兜底路径先解绑回调再结算，避免结算后回调续接；
- **`FINAL_DELAY_MS` 仍为 800**：沿用 `utils/voiceSlicer.ts` 的冻结值，本轮未改切片 5 常量（1 / 12 / 800 / 800 / 200）。

### 4.2 T2 · 默认 AI + 字号主体（`C-VOICEUI@4 §A` + `C-TYPO@1`）

- `frontend/src/views/PublishPage.vue`：`const activeTab = ref<PublishMode>('ai')`（L27），手动模式降级为兜底，两个 `.mode-panel` 用 **`v-show` 保活**（草稿切换不丢）；
- `frontend/src/styles/typography.css`：新建全局字号层 **6 个变量**，逐档 +1 —— `--el-font-size-extra-large: 22px` / `large: 18px` / `medium: 16px` / `base: 15px` / `small: 14px` / `extra-small: 13px`；
- `frontend/src/main.ts`：引入顺序 `element-plus/dist/index.css`（L4）→ `./styles/typography.css`（L5）→ `./App.vue`（L7），保证覆盖 Element Plus 默认值；`./styles/color-pool.css`（L9）保留；
- 约 **20 个 `.vue`** 共 **68 处** `font-size` 逐处 +1（T2 主体施工口径；`BlockText.vue` / `AiPanel.vue` 两文件由 T3 负责）。

### 4.3 T3 · 删块编辑 + 两文件字号（`C-VOICEUI@4 §B/§D` + `C-TYPO@1`）

- `frontend/src/components/VoiceComposer/BlockText.vue`：收敛为**单 span + `el-tooltip`** 纯展示（raw 块 tooltip `disabled`，非 raw 块展示 `meta.reason`）；`el-popover` / `editing` 编辑态 / `document` 外部点击监听**全部删除**；`emit('select')` 保留，点击**只做高亮定位**；
- `frontend/src/components/Publish/AiPanel.vue`：`blockOverrides` / `onEditBlock` / `resolveBlockFieldKey` / `@edit` 回灌链路**整体拆除**，`displayBlocks` 直接 `[...draft.blocks]` + live 虚拟块，不留死链路；
- 两文件字号：`BlockText.vue` 的 `font-size` 集合恰为 **`{15px, 16px}`**；`AiPanel.vue` 实测 **`13px×5 / 14px×6 / 16px×2`**，与基线「原 12/13/15 各 +1」的映射吻合。

### 4.4 T4 · 解析不留痕（`C-TRACE@2`）

`frontend/src/stores/draft.ts`：

- **`appliedTextAt` 删除**：全仓 `appliedTextAt` **0 命中**（含别名）；
- **`ai_applied` 仅剩 3 处显式采纳**：`adoptChange`、`adoptSuggestion`、`adoptPolished`——`pushTraceBlock('ai_applied'` 恰 **3 处**（已按函数边界定位），紫块只在用户真采纳时出现；
- **`applyExtract` / `applyExtractIncremental` 体内 `ai_applied` 0 命中**：解析只落值、不留痕（`applied_texts` 不消费）；
- **`user_note` 保留**：用户补说的原话仍以 `user_note` 追溯块留在左侧；`user_edit`（右侧手改）留痕亦保留。

### 4.5 T5 · 留痕（`C-DELIVERY@4`）

- 本文件（A 段第 1~3 节 + B 段第 4/5 节）、`codearts_proof/LOG.md` 阶段 9 行、`codearts_proof/prompts/prompt迭代记录.md` 的 **P-009 效果列**、`readme/README.md` 与根 `README.md` 的第四轮四项。

### 4.6 T6 · 回归终验与重打包（消费上述全部契约）

- `tests/frontend/check_contracts.py`：**16 → 21 项**——删除第三轮 ⑯ 正向块编辑断言，改为 `check_block_text_v4`（**C3 反向**断言）；修正 ⑦ `check_block_kinds`（**禁** `el-popover`、必须有 `el-tooltip`）；新增 ⑰ C1 默认 AI、⑱ C2 typography/main 基线、⑲ C2 字号梯度与逐文件分布、⑳ C4 留痕、㉑ C5 收尾结构共 6 项；另新增 `function_body()` / `arrow_property_body()` 符号锚定工具，零残留扫描用字符串拼接避免检查器自指假命中；
- `tests/frontend/MANUAL_CHECKLIST.md`：新增 **M23~M28**（默认 AI Tab 激活态与切回草稿、四页字号目视、点击块仅高亮、解析后无紫块、语音真机三保证、连续 10 次立刻停止）；
- `tests/security/{e2e_headless,verify_delivery,pack_delivery,ACCEPTANCE}`：E2E 新增 C1 源码探针 + C2 构建产物探针（46 → 48）；交付新增 **D35~D37**；`pack_delivery.py` 关键文件清单加入本文件；`ACCEPTANCE.md` 为本轮唯一结论来源。

### 4.7 三套件真实结果（T6 首轮）

| 套件 | 命令 / 脚本 | EXIT | PASS | FAIL | 关键输出 |
|---|---|---|---|---|---|
| 后端 6 脚本 | `T10_PORT=8050 T10_KB_PORT=8051 bash tests/backend/run_all.sh` | **0** | **1404** | **0** | `verify_tables` 41 / `test_applications` 413 / `test_api_e2e` 257 / `test_agent_mock` 229 / `test_agent_incremental` 358 / `test_sse_and_reminder` 106 → **主验证 1404 PASS / 0 FAIL**（另有 KB 观测 **25**，不计失败判据） |
| 前端 构建门禁 | `bash tests/frontend/run_all.sh` 步骤 1/2 | **0** | **4** | **0** | `typecheck 通过`；`vite build` 成功（**1703 modules**）；`dist/index.html` **424 字节**；`: any / as any` 0 |
| 前端 契约检查 | 同上 步骤 2/2 | **2** | **20** | **1** | ⑯⑰⑱⑳㉑ PASS；⑲ 报 `AiPanel` 5 处 13px（**断言口径问题**，见 P6） |
| 前端 语音切片单测 | `node tests/frontend/check_voice_slicer.cjs`（手动补跑） | **0** | **13** | **0** | 7 组切片 + 5 常量 1/12/800/800/200 |
| 安全 红线 | `bash tests/security/test_security_redline.sh` | **0** | **11 + 2 PASS-LOCAL** | **0** | Key 字面量 0；前端与 dist 无 `MAAS_API_KEY`；`.gitignore` 6 项；无 `.log/.tmp/备份` 残留 |
| 安全 交付物 | `python tests/security/verify_delivery.py` | **1** | **36** | **1** | **D35** stage9 未收口（缺 4 个契约 ID + B 段未回填）；D36 LOG 阶段 9 ✔、D37 两份 README 四项 ✔ |
| 安全 无头 E2E | `python tests/security/e2e_headless.py` | **0** | **48** | **0** | 46 既有 + C1 默认 AI 源码探针 + C2 构建产物含字号基线变量 |
| **首轮合计** | — | — | **1563** | **2** | 另 **38 DEFERRED**（不计 PASS） |

> 首轮 2 项 FAIL 即 ⑲ 与 D35（详见 §5 P6）：⑲ 经 Leader 裁定为**断言口径错误**（非实现缺陷），D35 的唯一原因就是本文件未收口。复核后的最终数字与唯一 `VERDICT` 见 `tests/security/ACCEPTANCE.md`。

### 4.8 关键实测证据

- **C2 全局字号分布**（`src/**/*.vue`，13/14/15/16 四档）：**`13px×34 / 14px×34 / 15px×7 / 16px×11`**；`font-size: 12px` **全局 0**；`11px×1`（`WarnBubble.vue`）**不在 +1 范围**，按原值保留；
- **`AiPanel.vue`**：**`13px×5 / 14px×6 / 16px×2`**，与基线「原 12/13/15 各 +1」完全吻合（5 处 13px 分别落在 5 个语义类，是正确结果而非残留）；
- **`BlockText.vue`**：`font-size` 集合 = **`{15, 16}`**（raw 15px→16px、追溯 14px→15px）；
- **C5 语音时序**：`frontend/.t1-voice-check` 场景 **A/B/C 共 25 断言 PASS**（A 14 / B 7 / C 4）——尾片**恰好一次**、**无重复 partial**、顺序 **`applyStream → finishStreaming → onAllChunksSent`**、review 通知恰一次；B 覆盖 `onend` 丢失后 3s 兜底同样尾片一次且含晚到文字；C 覆盖空尾片；
- **字号可核对性**：以第三轮 `dist` 组件级 CSS chunk 为迁移前快照，可核对的 **6 组**「原 15px 处数 = 现 16px 新增处数」**全部成立**（`Profile` / `TaskDetail` 组 / `AdminConsole` 组 / `TaskHall` / `LoginPage` / `BlockText`）；
- **块编辑零残留**：扫描 **46 个源文件**，`el-popover` / `editing` / `onEditBlock` / `blockOverrides` / `resolveBlockFieldKey` / `@edit=` **全仓 0**。

### 4.9 重打包

- `PACKED_FILES=162`、`ZIP_SIZE_MB=1.25`、`SENSITIVE_IN_ZIP=0`、`DIST_FILES_IN_ZIP=20`；
- 包内保留本轮正式构建产物 `frontend/dist`（1703 modules、`index.html` 424 字节）与 `codearts_proof/` 全部留痕；排除 `.env` / `*.db` / `.venv` / `node_modules` / `__pycache__` / `dist-t*` / `.tmp*`。

---

## 5 问题与修复

> 每条按「**现象 / 原因 / 让码道怎么修 / 结果**」四段记录；结果为 T6 首轮实测，自动化无法覆盖的部分明确标为 **DEFERRED**（不计 PASS）并给出人工复核入口 `tests/frontend/MANUAL_CHECKLIST.md`。

### P1 · 发布页总是先看到手动模式

- **现象**：进入 `/publish` 默认停在同一页的**手动表单**页签，用户每次要多切一次才能用到 AI 解析。
- **原因**：`PublishPage.vue` 的 `activeTab` 初值为 `ref<PublishMode>('manual')`，默认落手动。
- **让码道怎么修**：初值改 **`'ai'`**；手动模式降级为兜底（AI 不可用或用户主动切换时使用），保留切换入口与未发布草稿提醒；两个面板统一 `v-show`，切换不重建组件、草稿不丢。
- **结果**：`check_contracts.py` ⑰ PASS（`ref<PublishMode>('ai')` + 双 `v-show`），E2E C1 源码探针 PASS，构建门禁通过；浏览器真实 Tab 激活态与「切手动再切回草稿保留」按 `O-D4-1` 记 **DEFERRED M23**。

### P2 · 全站字号偏小

- **现象**：正文与控件文案整体偏小，长时间阅读与投影演示吃力；且各处字号散落，无统一基线。
- **原因**：`frontend/src/styles/` 下**只有** `color-pool.css`，没有全局字号层；`font-size: 12/13/14/15px` 硬编码分散在 20+ 个 `.vue`，逐处手改既无统一入口也容易破版。
- **让码道怎么修**：**先建全局层**——`typography.css` 六变量整体 +1，并在 Element Plus 样式**之后**引入；再对硬编码**逐处** +1，禁止用 `rem` / `vw` / `scale` 等缩放手段，不得破行高、按钮宽、表格列宽。
- **结果**：全局 `font-size: 12px` **0**；实测分布 `13px×34 / 14px×34 / 15px×7 / 16px×11`，11px×1 不在范围按原值保留；可核对的 6 组档位映射全部成立；四页目视不破版为人工项 **M24**。

### P3 · 块编辑入口多余（作废第三轮 B5 的「保留」裁定）

- **现象**：点击左侧彩色文字块会弹出编辑浮层，可原地改字；入口本身可用（第三轮已修好「秒关」），但用户明确表示**不想要**这个入口。
- **原因**：第三轮 B5 的目标是「**修好并保留**」，第四轮用户把诉求**反转**为「**去掉它**」——不是上一轮修错了，而是需求变了。实现侧 `BlockText.vue` 有 `el-popover` + `editing` + `document` 外部点击监听，`AiPanel.vue` 有 `blockOverrides` / `onEditBlock` / `resolveBlockFieldKey` / `@edit` 回灌链路，两者**成对**存在。
- **让码道怎么修**：**整体删除**浮层、编辑态与外部点击监听；同步拆除 `AiPanel` 的回灌链路（否则留下无出口的死链路）；改字统一走**右侧字段面板**与**增量解析**两条既有路径；只读能力（点击高亮、染色、tooltip）保留。
- **结果**：扫描 46 个源文件，`el-popover` / `editing` / `onEditBlock` / `blockOverrides` / `resolveBlockFieldKey` / `@edit=` **全仓 0**；`emit('select')` 保留，**点击仅高亮**；真实点击 10 次不弹框为人工项 **M25**。

### P4 · 解析后自动堆「AI建议：」紫块

- **现象**：每次解析（含增量解析）完成后，左侧自动追加若干 `ai_applied` 紫块，文案形如「AI建议：将…改为…」，而用户从未点击过任何「采纳」。
- **原因**：`stores/draft.ts` 的 `applyExtract` / `applyExtractIncremental` 在落值后**自动**调用 `pushTraceBlock('ai_applied')`，把「解析自动落值」误当成「用户采纳」留痕；另有 `appliedTextAt` 记录自动落值文本，进一步强化了这条错误链路。
- **让码道怎么修**：删除上述**两处自动生成点**与 `appliedTextAt`；**只保留** `adoptChange` / `adoptSuggestion` / `adoptPolished` 三处**显式采纳**留痕；`user_note`（用户原话）与 `user_edit`（右侧手改）不受影响。
- **结果**：`appliedTextAt` 全仓 **0 命中**；`pushTraceBlock('ai_applied'` 恰 **3 处**（store 层 15/15 断言 PASS）；解析后左侧无紫块、三类显式采纳仍出紫块；真实抓包确认发布请求体无「AI建议：」为人工项 **M26**。

### P5 · 语音「说完立刻停止」丢字 / 重复且不再出审核

- **现象**：读完最后一个字**立刻**点停止，末尾几个字**丢失或重复**；停止后**不再**自动产出审核/润色建议。
- **原因**：`stop()` 在 **800ms** 后 `resetLocalBuffer()` 清空本地缓冲，而 `recognition.stop()` 是**异步**的——浏览器随后补发的**最后一帧**到达时缓冲已空，被当作**新内容**重新切片，与**已发送的尾片重叠**（表现为重复）；清空瞬间尚未落入缓冲的末段则表现为**丢字**。同时尾片发送与审核触发**解耦**，尾片未闭合时审核不会被触发。
- **让码道怎么修**：采用 **v2「保帧 + onend 结算」**——`stop()` 只置 `stopping` 并挂 3s 兜底，`onend` 延迟 `FINAL_DELAY_MS` 后**全量**结算尾片，`scheduleSlices()` 守卫不零散发片，缓冲只在尾片成功后清一次。**v1「收尾锁丢弃晚到帧」被否决**：用户复现条件恰是「读完最后一个字马上停止」，锁窗口内到达的正是最后几个字，丢帧等于丢有效内容，且「丢弃」无法区分晚到帧是新内容还是上一批残留。
- **结果**：`.t1-voice-check` 场景 **A/B/C 共 25 断言 PASS**——尾片**恰好一次**、**无重复 partial**、顺序 **`applyStream → finishStreaming → onAllChunksSent`**、review 恰一次；3s 兜底路径同样尾片一次且含晚到文字；`check_contracts.py` ㉑ PASS；真机麦克风三保证（末批必达 / 不重复 / 顺序不变）按 `O-D4-4` 记 **DEFERRED M27/M28**。

### P6 · 终验首轮 2 项 FAIL 的定性

- **现象**：终验哨兵 T6 首轮给出 `VERDICT: FAIL`（2 项）——⑲ 契约检查报 `AiPanel.vue` 5 处 `font-size: 13px`；D35 交付检查报 stage9 未收口（缺 4 个契约 ID、第 4/5 节未回填）。
- **原因**：
  - ⑲ 是**断言口径错误，不是实现缺陷**。`AiPanel` 基线为 `12px×5 / 13px×6 / 15px×2`，按 C2 的 +1 映射（12→13、13→14、15→16）后的**正确结果正是 `13px×5 / 14px×6 / 16px×2`**；首轮断言写成「不得出现 13px」，与 +1 映射**自相矛盾**——若该处真按断言改成 14px，反而会打破「逐处 +1」的梯度。
  - D35 的唯一原因是**本文档未收口**：第 3 节缺 4 个契约 ID，第 4/5 节仍是空段。
- **让码道怎么修**：⑲ 交哨兵**改断言**（判据改为「12px 归零 + `AiPanel` 的 13px 恰 5 处且落在 5 个语义类」），**代码一行未改**；D35 由书记官**回填本文**第 3 节契约 ID 与第 4/5 节（即本次改动）。
- **结果**：断言修正后 ⑲ 按新判据转 PASS（`check_contracts.py` 的 ⑲ 判据已按上述口径更新，代码与 `frontend/src` 未动）；D35 由本次回填闭合；**复核后的最终数字与唯一 `VERDICT` 见 `tests/security/ACCEPTANCE.md`**，本文不写结论。

### P7 · 语音收尾定时器的命名演进

- **现象**：领航员在中间态观察到 `useVoiceComposer.ts` 仍在引用已删除的 `stopTimer`。
- **原因**：v2 施工把单一 `stopTimer` 拆成两个语义不同的定时器——**3s 兜底** `forceFinalizeTimer` 与 **`onend` 结算** `finalizeTimer`；命名替换过程中，注释先于代码更新，留下了旧名。
- **让码道怎么修**：T1 收尾时统一重命名并清除旧引用；注释只保留「由原 `stopTimer` 重命名而来」的**演进说明**，不留废弃别名。
- **结果**：代码内 `stopTimer` 的声明与引用 **0 命中**（仅注释中作为演进说明出现）；`typecheck` 与 `vite build` 通过（构建门禁 4 PASS）。

> **收口说明**：本轮 5 项反馈的**自动化可证部分**全部转绿；DEFERRED 项（真机麦克风、浏览器 DOM 激活态与点击、真实 MaaS 抓包）**不计 PASS**，须按 `MANUAL_CHECKLIST.md` M23~M28 人工复核。最终结论与数字见 `tests/security/ACCEPTANCE.md`。