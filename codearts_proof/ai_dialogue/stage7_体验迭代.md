# 阶段 7 · 体验驱动迭代（第二轮 R12~R17）

> **归档口径（与本轮 `C-DELIVERY@2` 真实性红线一致）**
> 1. 第 1/2/3 节为 **A 段**，内容来自**用户本轮反馈原文要点**与 **Leader 已定契约**（均已实际下发 / 生效），不含推测。
> 2. 第 4/5 节为 **B 段**，已由本任务（书记官）在 T1~T8 真实完成后补写，内容均为真实文件路径与真实命令输出，**不含任何未发生的结果**。
> 3. 未发生的对话与截图统一写「（待人工归档）」并注明原因，禁止编造。
> 4. 模型口径：文档中的 `DeepSeek-V4.1-Flash` 一律指 **`DeepSeek-V4.1-Flash-1017`**。
> 5. 需求编号沿用 `1. 需求` 章的 R12~R17，契约编号以 `2.2.x` 为准。

---

## 1 用户反馈（本轮 6 条，原文要点）

> 说明：以下逐条保留用户原话中的**诉求、现场细节与复现条件**，不改写为"优化体验"这类空话。每条末尾标注对应需求编号与契约。

### 1.1 反馈 1 · AI 模式解析后输入栏被锁定，无法追加增量（对应 R12 / `C-AGENT@2`）

**用户原话要点**：「AI 智能模式解析后左侧输入栏被锁定，只能在右侧字段面板改；希望能继续在已解析的彩色文字块后面输入新内容（如"人数修改为 6 人"），再点解析，把**增量信息**发给模型，模型返回对应数据的修改/补充 JSON 并对齐到文字块。」

- **现场表现**：首次解析完成后，左侧输入区不可再输入，用户若想补一句"人数修改为 6 人"只能去右侧改字段，左侧没有留痕。
- **诉求**：① 追加输入常驻可用；② 只把"这次补的内容"发给模型（增量），而不是让用户重述全句；③ 返回字段级 diff 并落到左侧文字块。
- **验收要点（R12-AC5/AC6/AC7）**：`base_draft.quota=3` + 追加"人数修改为 6 人" ⇒ `draft.quota=6` 且 `changes` 含 `{op:"set", field:"quota", old_value:3, new_value:6, source:"ai"}`；左侧新增 `AI建议：将名额由「3」改为「6」`；追加的原文以 `kind="user_note"` 保留，但不写入任何数据字段。

### 1.2 反馈 2 · 审核建议不可视化、不可追溯且"死板"（对应 R13 / `C-AGENT@2` + `C-TRACE@1`）

**用户原话要点**：「审核建议有价值但不可视化、不可追溯且死板；采纳建议后应像用户输入那样以**变色文字块**显示在输入框（如"AI建议：将 xxx 改为 xxxx"）以便追溯；同时**不能把建议句塞进数据字段**——JSON 必须把「数据值」与「建议语句」分开，右侧只落值。」

- **现场表现**：建议只在右侧气泡/弹层出现，采纳后界面没有任何痕迹，用户无法回溯"这条值是谁改的、从什么改成什么"；更严重的是模型把"建议改为 14:00"整句写进字段，任务标题/时间里出现"建议""改为"字样。
- **诉求**：① 采纳后左侧留一条变色块 `AI建议：将时间由「下午」改为「14:00」`；② `new_value` 必须是**纯数据值**；③ 建议语句只用于展示，不得进入任何字段。
- **验收要点（R13-AC2/AC3/AC4/AC5）**：`new_value` 只含 `14:00` / `教四` / `5` / `搬桌椅` 这类值，禁止"建议/改为/请/或/可/推荐"；未通过纯值校验的候选**宁缺勿污染**（不产出 change，`ambiguities` 保留原提问）；必须有回归断言证明字段里不出现 `AI建议` / `改为` / `用户：` 前缀。

### 1.3 反馈 3 · 用户右侧手改也要可追溯（对应 R14 / `C-TRACE@1`）

**用户原话要点**：「用户在右侧手改也应可追溯：自动在左侧生成"用户：将 xxx 改为 xxxx"、"用户：新建 xxx，内容为 xxxx"等块。」

- **现场表现**：右侧改完值之后，左侧没有任何记录，分不清"这个值是 AI 解析出来的还是我自己改的"。
- **诉求**：三类文案——`用户：将{字段}由「旧」改为「新」`、`用户：新建{字段}，内容为「新」`、`用户：清空{字段}（原「旧」）`；扩展项有 `用户：删除扩展项「key」（原「旧」）`。
- **验收要点（R14-AC4/AC5/AC6）**：追溯块只出现在左侧；右侧字段只含纯数据；用户手改后红色警示角标清除；`toTaskPayload` 必须忽略 `ai_applied` / `user_edit` / `user_note` / `live` 块（防污染），且有自动化断言。

### 1.4 反馈 4 · 语音严重不实时（对应 R15 / `C-VOICEUI@2`）

**用户原话要点**：「语音严重不实时：Edge 下按住说话长时间无反应，直到点"结束录音"才一次性出字。要求"说几个字就转几个字"的实时可视化。」

- **现场表现**：Edge 下按住说话，界面上长时间没有任何文字，只有点"结束录音"后才一次性出现整段；用户无法确认麦克风是否在工作。
- **根因方向（契约已定）**：① 旧规则要求"未处理片段超过多个标点"才切片（P1 的阈值 3 与"取倒数第二个标点"），大量口语没有标点时永不触发；② interim（临时识别）结果没有渲染；③ Edge 静默后会自动触发 `onend`，识别被中断却未续接。
- **诉求**：说几个字就显示几个字；停顿也能出字。
- **验收要点（R15-AC1~AC4/AC7）**：**任一标点即切**（阈值 3 → 1）；无标点时满 **12 字**强制切；连续 **800ms** 无新结果即切；interim 以 `live` 块逐字刷新（≤200ms）；`onend` 在用户未主动停止时自动续接。

### 1.5 反馈 5 · 报名需老师确认 + 8 个名额的 bug（对应 R16 / `C-APPLY@1` + `C-DATA@2`）

**用户原话要点**：「学生可报名符合自己条件的任务，但需**老师确认**才生效；老师可拒绝；老师确认/拒绝之前学生可**撤回报名**。另外名额 bug：任务设 8 个名额，第一个学生报名后第二个就报不了（已用不同账号验证）。」

- **现场表现**：P1 采用「单任务单负责人」模型——第一个学生认领后任务即被占用，第二名学生无法报名，8 个名额等于 1 个。
- **诉求**：① 报名是"申请"，必须发布者（老师）审批才生效；② 老师可拒绝（须填原因）；③ 审批前学生可撤回；④ 名额是**人数上限**，1 人通过后其余人仍可报名。
- **验收要点（R16-AC2/AC3/AC6/AC9）**：`quota=8`、已有 1 名 approved 时第二人仍可提交报名，直到 approved 达到 8；满额返回 `4090`「名额已满」；已 approved 不可撤回；验收通过时**每位 approved 成员各加分**，加分幂等，`credit_logs` 行数等于人数且重复验收不新增。
- **根因结论**：第一轮决策 **D1「单任务单负责人」作废**——这正是 8 名额 bug 的根因。

### 1.6 反馈 6 · AI 交互文档必须按开发方案补齐（对应 R17 / `C-DELIVERY@2`）

**用户原话要点**：「AI 交互文档必须按开发方案 md 补齐，不得缺斤少两，也不得编造。」

- **现场表现**：第一轮留痕只有 6 个阶段文件，本轮（第二轮）的反馈、决策、派工、产出完全没有对应文档，属于"缺斤少两"；同时必须避免为凑数而编造对话。
- **诉求**：① 新增 `stage7_体验迭代.md`，五节齐全；② 同步 `LOG.md`、`prompt迭代记录.md`、`readme/码道应用总结.md`、两份 README；③ **未发生的写占位并说明原因**。
- **验收要点（R17-AC1~AC4）**：五节标题齐全；第 1 节逐条覆盖 6 条反馈；`LOG.md` 新增行且产出路径可 `ls` 验证；`prompt迭代记录.md` 新增 ≥2 条（增量解析 / 纯值）；README 含四项功能；路径、命令、错误码与实现一致。

---

## 2 Leader 决策（契约修订）

> 本轮 6 个契约由 Leader 冻结为基线；P1 的 `C-DATA@1` / `C-AGENT@1` / `C-VOICEUI@1` / `C-DELIVERY@1` 分别由 `@2` 版本**取代**，其余 P1 契约（`C-BOOT@1` / `C-AUTH@1` / `C-TASKS@1` / `C-NOTIFY@1` / `C-SSE@1` / `C-KB@1` / `C-SHELL@1` / `C-UI-COMMON@1`）继续有效。

### 2.1 `C-DATA@2` 数据模型扩展（T1 提供）

- **第 9 张表 `task_applications`**：`id / task_id / user_id / status / reason / created_at / decided_at / decided_by`，唯一约束 `UNIQUE(task_id, user_id)`；`status` 仅允许 `pending | approved | rejected | cancelled`。
- **`tasks` 表结构不变**，但 `assignee_id` 语义降级为「首位 approved（兼容展示与通知）」，`quota` 表示**名额上限**（`null` = 不限）。
- **Schema 扩展**：新增 `ApplicationOut` / `ApplyOut` / `DecisionIn` / `ApplicationItemOut` / `ChangeOut` / `TraceBlock` 等；`TaskOut` 新增派生字段 `applied_count`（pending 数）、`approved_count`（approved 数）、`my_application_status`、`assignee_names`（按报名先后）。
- **`Draft` 扩展**：新增 `trace` 透传字段（后端不生成、不清洗、不排序）；`ExtractIn` 新增 `base_draft` 与 `mode`。
- **只读聚合服务**：新建 `services/application_service.py`（计数 / 成员列表 / 我的状态 / legacy 回退），禁止各路由自行写 SQL。

### 2.2 `C-AGENT@2` 增量解析与建议结构化（T3 提供）

- **`POST /api/agent/extract`** 支持 `ExtractIn{text, base_draft?, mode?}`：`mode="incremental"` 必须带 `base_draft`，否则 `4001`；`mode="full"` 保持 P1 行为（忽略 `base_draft`），保证旧调用不回归。
- **合并规则唯一实现**：`agents/diffing.merge_draft`——标量非空覆盖、`extra_tags` 键级合并、`corrections` 按 `target` 覆盖、`unresolved` **全量替换**、`style_prompt` 非空覆盖、`trace` **原样透传**；`spans` 只返回本次文本片段，不合并历史。
- **`changes` / `applied_texts`**：`changes` 按固定字段顺序产出字段级 diff（`op ∈ set|add_tag|remove_tag`，`source="ai"`）；`applied_texts` 与 `changes` **等长、同序、逐字一致**（后端文案与前端 `formatChangeText` 必须逐字相同，T8 交叉断言）。
- **纯值约束**：`new_value` 只含数据值，`is_pure_value()` 不合格即丢弃该 change 与对应文案（宁缺勿污染）；`reason` 只展示，不落字段。
- **`polished` 不入 `changes`**（D5）：润色是整段文本、含建议语，违反纯值红线；继续以独立字段提供「一键替换」，由前端生成追溯块。

### 2.3 `C-VOICEUI@2` 语音实时（T5 提供）

- **常量写死**：`PUNCT_THRESHOLD=1`（P1 的 3 作废）、`MAX_CHUNK_CHARS=12`、`SILENCE_CUT_MS=800`、`FINAL_DELAY_MS=800`、`LIVE_MAX_REFRESH_MS=200`。
- **切片纯函数** `sliceChunk(pendingText)`（新建 `utils/voiceSlicer.ts`）：第一个标点即切 → 无标点满 12 字强制切 → 否则返回 `null`；旧函数 `sliceByPunctuation` **移除不留别名**（D6）。
- **运行时**：interim 以 `live` 块逐字渲染（≤200ms 节流，不入 `blocks` / `rawText` / `toTaskPayload`）；`onend` 非主动停止时自动 `start()` 续接；`no-speech` 不进入错误态、`aborted` 静默、`network` 提示并停止；`onresult` 内禁止 `await`，切片经串行队列按顺序发送。

### 2.4 `C-APPLY@1` 报名与审批（T2 提供）

- **6 条接口**：`apply` / `apply/withdraw` / `applications`（发布者查看）/ `decide` / `applications/me` / `claim`（兼容别名，等价 `apply`）。
- **报名校验顺序固定**：任务存在 → 非自己发布 → 状态可报名 → 前置依赖已完成 → 无 `pending/approved` 记录 → 名额未满（`approved_count < quota`，`null` 不限）。
- **审批**：通过 ⇒ `approved` + 写 `decided_at/decided_by` + 首位approved 回填 `assignee_id` + `published→claimed` + 通知；**拒绝必须填原因**（否则 `4001`），置 `rejected` 并通知。
- **撤回**：仅 `pending` 可撤回 → `cancelled`；`approved` 返回 `4090`；`rejected/cancelled` 允许重新报名（复用同一行，满足唯一约束）。
- **多负责人**：`progress/submit/checkin` 对每名 approved 成员开放；`verify` 通过时**逐成员加分**，幂等键 `(user_id, task_id)`，重复验收不新增流水。

### 2.5 `C-TRACE@1` 前端追溯块（T4 提供）

- **五类块**：`raw`（解析出的数据块，按字段染色）、`ai_applied`（AI 建议采纳）、`user_edit`（用户手改）、`user_note`（用户追加原文）、`live`（语音 interim 临时块）。
- **4 个追溯色**（既有 8 个键与色值不得修改）：`ai_applied = #8B5CF6`（紫）、`user_edit = #0891B2`（青）、`user_note = #6B7280`（灰）、`live = #3B82F6`（蓝，虚线）。
- **文案模板唯一来源** `utils/traceText.ts`：`AI建议：将{label}由「old」改为「new」` / `AI建议：补充{label}为「new」` / `AI建议：新增扩展项「key」，内容为「value」` / `用户：将…` / `用户：新建…` / `用户：清空…`。
- **防污染**：`toTaskPayload` 只从字段值组装请求体，忽略全部追溯块与 live 块。

### 2.6 `C-DELIVERY@2` 本轮留痕（T7 提供，即本文件）

- 交付 6 个路径：本文件（五节结构）、`LOG.md` 本轮回、`prompt迭代记录.md` ≥2 条、`readme/码道应用总结.md` 体验驱动迭代案例、`readme/README.md` 四项功能、根 `README.md` 保持一致。
- **5 条真实性红线**：只写实际发生的；路径必须 `ls` 可验证；不写 Key/token/.env；问题栏必须真实（无问题写"未记录到问题"）；第 1 节不得缺项。
- P1 `C-DELIVERY@1` 的全部要求（install 脚本、README、开源组件说明、目录结构、无 Key 红线）**继续有效**。

### 2.7 关键决策：第一轮 D1 作废

| ID | 议题 | 决策 | 影响 |
|---|---|---|---|
| **D1（作废）** | P1「单任务单负责人」 | **作废**。用户实测出名额 bug（`quota=8` 第二人无法报名），改为「多名额 + 报名表 + 老师审批」；`assignee_id` 降级为首位 approved 兼容字段 | `C-DATA@2`、`C-APPLY@1`、T1/T2/T6/T8 |
| **D6** | P1「超过多个标点才切 / 取倒数第二个标点」 | **作废**，改为「第一个标点即切 + 12 字强制切 + 800ms 静默切」，函数更名 `sliceChunk` | T5/T8，旧断言必须更新 |
| **D5** | 润色结果是否进 `changes` | **不进入**（含建议语，违反纯值红线），保留独立 `polished` 字段 | T3/T4 |

> 其余裁定（D2 催办调度器本轮不改、D3 `types/models.ts` 归 T1、D4 `BlockText.vue` 归 T4、D7 `ApplicationItemOut`、D8 `VerifyOut`、D9 `assign` 与报名并存）见计划 `2.3.2`。

---

## 3 派工 Prompt 要点（T1~T8）

> 以下为实际下发/生效的派工要点（每条对应任务 `objective`）；完整下发原文见 `codearts_proof/prompts/agent_team_启动指令/`。

| 任务 | 派工 Prompt 要点（1~2 句） | 前置 |
|---|---|---|
| **T1** · 数据层与契约扩展 | 新增 `task_applications` 表（含 `UNIQUE(task_id,user_id)`）与 7 个 Schema 新模型 / 5 个既有模型扩展，把同一契约镜像到 `frontend/src/types/models.ts`，并新建只读聚合服务 `services/application_service.py`（含 legacy 回退）。**`db.py` 只允许追加兼容注释**，不得改连接/会话/建表机制。 | 无（关键路径起点） |
| **T2** · 后端报名审批与多负责人 | 新建 `routers/applications.py`（A1~A5 + `claim` 兼容别名共用同一服务函数），改造 `tasks.py`（`TaskOut` 派生字段、`is_claimable`、`verify` 逐成员加分、`progress/submit` 权限）、`checkin.py`（approved 成员可签到）、`credit.py`（`has_task_bonus` 幂等键）、`notify_service.py`（报名文案 `apply_notice`）。 | T1 |
| **T3** · 后端增量解析与 changes | 新建 `agents/diffing.py`（`merge_draft` / `diff_draft` / `applied_texts_for` / `is_pure_value` / `sanitize_value`），改造 `routers/agent.py` 支持增量入口与三接口 `changes`，改造 `extractor.py` / `reviewer.py` / `mock_fixtures.py`（确定性 changes、`"人数修改为 N 人"` 规则、纯值 suggestion），`prompts.py` **仅在末尾追加**「增量 + 纯值」提示段。 | T1 |
| **T4** · 前端 AI 面板可追溯 | 扩展 `stores/draft.ts`（`Block.kind/meta`、`liveText`、`suggestedChanges`、`applyExtractIncremental`/`adoptChange`/`setField(trace)`/`setLiveText`、`toTaskPayload` 防污染），新建 `utils/traceText.ts`，扩展颜色池（4 个追溯色），改造 `BlockText.vue`（kind 染色 + live 虚线）、`FieldPanel.vue`（手改带旧值）、`AiPanel.vue`（追加输入 + 增量解析 + live 渲染 + 建议采纳）、`PublishPage.vue`。 | T1（编译验证需 T5） |
| **T5** · 前端语音实时化 | 新建纯函数 `utils/voiceSlicer.ts`（`sliceChunk` + 全部常量），重写 `composables/useVoiceComposer.ts` 的切片 / 静默 / live / 续接 / 错误处理，微调 `VoiceButton.vue` 适配新 API；**不修改** `BlockText.vue`（live 渲染由 T4 负责）。 | T1（typecheck 需 T4） |
| **T6** · 前端报名审批 UI | 新建 `api/applications.ts`（5 个函数），调整 `api/tasks.ts` 的 `claimTask` 返回类型，改造 `TaskHall.vue`（报名按钮 + 名额进度）、`TaskDetail.vue`（报名/撤回、成员列表、approved 成员可进度/提交/签到）、`AdminConsole.vue`（审核弹窗：通过 / 拒绝必填原因）、`Profile.vue`（我的报名）、`TaskCard.vue`（多名额置灰原因）。 | T1（编译需 T4/T5） |
| **T7** · 交付物与本轮留痕 | 新建本文件（五节结构）并同步 `LOG.md` / `prompt迭代记录.md` / `readme/码道应用总结.md` / 两份 README 的四项功能说明；A 段写反馈/决策/派工，B 段在 T1~T6 完成后由本任务收口。 | 无（A 段即本文件） |
| **T8** · 回归与终验 | 更新 `tests/backend/*`（旧 `claim` 断言改为 `apply + approve` 语义），新增 `test_applications.py` 与 `test_agent_incremental.py`，扩展 `check_contracts.py` 与新增 `check_voice_slicer.cjs`，更新 `tests/security/{e2e_headless.py,verify_delivery.py,ACCEPTANCE.md}` 并执行构建 / 集成 / 安全 / 终验。 | T1~T7 产物 |

---
## 4 产出（本轮真实文件与命令）

> **口径**：下列路径均为仓库内真实文件，已于 2026-11-11 用 `ls` 逐一核验存在（抽查结果见本轮自检）；下列数字均为 **T8 在本机真实执行** `tests/backend/run_all.sh`、`tests/frontend/run_all.sh`、`tests/security/e2e_headless.py` 的原样输出，未做改写。

### 4.1 T1 · 数据层与契约扩展

| 路径 | 实际产出 |
|---|---|
| `backend/app/models.py` | 共 **9 张表**；新增第 9 张 `task_applications`，含唯一约束 `uq_task_applications_task_user`（`UNIQUE(task_id, user_id)`） |
| `backend/app/schemas.py` | **7 个新模型 + 5 处既有模型扩展**（`ApplicationOut` / `ApplyOut` / `DecisionIn` / `ApplicationItemOut` / `ChangeOut` / `TraceBlock` 等；`TaskOut` 增派生字段、`Draft` 增 `trace`、`ExtractIn` 增 `base_draft`/`mode`，清单见 §2.1） |
| `backend/app/services/application_service.py` | 只读聚合服务（计数 / 成员列表 / 我的状态 / legacy 回退）；报名写入不在此处，禁止各路由自行写 SQL |
| `frontend/src/types/models.ts` | 同一契约的前端类型镜像（归 T1，其余任务只读） |

**实测结果**：`verify_tables.py` **41 PASS**（`run_all.sh` EXIT=0）。

### 4.2 T2 · 后端报名审批与多负责人

| 路径 | 实际产出 |
|---|---|
| `backend/app/routers/applications.py` | 新建 6 条接口（`apply` / `apply/withdraw` / `applications` / `decide` / `applications/me` / `claim` 兼容别名），报名校验顺序固化 |
| `backend/app/routers/tasks.py` | `TaskOut` 派生字段（`applied_count` / `approved_count` / `my_application_status` / `assignee_names`）；`verify` 逐成员加分；`scope=mine` 修复（新增 `_my_participating_task_ids`，条件改为 `or_(publisher, assignee, id.in_(approved))`） |
| `backend/app/routers/checkin.py` | 签到权限放开到每名 approved 成员 |
| `backend/app/services/credit.py` | `has_task_bonus` 幂等键 `(user_id, task_id)`，重复验收不新增流水 |
| `backend/app/services/notify_service.py` | 新增报名类通知文案（申请 / 通过 / 拒绝） |

**实测结果**：`test_applications.py` **413 PASS**、`test_api_e2e.py` **257 PASS**（随 `run_all.sh` EXIT=0）。

### 4.3 T3 · 后端增量解析与 changes

| 路径 | 实际产出 |
|---|---|
| `backend/app/agents/diffing.py` | 新建；承载 `merge_draft` / `diff_draft` / `applied_texts_for` / `is_pure_value` / `sanitize_value`，合并与 diff 的**唯一实现** |
| `backend/app/routers/agent.py` | 支持 `ExtractIn{text, base_draft?, mode?}` 增量入口；`mode="incremental"` 缺 `base_draft` ⇒ `4001`；`mode="full"` 保持 P1 行为 |
| `backend/app/agents/extractor.py`、`reviewer.py`、`mock_fixtures.py`、`prompts.py` | 确定性 `changes`、`"人数修改为 N 人"` 规则、纯值 suggestion；`prompts.py` 仅在末尾追加「增量 + 纯值」提示段 |

**实测结果**：`test_agent_incremental.py` **243 PASS**、`test_agent_mock.py` **217 PASS**。

### 4.4 T4 · 前端 AI 面板可追溯

| 路径 | 实际产出 |
|---|---|
| `frontend/src/utils/traceText.ts` | 文案模板唯一来源（`AI建议：将…` / `用户：将…` / `用户：新建…` / `用户：清空…`） |
| `frontend/src/utils/colorPool.ts`、`frontend/src/styles/color-pool.css` | 颜色池扩展 4 个追溯色（`ai_applied` / `user_edit` / `user_note` / `live`），既有 8 键与色值未改 |
| `frontend/src/stores/draft.ts` | `Block.kind/meta`、`liveText`、`suggestedChanges`、`applyExtractIncremental` / `adoptChange` / `setField(trace)` / `setLiveText` / `toTaskPayload` 防污染 |
| `frontend/src/components/VoiceComposer/BlockText.vue`、`FieldPanel.vue` | `kind` 染色与 `live` 虚线块；右侧手改携带旧值生成 `user_edit` 块 |
| `frontend/src/components/Publish/AiPanel.vue`、`frontend/src/views/PublishPage.vue`、`frontend/src/api/agent.ts` | 追加输入常驻、增量解析调用、`live` 实时渲染、建议采纳落地 |

**实测结果**：前端 `run_all.sh` 中**构建 4 PASS**、**契约 11 PASS**。

### 4.5 T5 · 前端语音实时化

| 路径 | 实际产出 |
|---|---|
| `frontend/src/utils/voiceSlicer.ts` | 新建纯函数 `sliceChunk` + 常量写死：`PUNCT_THRESHOLD=1`、`MAX_CHUNK_CHARS=12`、`SILENCE_CUT_MS=800`、`FINAL_DELAY_MS=800`、`LIVE_MAX_REFRESH_MS=200`；旧 `sliceByPunctuation` 已移除、不留别名 |
| `frontend/src/composables/useVoiceComposer.ts` | 重写切片 / 静默 / `live` / `onend` 续接 / 错误处理；`onresult` 内不 `await`，切片经串行队列按序发送 |
| `frontend/src/components/VoiceComposer/VoiceButton.vue` | 适配新 API；`live` 渲染仍归 T4 的 `BlockText.vue` |

**实测结果**：`check_voice_slicer.cjs` **13 PASS**（含 7 组切片断言 + 5 个常量断言）。

### 4.6 T6 · 前端报名审批 UI

| 路径 | 实际产出 |
|---|---|
| `frontend/src/api/applications.ts` | 新建报名/审批 API 层（5 个函数） |
| `frontend/src/views/TaskHall.vue`、`frontend/src/components/task/TaskCard.vue` | 报名按钮 + 名额进度；多名额置灰原因只用后端派生字段判断，前端不自行算名额 |
| `frontend/src/views/TaskDetail.vue` | 报名 / 撤回、成员列表；approved 成员可提交进度 / 提交 / 签到 |
| `frontend/src/views/AdminConsole.vue` | 审核弹窗：通过 / 拒绝（拒绝必须填原因） |
| `frontend/src/views/Profile.vue` | 新增「我的报名」区块，锚点 `id="my-applications"` |

**实测结果**：T6 收尾会话**十条 UI 断言全过**，`typecheck` 与 `build` 通过；前端 `run_all.sh` 契约项 **11 PASS**。

### 4.7 T7 · 交付物与本轮留痕

- `codearts_proof/ai_dialogue/stage7_体验迭代.md`（本文件，五节齐全；第 4/5 节即本段）
- `codearts_proof/LOG.md`（阶段 7 行：产出列补第 4/5 节，问题列改为 B 段已收口）
- `codearts_proof/prompts/prompt迭代记录.md`（P-005 增量解析 / P-006 纯值约束）
- `readme/码道应用总结.md`（「体验驱动迭代案例」一节；6.6 状态已收口）
- `readme/README.md`、根 `README.md`（四项功能说明：报名审批 / 增量解析 / 追溯块 / 语音实时）

### 4.8 T8 · 回归与终验（真实命令输出）

| 套件 | 命令 | 真实结果 |
|---|---|---|
| 后端 | `bash tests/backend/run_all.sh` | **EXIT=0**：`verify_tables` 41 PASS、`test_applications` 413 PASS、`test_api_e2e` 257 PASS、`test_agent_mock` 217 PASS、`test_agent_incremental` 243 PASS、`test_sse_and_reminder` 106 PASS |
| 前端 | `bash tests/frontend/run_all.sh` | **EXIT=0**：构建 4 PASS、契约 11 PASS、语音 13 PASS |
| 安全 | `python tests/security/e2e_headless.py` | **EXIT=0**：37 PASS |

测试文件（均真实存在）：`tests/backend/{verify_tables,test_api_e2e,test_applications,test_agent_incremental,test_agent_mock,test_sse_and_reminder}.py` + `run_all.sh`；`tests/frontend/{check_contracts.py,check_voice_slicer.cjs}` + `run_all.sh`；`tests/security/{e2e_headless,verify_delivery,ACCEPTANCE}`。

### 4.9 关键行为实测（本轮修复的直接证据）

- **8 名额回归**：`quota=8` 时 student02（第 2 人）报名返回 **200 / pending**；student03（已有 1 名 approved 时的第 3 人）报名返回 **200 / pending**；审批后 `approved_count=3`。
- **双人加分**：验收通过 `credited_user_ids=[2,3]`，各 **+20**；重复验收返回 **4090** 且 `credit_logs` 流水不增。
- **增量解析**：mock 输入「人数修改为 6 人」⇒ `quota` 3→6，仅 **1 条** change，`applied_texts=["AI建议：将名额由「3」改为「6」"]`。
- **红线防污染**：`draft` 8 个字段与 `extra_tags` 均不含「AI建议 / 改为 / 用户：」。

---

## 5 问题与修复（真实发生）

> 下列 8 条均为本轮真实出现并被处置的问题，按「现象 / 原因 / 让码道怎么修 / 结果」逐条记录；未发生的项不虚构。

### P1 8 个名额只有 1 人能报名

- **现象**：任务设 `quota=8`，第一个学生报名后，第二个学生用另一账号报名被「任务已被认领」拦住。
- **原因**：第一轮决策 **D1「单任务单负责人」**把任务与唯一 `assignee_id` 绑定，`quota` 只作展示字段、未参与占用判定。
- **让码道怎么修**：作废 D1；新增 `task_applications` 表（`UNIQUE(task_id,user_id)`）+ 申请/审批状态机，改为「多名额 + 老师审批 + 多负责人加分签到」；`assignee_id` 降级为首位 approved 的兼容字段。
- **结果**：`quota=8` 时第 2、3 人报名成功（200/pending），满额返回 `4090`（详见 §4.9）。

### P2 第 2 名成员在「我的任务」里看不到

- **现象**：学生已被审批为第 2 名 approved 成员，但 `scope=mine` 的任务列表为 0 条。
- **原因**：`scope=mine` 仅按 `assignee_id` 过滤，而 `assignee_id` 只回填首位 approved，其余 approved 成员被漏掉。
- **让码道怎么修**：T2 在 `tasks.py` 追加 `_my_participating_task_ids`，查询条件改为 `or_(publisher, assignee, id.in_(approved_ids))`。
- **结果**：student02 从 0 条变 1 条；legacy（仅 `assignee_id` 的历史任务）行为不变，相关 **7 PASS**。

### P3 语音长时间不出字、点停止才一次性出字

- **现象**：Edge 下按住说话，界面长时间无文字，点「结束录音」后整段一次性出现。
- **原因**：旧规则阈值 3 且「取倒数第二个标点」，无标点口语永不触发切片；interim（临时识别）结果完全不渲染。
- **让码道怎么修**：阈值 **3 → 1**（任一标点即切）+ 满 **12 字**强制切 + **800ms** 静默切；interim 以 `live` 块经 `setLiveText` 实时刷新（≤200ms 节流）；`onend` 非主动停止时自动续接。
- **结果**：`check_voice_slicer.cjs` **7 组切片断言 + 5 个常量断言全部 PASS**（前端语音项 13 PASS）。

### P4 `onend` 续接失效

- **现象**：静默触发 `onend` 后续接不生效，麦克风停止后不再恢复识别。
- **原因**：续接前未复位 `recording` 标志，续接调用的 `start()` 命中「已在录音」短路直接返回。
- **让码道怎么修**：续接前先置 `recording=false`，再延时 **250ms** 重启识别，并在重启路径上处理已停止 / 无实例 / 已卸载三重短路。
- **结果**：修复后 `typecheck` 与 `build` 通过；语音项 13 PASS。

### P5 建议句被写进字段值

- **现象**：任务标题 / 时间等字段出现「建议」「改为」字样，如时间值变成「建议改为 14:00」整句。
- **原因**：初版把模型返回的建议整句直接写入 `new_value`，数据值与展示文案未分离。
- **让码道怎么修**：`ChangeOut` 拆分 `new_value`（纯数据值）与 `applied_texts`（建议语）；新增 `is_pure_value` / `sanitize_value`，不合格候选直接丢弃该 change 与对应文案（宁缺勿污染）；前端以紫色 `ai_applied` 块单独展示建议语。
- **结果**：红线断言 **0 命中**——`draft` 8 个字段与 `extra_tags` 均不含「AI建议 / 改为 / 用户：」。

### P6 T6 会话两轮超时中止

- **现象**：T6 前端报名审批 UI 的会话连续两轮超时中止，页面改造未完成。
- **原因**：单个会话承载任务过重（5 个页面 + API 层 + 类型联动），超出单会话可完成量。
- **让码道怎么修**：Leader 拆分「T6 收尾」由新会话接手——保留已落盘的 `api/applications.ts`、`TaskCard.vue`、`TaskHall.vue`，补写 `TaskDetail.vue` / `AdminConsole.vue` / `Profile.vue` 三页与「我的报名」`id="my-applications"`。
- **结果**：收尾会话**十条断言全过**，`typecheck` 与 `build` 通过。

### P7 T8 首轮工具故障

- **现象**：T8 执行首轮回归时，bash 同类调用触顶上限、`write`/`edit` 出现 5 分钟级超时，批次未跑完。
- **原因**：单批命令与单次写入体积过大，超出工具单次调用上限与超时阈值。
- **让码道怎么修**：改为分批 / 分段写入；对已有文件用 `python` 做精确替换，并逐项重跑套件确认无遗漏。
- **结果**：后端 6 套件、前端 3 套件、安全 3 套件**实测完成**（数字见 §4.8，均 EXIT=0）。

### P8 终验口径待收敛（Key 与本地运行时文件）

- **现象**：终验对 `backend/.env`（含真实 Key）与 `backend/campus.db`（残留数据库文件）判定为红线风险。
- **原因**：两项均为本地演示必需——无 Key 无法走真实模型链路，无 db 无法演示报名/审批数据；二者已被 `.gitignore` 排除、不在交付包内，与「源码写死 Key」性质不同。
- **让码道怎么修**：红线口径改为**分层判定**——源码 Key 字面量禁令（零容忍）+ 本地运行时文件合规（被 `.gitignore` 排除且不入交付包即合规）；该口径修正**在办**。
- **结果**：注明「口径修正后重跑」；当前终验结论见 `tests/security/ACCEPTANCE.md`，本项不作为已修复结论。
