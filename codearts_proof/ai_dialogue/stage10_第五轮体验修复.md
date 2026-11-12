# 阶段 10 · 第五轮体验修复（D1~D4）

> **归档口径（与 `C-DELIVERY@5` 真实性红线一致）**
> 1. 第 1 节为用户**第五轮实机反馈的原文要点**，逐条保留诉求与现场细节，不改写成「优化体验」这类空话。
> 2. 第 2 节为 **Leader 已下发的核验结论与根因定位**，不含事后推测。**行号一律为「A 段核验时点（T2 落地前）的修复前基线」**——T2 施工后同名符号的行号已整体后移，实际落地形态与计数**以第 4 节（T4 回归实测）为准**；符号名（`dedupTail` / `keepSession` / `trimRestartOverlap` / `commitStoppedSession` 等）全程不变，可按符号名在任何时点的文件里自查。
> 3. 第 3 节为本轮实际下发的派工要点（D1~D4 → T1~T4），并列明 3 个契约 ID：`C-DEV@1`（T1 白名单）、`C-VOICEUI@5`（T2 的 D2/D3/D4）、`C-DELIVERY@5`（T3 留痕 + T4 终验），来源为 `campus-task-agent-iteration5/plan.md` 第 2.2.3 节。
> 4. 第 4/5 节为 **B 段收口结果**：第 4 节按 T4 回归实测逐项登记产出与计数，第 5 节登记 6 条真实问题与修复；**未发生的事项一律不写，不以计划代替结果**。
> 5. 模型口径：文中的 `DeepSeek-V4.1-Flash` 一律指 **`DeepSeek-V4.1-Flash-1017`**。

---

## 1 用户反馈（第五轮，2 项）

> 说明：以下逐条保留用户原话中的**诉求、现场细节与复现条件**；每条末尾标注对应变更编号与承担任务。

1. **每次录音都会录两遍**：同一句在左侧文字块与右侧字段里出现两遍；第二遍常常带一个**前导逗号**，例如「资源时长两小时」被录成「资源，时长两小时」。
2. **公网穿透访问前端返回 403 Blocked request**：后端公网 API 已通，前端页面被 Vite 的 Host 校验拦住；用户**已授权放行 `*.takin.cc`**。

### 1.1 反馈 1 · 每次录音都会录两遍（D2 / D3 / D4）

- **用户原话要点**：「每次录音都会录两遍。」——同一句出现两遍，第二遍常带前导逗号，如 `资源时长两小时` → `资源，时长两小时`。
- **现场表现**：用户**没有点「停止录音」**，正常连续说话；一句话说完停顿一下再继续，或只是稍长停顿后接着补一句，最终草稿里同一句出现两遍。第二遍的字面常以逗号开头，把上一句末尾的标点又吐了一遍。用户可以稳定复现，不是偶发。
- **诉求**：同一句**只进草稿一次**；第二遍不得带前导标点；且**不得以牺牲第四轮 C5 的成果为代价**——末批必达（最后几个字不丢）、两个 agent 顺序不变（提炼助手 → 审核助手）、停止后仍自动出审核建议，三条都要保住。
- **归属（D2 / D3 / D4，T2 承担）**：
  - **D2**：`dedupTail` 的清空**只保留在「新建会话」分支**，`keepSession` 续接路径**保留**去重链；
  - **D3**：新增 `trimRestartOverlap` 重叠裁剪纯函数，在续接后的重吐帧上裁掉与前文重复的前缀；
  - **D4**：`commitStoppedSession()` 加首行幂等守卫（收尾只结算一次，作为防御性冗余）。

### 1.2 反馈 2 · 公网穿透访问前端 403 Blocked request（D1）

- **用户原话要点**：「公网穿透访问前端返回 403 Blocked request；后端公网 API 已通、前端被 Vite Host 校验拦截，用户已授权放行 `*.takin.cc`。」
- **现场表现**：通过内网穿透的公网域名（`*.takin.cc` 下的随机子域）打开前端，浏览器拿到的不是页面而是 **403**，正文是 Vite dev server 的拦截提示；同一时刻 **8000 端口的公网 API 是通的**（`/api/health` 有正常响应）。即：**同一台机器、同一条穿透隧道，后端通、前端被拦**。
- **诉求**：公网域名能正常打开前端页面，**不要再返回 403**；放行范围限定在 `*.takin.cc`（用户已授权），**不要图省事开成任意 Host**。
- **归属（D1，T1 承担）**：`frontend/vite.config.ts` 的 `server` 追加 `allowedHosts: ['.takin.cc']`，`port` / `proxy` 等既有配置**一字不动**。

---

## 2 Leader 核验与根因

> 本节分三块：先给**行号口径**（2.1），再分别定位两项反馈的根因（2.2 语音两遍 / 2.4 穿透 403），中间用 **2.3 逐路径排除 C5 收尾时序**把「是不是第四轮改坏了」这个问题一次性关掉，最后收敛变更编号（2.5）。

### 2.1 行号口径（修复前基线快照）

| 项 | 说明 |
|---|---|
| **快照时点** | A 段核验时点（T1 落地后、T2 落地前）的 `frontend/src/composables/useVoiceComposer.ts`，共 **906 行** |
| **引用方式** | 行号仅用于「修复前」定位，**T2 施工后行号整体后移**（文件已增长）；排查时以**符号名**为准 |
| **不写结论** | 本节只写**根因与方案**，不写落地结果；T4 回归得到的实际路径、行号与计数归第 4 节 |

### 2.2 反馈 1 根因：续接时清空去重链 → Edge 重吐前缀被当成新内容

#### 2.2.1 链路（四步）

1. **Edge 会在用户没点停止时自动结束一次识别**。`continuous = true` 并非真无限（L734）；用户停顿后浏览器静默触发 `onend`（L740 起）。此时 `userStopped = false`、`aborting = false`、`recording.value = true` ⇒ `shouldResume = true`（L748），于是 `RESTART_DELAY_MS`（**250ms**，L55）后用 **`start({ keepSession: true })`** 续接（L773）。**用户以为是一次录音，底层其实被拼成了 N 个识别会话。**
2. **`keepSession` 分支只保住了后端会话，没保住前端去重链**。分支内（L709~L720）只跳过了 `store.newSession()`（保留后端 `parse_sessions` 的累计文本），而 **`dedupTail = ''`（L731）写在 `if/else` 之外，无条件执行** —— 注释还写着「不清空 `fullText` / `sentIndex`」（L730），却把去重链这一项漏在了豁免范围之外。
3. **没有锚点，前缀帧就从「覆盖」退化成「追加」**。`dedupTail` 是上一帧 `transcript` 的去重锚点，`applyInterim`（L355~L368）与 `applyFinal`（L371~L386）都靠它做三种判断：相等 ⇒ 直接 `return`；新帧以旧帧为前缀 ⇒ `replaceTail(dedupTail, transcript)` **覆盖尾部**；其余 ⇒ `fullText.value += transcript` **追加**。锚点被清空后，续接实例重吐的前缀帧不再命中「覆盖」分支，而是走 `+=` 被**整段追加**进 `fullText`。
4. **重复文本随后被切成新片发给了后端**。`fullText` 是唯一切片来源，`pendingText = fullText.slice(sentIndex)`；追加进来的重复片段由 `scheduleSlices()`（L395~L404）/ `flushPendingOnSilence()`（L417~L423）当作新内容入队，经 `drain()`（L573~L623）调 `streamParse(sessionId, chunk, isFinal)` 发出。

#### 2.2.2 为什么第二遍常带一个前导逗号

Edge 续接后吐出的首帧**不是从零开始**，而是从停顿点**回退若干字符重吐**（识别引擎重启后的上下文回填）。回退边界通常落在**标点**上，于是重吐片段的片头带着上一句结尾的逗号。用户看到的「资源，时长两小时」正是这个回退边界的痕迹：前半「资源」是回退重吐，后半「时长两小时」是新内容，被拼成了一条。

> 判据意义：这条现象本身就是**续接重吐**的直接指纹——如果重复来自收尾时的双结算，重复文本长度应与尾片相同、且**不带**这种标点回退痕迹。两者成因不同，处置也不同（见 2.3）。

#### 2.2.3 为什么「看起来两遍」会变成「草稿里真两遍」——与第三轮 B7 的链式叠加

第三轮 **B7** 把 `/stream/parse` 改成了**顺序增量链式**：第 N 片**只发**「本片 chunk + 当前草稿」，不发累计全文（见 `prompt迭代记录.md` P-007）。这个改法把「前端多发一片」的代价直接放大：

- 前端多发一片重复文本 ⇒ 后端把它当作「本次新增片段」合进 `base_draft` ⇒ 提炼助手按增量语义**照抄**进字段与 `spans` ⇒ 左侧文字块与右侧字段**都**出现第二遍。
- 结论：**这不是渲染层的错觉，而是草稿里真的存了两份**。B7 本身没有错（它解决了「越说越慢、重复解析前句」），错在前端把重复内容当新片喂给了它——**B7 只保证「不重发历史」，不保证「不进重复内容」**，去重链是前端的第一道闸。

#### 2.2.4 可复现条件（供 T4 回归照抄）

- **不使用**「点停止」路径：正常连续说话，**句间停顿 ≥ 静默切片阈值 800ms**，让 Edge 至少自动续接一次；
- 观察点：左侧文字块是否出现同一句两遍、第二遍是否带前导逗号；右侧字段是否被同一内容覆盖两次；
- 反向对照：同样一句话**一口气不停顿**说完（不触发续接）时**不应**复现——这一条用于把「收尾双结算」与「续接重吐」区分开。

### 2.3 C5 收尾时序逐路径排除（本轮重复**不是**第四轮改坏的）

第四轮 C5 把收尾改成「保帧 + `onend` 结算 + `stopping` 守卫」。为排除「是不是 C5 引入了双结算」，Leader 把**所有能产生尾片的出口**逐条走了一遍（行号为修复前基线）：

| # | 路径 | 代码位置 | 该路径做什么 | 是否可能二次结算 |
|---|---|---|---|---|
| 1 | 用户点停止 `stop()` | L803~L832 | **只**置 `stopping = true`、调 `recognition.stop()`、挂 3s 兜底；**不发尾片、不清缓冲**；首行防重入 `if (forceFinalizeTimer \|\| finalizeTimer) return`（L805） | **否**（本函数唯一不结算的出口） |
| 2 | `onend` → 用户停止分支 | L755~L763 | 先清掉 3s 兜底（L742~L745），再挂 `finalizeTimer` → `commitStoppedSession()` **一次** | **否**（兜底定时器已清，二者互斥） |
| 3 | `onend` → 续接分支 | L765~L777 | 不结算，只 `start({ keepSession: true })`；与分支 2 用 `if (stopping) … return` 互斥 | **否**（不产生尾片） |
| 4 | 3s 兜底 `FORCE_FINALIZE_MS = 3000` | L826~L831 | **仅当 `onend` 丢失**才触发：先 `detachRecognition()` 再 `commitStoppedSession()` | **否**（`onend` 一旦到达即在 L742 被清除，两条路径互斥） |
| 5 | `detachRecognition()` | L638~L646 | 摘掉 `onresult` / `onerror` / `onend` / `onstart` | **否**（摘后晚到帧不再进 `applyFinal` / `applyInterim`，不会二次入队） |
| 6 | 尾片发送失败回退 | L585~L596 | `fullText = item.chunk`、`sentIndex = 0`、`dedupTail = ''`、清队列、`finalizePending = false`、`break` | **否**（只把文本退回待发送区，**不重入结算**；此时 `stopping` 已 false、两个定时器已 null、`recording` 已 false，无路径再进 `commitStoppedSession`） |
| 7 | 空尾片 | L546~L563 | 仅当 `sentChunks > 0` 才置 `finalizePending`，否则只 `finishStreaming()` | **否**（不产生请求） |
| 8 | 故障停机 `haltAfterError()` | L474~L501 | 清两个定时器、`finalizePending = false`、**不发尾片** | **否** |

**排除结论**：C5 的 8 条出口里，**有且只有一条**能真正结算尾片（分支 2，或 `onend` 丢失时的分支 4），**不存在双结算路径**；`resetLocalBuffer()` 只在尾片成功落地后由 `drain()` 调一次（L612~L617），也不会在结算前清空去重链。因此本轮「录两遍」**发生在 C5 明确保留的「续接」这条路径上**（`stopping = false` 的分支 3），是**新暴露的问题**，不是第四轮回归。

**测试口径补充（自省，不是辩解）**：第四轮 `.t1-voice-check` 的 25 条断言验证的是「**单会话内**尾片恰好一次、无重复 partial」，其断言前提里**没有**「Edge 自动续接后再起一轮」这一跨会话场景，所以 C5 全绿与「续接重复」可以同时成立。本轮回归必须补上跨会话断言（见第 3 节 T4）。

**为什么 D4 还要加幂等守卫**：上面 8 条已逐路径排除双结算，但 `commitStoppedSession()` 仍是唯一写尾片的函数、被两条路径调用。D4 在**函数入口**加幂等守卫（已结算或无可结算文本即 `return`），把「依赖调用方互斥」降级为「函数自身幂等」——属**防御性冗余**，不改变已证路径的行为，也就不需要为它重跑第四轮的行为断言。

### 2.4 反馈 2 根因：Vite dev server 的 Host 白名单（`server.allowedHosts`）

- **官方语义**（Vite 官方文档 `Server Options → server.allowedHosts`，A 段核对过原文）：
  - 默认值 `[]`；**仅** `localhost`、`.localhost` 下的域以及**所有 IP 地址**默认放行；
  - 条目以 `.` 开头时，放行「去掉前导点的域名**本身** + 其**全部子域**」（`.example.com` 覆盖 `example.com` / `foo.example.com` / `foo.bar.example.com`）；
  - 该项**未配置**（默认 `[]`）时，dev server 对不匹配的 `Host` 头**直接拦下**（即用户看到的 **403 Blocked request**）；
  - 该项**只在 dev 生效**（该章页首即注明「Unless noted, the options in this section are only applied to dev」）；**HTTPS 下跳过该校验**。
- **本工程的具体成因**：`frontend/vite.config.ts` 原先只配了 `port: 5173` 与 `/api` 代理，**没有 `allowedHosts`** ⇒ 穿透域名（`<随机子域>.takin.cc`）既不是 `localhost`、也不是 IP ⇒ 命中拦截 ⇒ 前端资源（`index.html`、`/src/*`）一个都拿不到。
- **为什么「后端通、前端 403」**：uvicorn（8000）**不做 Host 白名单校验**，穿透域名可直接访问 `/api/health` 等接口；5173 的 Vite dev server 才是唯一设闸者。两个进程、两道不同的门，所以表现为「API 通、页面 403」，而不是全链路不通。
- **为什么是显式 `['.takin.cc']` 而不是 `true`**：`allowedHosts: true` 等于放弃 DNS rebinding 防护（官方以 DANGER 标注，见安全公告 GHSA-vg6x-rcgg-rjx6）——任何站点只要把自己的域名解析到本机，就能读走 dev server 的源码。本轮采用**显式子域白名单**，前导点覆盖随机子域；用户已授权该域，范围最小可用。
- **生产不受影响**：`npm run build` 的静态产物由反向代理（Nginx / Caddy）托管，`allowedHosts` 是 **dev server 选项**，不进入产物；生产的域名 / Host 校验由反代负责。这也解释了「为什么只改一行 vite 配置就够了」，不必动后端 CORS 与部署脚本。

### 2.5 两项反馈收敛为 D1~D4

| 编号 | 对应反馈 | 变更主题 | 承担任务 |
|---|---|---|---|
| **D1** | 反馈 2 | `vite.config.ts` 追加 `server.allowedHosts = ['.takin.cc']`，公网域名不再 403 | T1 |
| **D2** | 反馈 1 | `dedupTail` 清空**移入新建会话分支**，`keepSession` 续接**保留**去重链 | T2 |
| **D3** | 反馈 1 | `voiceSlicer.ts` 新增 `trimRestartOverlap` 重叠裁剪纯函数，续接重吐帧接入 | T2 |
| **D4** | 反馈 1 | `commitStoppedSession()` 首行幂等守卫（防御性冗余） | T2 |

> **与第四轮的关系**：D2~D4 **不推翻** C5 的「保帧 + `onend` 结算」时序（2.3 已证其无双结算），只在**续接**这条 C5 保留的路径上补「去重链不清 + 重吐裁剪 + 收尾幂等」三层保护。切片 5 常量（`PUNCT_THRESHOLD = 1` / `MAX_CHUNK_CHARS = 12` / `SILENCE_CUT_MS = 800` / `FINAL_DELAY_MS = 800` / `LIVE_MAX_REFRESH_MS = 200`）**一律不动**。

---

## 3 派工 Prompt 要点（T1~T4）

> 以下为本轮实际下发的派工要点（每条对应任务 `objective`）。**T3 即本文件（A 段写第 1~3 节、B 段回填第 4/5 节），只写文档、不改代码**；T4 在 T1~T3 完成后做回归终验与重打包。

| 任务 | 变更 | 派工 Prompt 要点（1~3 句） | 覆盖 | **契约** | 前置 |
|---|---|---|---|---|---|
| **T1** · 穿透白名单 | **D1** | `frontend/vite.config.ts` 的 `server` 内**追加** `allowedHosts: ['.takin.cc']`；`port: 5173`、`/api` 代理（`target` / `changeOrigin`）等既有配置**一字不动**；前导点覆盖 `takin.cc` 及其全部子域；**只在 dev 生效**，生产静态托管由反代负责 Host，不得为此改部署脚本或后端 CORS。 | 反馈 2 | **`C-DEV@1`** | — |
| **T2** · 语音续接去重 | **D2 / D3 / D4** | **D2**：把 `start()` 里无条件执行的 `dedupTail = ''`（修复前基线 L731）**移入新建会话分支**，`keepSession` 续接路径**保留去重链**；**D3**：`utils/voiceSlicer.ts` 新增纯函数 `trimRestartOverlap(prevTail, transcript)`，在**续接后的重吐帧**上裁掉与前文重叠的前缀（含前导标点），并限制重吐裁剪只在续接后的前若干帧生效、新建会话不进入该窗口；**D4**：`commitStoppedSession()` 首行加幂等守卫；**切片 5 常量与 C5 的 `stopping` / `onend` / 3s 兜底时序一律不动**。 | 反馈 1 | **`C-VOICEUI@5`** | — |
| **T3** · 留痕（A + B 两段） | — | 只写文档：A 段写本文件第 1~3 节；B 段按 T4 实测**回填第 4/5 节**；同步 `LOG.md` 阶段 10 行、`prompt迭代记录.md` 的 **P-010**、两份 README（穿透白名单 + 续接去重机制）；**不改源码 / tests / plan**。 | 全部（留痕） | **`C-DELIVERY@5`** | 无（A 段即时可写；B 段依赖 T4 结论） |
| **T4** · 回归终验与重打包 | 消费 D1~D4 | 实机复现「不点停止、停顿超 800ms 让 Edge 自动续接 ≥1 次」的跨会话场景，断言同一句**恰好一遍**且第二遍**无前导标点**；对 dev server 用 `Host: <xxx>.takin.cc` 断言**非 403**；复跑既有三套件并重新打包；发现未修复项如实记录，**禁止以计划代替结果**。 | 全部（验证） | **`C-DELIVERY@5`** | T1~T3 产物 |

> **契约登记（B 段已按 `campus-task-agent-iteration5/plan.md` 第 2.2.3 节落盘内容登记，共 3 个）**
> - **`C-DEV@1`** —— `frontend/vite.config.ts` 的 `server.allowedHosts` **前导点子域白名单**（T1 承担，对应 D1）；机检：`check_contracts.py` ㉒、`e2e_headless.py` D1 探针。
> - **`C-VOICEUI@5`** —— **续接去重链保留（D2）+ `trimRestartOverlap` 重吐裁剪（D3）+ 尾片结算幂等（D4）**（T2 承担）；机检：`check_contracts.py` ㉓/㉔/㉕、`e2e_headless.py` D2/D3/D4 探针、`check_voice_slicer.cjs` 的 8 组重吐裁剪用例。
> - **`C-DELIVERY@5`** —— **本轮五节留痕与交付口径**：T3 负责第 1~5 节与 `LOG.md` / `P-010` / 两份 README，T4 负责回归终验与重打包并给出真实计数；机检：`verify_delivery.py` 的 **D38~D40**（D38 即本文件的五节与非空收口）。

> **纪律**：T3 可修改 `stage10_第五轮体验修复.md`、`LOG.md`、`prompt迭代记录.md`、`readme/README.md`、根 `README.md` 这 **5 个文件**，**不改源码 / tests / plan**。**未发生的事项不得写入正文**，禁止编造计数与路径；数字一律原样引用 T4 回归报告。

---

## 4 产出

> **数字口径**：本节计数一律取自 T4 回归报告（`tests/security/ACCEPTANCE.md` 第五轮第一节「统计」与第四节「B 段回填所需的真实计数」）及 T4 任务总结的打包四项，**原样引用、不改写、不外推**。行号以符号名定位（见 §2.1 口径）。

### 4.1 T1 · 穿透白名单（`C-DEV@1`）

`frontend/vite.config.ts`：

- `server` 内新增 **`allowedHosts: ['.takin.cc']`**：`grep -c allowedHosts` **恰好 1 处**，数组**恰好 1 个元素**，键路径落在 `server: {` 与 `proxy: {` 之间；
- 既有配置**一字未动**：`port: 5173`、`target: 'http://127.0.0.1:8000'`、`changeOrigin: true`、`plugins: [vue()]`（由 `check_contracts.py` ㉒ 冻结断言）；
- **未**采用 `allowedHosts: true`：前导点只放开 `takin.cc` 及其全部子域，DNS rebinding 防护仍在（HTTP 403 行为见 §4.5 D1）。

### 4.2 T2 · 续接去重（`C-VOICEUI@5`）

`frontend/src/composables/useVoiceComposer.ts`：

- **D2 去重链保留**：`start()` 的 `if (options.keepSession && sessionId) {` 分支体内 `dedupTail = ''` **0 处**；清空语句只剩 `else {`（新建会话）分支 **1 处**。续接分支改写 `resumedRestartFrames = RESUMED_RESTART_FRAME_BUDGET`，新建会话分支写 `resumedRestartFrames = 0`（不进入重吐窗口）；
- **D3 重吐裁剪**：新增 `trimResumedTranscript(transcript)`——以 `fullText.slice(-64)` 为 `prevTail` 调 `trimRestartOverlap`，只有重叠 **≥2 字**才裁；窗口 `RESUMED_RESTART_FRAME_BUDGET = 3`，每处理一帧非空 `transcript` 消耗 1 次预算；在 `applyInterim` / `applyFinal` 的**追加语句之前**调用，`replaceTail` 内 **0 命中**（覆盖分支不受裁剪影响）；
- **D4 结算幂等**：`commitStoppedSession()` 首条有效语句为 **`if (!stopping) return`**，其后五步顺序 `pendingText → sentIndex → stopping = false → enqueue(tail, true) → clearLiveText` 未变；
- **O-T4-5-1 补修**：`resetLocalBuffer()` 在清 `fullText` / `sentIndex` / `dedupTail` 的同时**补 `resumedRestartFrames = 0`**（T2 已补修，见 §5 P4）。

`frontend/src/utils/voiceSlicer.ts`：

- 新增导出 **`trimRestartOverlap(prevTail, transcript)`**：取最长「`prevTail` 后缀 = `transcript` 前缀」重叠并裁掉；`prevTail` 为空 / `transcript` 为空 / 无重叠 ⇒ 原样返回，全重叠 ⇒ 返回空串；
- **零 import**（含类型 import）不变，仍是 `tsc` 可单编译、Node 可直跑的纯函数。

### 4.3 T3 · 留痕（`C-DELIVERY@5`）

- 本文件：A 段第 1~3 节（反馈原文 / 根因 / 派工与契约）+ B 段第 4/5 节（产出与问题）；
- `codearts_proof/LOG.md` 阶段 10 行（产出列与问题列）；
- `codearts_proof/prompts/prompt迭代记录.md` 的 **P-010 效果列**；
- `readme/README.md` 与根 `README.md`：穿透白名单（`allowedHosts` / `takin.cc`）与语音续接去重（`dedupTail` 续接保留）两件事。

### 4.4 T4 · 三套件、桩测与打包（消费 D1~D4）

| 套件 | 命令 / 脚本 | EXIT | PASS | FAIL | 关键输出 |
|---|---|---|---|---|---|
| 后端 6 脚本 | `T10_PORT=8060 T10_KB_PORT=8061 bash tests/backend/run_all.sh` | **0** | **1404** | **0** | `verify_tables` 41 / `test_applications` 413 / `test_api_e2e` 257 / `test_agent_mock` 229 / `test_agent_incremental` 358 / `test_sse_and_reminder` 106；另 KB 观测 **25**（不计失败判据） |
| 前端 构建门禁 | `bash tests/frontend/run_all.sh` 步骤 1 | **0** | **4** | **0** | typecheck + `vite build` + `dist` + 无 `any` |
| 前端 契约检查 | 同上 步骤 2（`check_contracts.py`） | **0** | **25** | **0** | 21 既有 + ㉒/㉓/㉔/㉕ 新增（D1~D4） |
| 前端 语音切片 | 同上 步骤 3（`check_voice_slicer.cjs`） | **0** | **21** | **0** | 7 组切片 + **8 组 `trimRestartOverlap`** + 5 常量 + 1 旧名零命中 |
| 安全 红线 | `bash tests/security/test_security_redline.sh` | **0** | **11 + 2 PASS-LOCAL** | **0** | A 层 0 命中；B 层本地运行时文件合规 |
| 安全 交付物 | `python tests/security/verify_delivery.py` | **1** | **39** | **1** | 唯一 FAIL = **D38**（本文件第 4/5 节在 T4 执行时尚未回填，即本次回填的对象） |
| 安全 无头 E2E | `python tests/security/e2e_headless.py` | **0** | **52** | **0** | 48 既有 + **D1~D4 四个源码探针全 PASS** |
| 纯逻辑桩测 | `node build.mjs && node bundle.mjs`（`frontend/.t1-voice-check`） | **0** | **25** | **0** | 场景 A14 + B7 + C4，**25/25** |
| **合计** | — | — | **1583** | **1** | 1404+4+25+21+13+39+52+25；另 **41 DEFERRED**（38 第四轮 + M29~M31） |

> **收口复核（书记官回填后补测，时点晚于 T4）**：`python tests/security/verify_delivery.py` → 汇总 **40 PASS / 0 FAIL / 共 40 项**（输出「结论：交付物核验 PASS」），即 **D38 已随本次回填转 PASS**。上表「39 / 1」为 T4 执行时点值，**保留不改**；两者差异仅因本文件第 4/5 节由空到实。

**打包四项**（`python tests/security/pack_delivery.py`）：`PACKED_FILES=163`、`ZIP_SIZE_MB=1.30`、`SENSITIVE_IN_ZIP=0`、`DIST_FILES_IN_ZIP=20`。

**桩测三个必达点**（`.t1-voice-check`，25/25 PASS）：尾片 **count=1**（恰好一次）、**无重复 partial**、顺序为 **`applyStream → finishStreaming → onAllChunksSent`**。

### 4.5 关键断言实测（D1~D4）

| 项 | 断言位置 | 结果 | 真实证据 |
|---|---|---|---|
| **D1** allowedHosts 白名单 | `check_contracts.py` ㉒ + `e2e_headless.py` D1 | **PASS / PASS** | `allowedHosts` **恰 1 元素**、`port` / `proxy` / `plugins` 冻结；`Host: test.hn.takin.cc` → **200**，`Host: evil.example.com` → **403**（证明只放开 `*.takin.cc`、未全局放开） |
| **D2** 续接保留去重链 | `check_contracts.py` ㉓ + `e2e_headless.py` D2 | **PASS / PASS** | `keepSession` 分支 `dedupTail` **0 处**、`else`（新建会话）**1 处**；两边 `resumedRestartFrames` 分别为 `BUDGET` / `0` |
| **D3** 重吐裁剪接入 | `check_contracts.py` ㉔ + `e2e_headless.py` D3 + `check_voice_slicer.cjs` | **PASS / PASS / 8+8 PASS** | `voiceSlicer.ts` 零 import 导出 `trimRestartOverlap`；**仅在追加分支调用**（`applyInterim` / `applyFinal`），`replaceTail` **0 命中**；8 组函数用例全 PASS |
| **D4** 尾片结算幂等 | `check_contracts.py` ㉕ + `e2e_headless.py` D4 | **PASS / PASS** | `commitStoppedSession()` **首条有效语句 `if (!stopping) return`**；其后五步顺序未变；双 `onend` + 双 timer 实测**只结算 1 次** |

**`trimRestartOverlap` 8 组真实输出（`check_voice_slicer.cjs`）**

```text
PASS trimRestartOverlap("明天下午两点", "明天下午两点去操场") = "去操场"
PASS trimRestartOverlap("abc", "abc") = ""
PASS trimRestartOverlap("abc", "xyz") = "xyz"
PASS trimRestartOverlap("", "abc") = "abc"
PASS trimRestartOverlap("abc", "") = ""
PASS trimRestartOverlap("ab", "bx") = "x"
PASS trimRestartOverlap("一二三四五", "三四五六七八") = "六七八"
PASS trimRestartOverlap("资源时长两小时", "资源，时长两小时") = "资源，时长两小时"（期望 "资源，时长两小时"）
```

> 第 8 组即用户实测原话用例：单字重叠（「资」）按 **≥2 字**门槛**不裁**，说明裁剪不会吞掉用户真实重复的内容；有 2 字以上重叠的 4 组（含第 1 组「明天下午两点」）正确裁掉前缀。对抗探针 A11 已把函数体换成恒等 `return transcript`，结果 **8 组中 4 组 FAIL**，证明该组断言有判别力（非永真）。

### 4.6 本轮 DEFERRED（不计 PASS）

真机/公网三项按 `MANUAL_CHECKLIST.md` 第 9 节记 **DEFERRED**：**M29**（静默续接后同一句只出现一次，需真实麦克风与 Edge 静默 `onend` 时序）、**M30**（说完立刻停止 ×10 的末批必达，需真实麦克风反复核对）、**M31**（公网 `https://xxx.hn.takin.cc/` 返回 200 且可登录，需真实穿透隧道）。本机的 `Host` 头模拟（200/403）与纯逻辑裁剪已自动化覆盖，**真机听感与真实公网域名如实不记 PASS**。

## 5 问题与修复

> 每条按「**现象 → 原因 → 让码道怎么修 → 结果**」四段登记；P1~P5 为本轮用户反馈与实现缺陷，P6 为终验首轮的交付项处置。结论一律以 `tests/security/ACCEPTANCE.md` 复核为准，本文不写 `VERDICT`。

### P1 · 录音整句出现两遍（D2）

- **现象**：用户**没有点停止**、正常连续说话，同一句在左侧文字块与右侧字段里出现两遍，第二遍常带前导逗号（`资源时长两小时` → `资源，时长两小时`）；可稳定复现。
- **原因**：`dedupTail = ''` 在 `start()` 里**无条件执行**（修复前基线 L731，写在 `if/else` 之外）。Edge 的 `continuous` 并非真无限，静默 `onend` 后用 `start({ keepSession: true })` 续接；续接分支只保住了后端 `parse_session`，去重链却被清空 ⇒ 续接实例重吐的前缀帧不再命中「覆盖」，退化成 `fullText += transcript` 追加 ⇒ 叠加第三轮 **B7** 顺序增量链式（只发本片 + 当前草稿），后端把重复片当「本次新增」合并，模型**照抄**进字段与 `spans` ⇒ 草稿里真的存了两份。
- **让码道怎么修**：把 `dedupTail = ''` 从 `if/else` 之外**移入 `else`（新建会话）分支**；`keepSession` 续接**保留**去重链，并在续接分支置 `resumedRestartFrames = RESUMED_RESTART_FRAME_BUDGET` 开启重吐窗口、新建会话分支置 `0` 关闭窗口；切片 5 常量与 C5 收尾时序**一律不动**。
- **结果**：`check_contracts.py` ㉓ 与 E2E D2 双路径 PASS（续接分支 `dedupTail` 0 处、`else` 1 处）；R1 场景「片 1 final → 续接 → 重吐同文 → 片 2」片 1 **只出现一次**；R4 场景「双 `onend`」**只结算一次**。

### P2 · 公网穿透访问前端 403 Blocked request（D1）

- **现象**：通过 `*.takin.cc` 下随机子域打开前端返回 **403 Blocked request**（Vite dev server 拦截页），而同机 8000 端口 `/api/health` 正常 —— 后端通、前端被拦。
- **原因**：Vite `server.allowedHosts` 默认 `[]`，只放行 `localhost` / `.localhost` / 所有 IP；穿透域名两者都不是 ⇒ 命中 Host 校验被拦。uvicorn 不校验 Host，故表现为「API 通、页面 403」。
- **让码道怎么修**：在 `frontend/vite.config.ts` 的 `server` 内**追加前导点白名单** `allowedHosts: ['.takin.cc']`（前导点覆盖主域 + 全部子域），其余配置一字不动；**禁止**写成 `allowedHosts: true`（等于放弃 DNS rebinding 防护）。
- **结果**：E2E D1 实测 `Host: test.hn.takin.cc` → **200**、`Host: evil.example.com` → **403**（证明未全局放开）；`allowedHosts` 恰 1 处、数组恰 1 元素。真实公网域名访问按 M31 记 DEFERRED。

### P3 · D3 的误裁边界（重吐 vs 用户真心重复）

- **现象**：裁剪上线后存在一类理论误裁——用户在续接窗口内**真的重复说了一句**，可能与「浏览器重吐」无法区分。
- **原因**：裁剪工作在**文本层**，只有「后缀 = 前缀」这一条重叠证据；单凭字面无法判定该帧是引擎重吐还是用户重说（引擎重吐的指纹是「停顿点回退 + 常带前导标点」，但并非每帧都有标点）。
- **让码道怎么修**：加**三重约束**收敛裁剪面 —— ① 只在**续接窗口**内生效（`resumedRestartFrames = 3` 帧，新建会话不进窗口）；② 重叠长度 **≥2 字**才裁（单字重叠如「好的好的」不裁，避免吞掉真实口语）；③ `fullText` 非空才比对（无前文可依时不裁）。裁剪只作用于**追加分支**，`replaceTail` 覆盖分支不裁剪。
- **结果**：正常新内容**不被裁**（R2）；真实重复语句若恰落在 3 帧窗口内**可能被裁一遍**（R3）——该边界已知、已写入本文与 `prompt迭代记录.md` P-010，并作为**可接受的取舍**（窗口只有 3 帧，代价远小于「整句两遍」）。8 组函数用例 PASS，A11 探针证明断言有判别力。

### P4 · `resetLocalBuffer` 未复位 `resumedRestartFrames`（实现遗漏，已补修）

- **现象**：T4 终验（O-T4-5-1）发现 `resetLocalBuffer()` 只清 `fullText` / `sentIndex` / `dedupTail`，**遗留 `resumedRestartFrames` 非零**，理论上存在跨会话误裁风险。
- **原因**：D3 新增了窗口计数变量，但清空函数是 C5 时期写的，T2 首版只改了 `dedupTail`，漏掉新变量；现有调用路径虽不会踩中（下一次 `start()` 恒走 `else` 分支把窗口归零），但这是「靠调用顺序兜底」而非「状态自洽」。
- **让码道怎么修**：在 `resetLocalBuffer()` 中**补一行 `resumedRestartFrames = 0`**，并加注释说明「第五轮 D3 配套：清空续接重叠窗口，防跨会话误裁新内容」——不做结构性改造、不动其它缓冲字段。
- **结果**：T2 已补修（`useVoiceComposer.ts` 的 `resetLocalBuffer()` 内可见该行）；typecheck 通过，桩测 **25/25 仍 PASS**，C5 行为未回退。

### P5 · 尾片双结算的防御（D4）

- **现象**：`onend` 结算与 3s 兜底（`FORCE_FINALIZE_MS`）/ `finalizeTimer` 理论上可能对同一次收尾各结算一遍，导致尾片发两次。
- **原因**：§2.3 已逐路径证明 8 条出口互斥（`onend` 一到即清兜底），但该保证**依赖调用方互斥**；`commitStoppedSession()` 作为唯一写尾片的函数被两条路径调用，缺少自身幂等性。
- **让码道怎么修**：在 `commitStoppedSession()` **首行**加幂等守卫 —— 首条有效语句 `if (!stopping) return`（已结算或无可结算文本即返回），把「调用方互斥」降级为「函数自身幂等」；**不改**其后五步顺序、不改 C5 的 `stopping` / `onend` / 3s 兜底时序。
- **结果**：`check_contracts.py` ㉕ 与 E2E D4 双路径 PASS（首条有效语句命中）；A12 探针「`stopping` 已为 false 时再次调用」实测尾片**只结算 1 次**；双 `onend` + 双 timer 场景同样 1 次。

### P6 · 终验首轮交付项未收口（D38）

- **现象**：T4 终验首轮给 **PARTIAL**，唯一 FAIL 为 **D38** —— `stage10_第五轮体验修复.md` 第 4/5 节为空节（机检要求第 4/5 节非空且第 4 节含实测计数）；其余 39 项交付校验、三套件、D1~D4 断言全部 PASS。
- **原因**：A 段只写到第 3 节，第 4/5 节依赖 T4 的真实计数，A 段撰写时无法预填；B 段未在下发当轮即时回填，导致交付物机检把「文档未收口」判为 FAIL（按 `R26-AC3` / `C-DELIVERY@5`，B 段未收口不得给 PASS）。
- **让码道怎么修**：按 `ACCEPTANCE.md` 第四节「真实计数」逐项回填第 4 节（文件 / 三套件 / 桩测 / 合计 / zip / D1~D4 证据），按 5 条根因 + 1 条收口回填第 5 节，并在第 3 节登记 `C-DEV@1` / `C-VOICEUI@5` / `C-DELIVERY@5`；**数字原样引用、不改写、不补造**。
- **结果**：本次回填完成——第 4 节含 **1583 / 1404 / 163 / `SENSITIVE_IN_ZIP=0`** 等实测计数，第 5 节为 **P1~P6**，第 3 节 3 个契约 ID 各 ≥1 命中；书记官回填后复跑 `verify_delivery.py` 实测 **40 PASS / 0 FAIL**，**D38 已转 PASS**。**最终 `VERDICT` 以 `tests/security/ACCEPTANCE.md` 复核为准，本文不写结论**。