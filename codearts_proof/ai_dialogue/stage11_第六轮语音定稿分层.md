# 阶段 11 · 第六轮语音定稿分层（ITN 定稿才进发送层）

> 归档口径：本轮按用户要求**精简执行**——只改语音一处代码 + 本文件 + `LOG.md` 一行；
> **未跑测试套件/回归/无头 E2E，未新建 plan，未走契约/哨兵终验，未重打 zip，未改 MANUAL_CHECKLIST**。
> 验证由用户在浏览器 / 穿透环境自行完成。本文件不写任何未发生的验证结论。

## 1 用户反馈（原文要点）

> "十一月**11月**15号的歌手大赛需要三名志愿者。负责。钱到签到和签退。"

同一条草稿里「十一月」与「11月」双写、且伴随「负责。」句号残留。用户据此指出：

> "不要急急忙忙把没有 ITN 的文本放到输入框里或者给 AI 读取，等 ITN 完了再放。"

## 2 根因（为什么前两轮的"精确文本去重"抓不住）

1. **重复源是"迟到定稿"**：Edge 停顿后静默断流 → 应用 250ms 后 `start({keepSession:true})` 续接；语音服务会把停顿前 utterance 的 final **补发**给新实例。这个重复源从第二轮加入自动续接起就存在。
2. **迟到定稿经过 ITN（逆文本规整）**：`十一月→11月`、`三名→3名`。它与缓冲中已存的原始转写**零字符重叠**，因此第五轮 `trimRestartOverlap`（最长「后缀=前缀」逐字精确匹配）对它是**结构性无效**——不是实现质量问题，而是武器选错了。
3. **interim 曾混入发送缓冲**：`applyInterim` 过去会把 interim 累加进 `fullText`，于是未经 ITN 的暂定稿既进了输入框、也可能进入切片发给 AI；等 final 以规整形态到达时，两边各留一份。
4. 第三、四轮为何没暴露/为何爆发：第三轮重复帧被实时小切片打散、后端 `merge_draft` 以累计文本为基准能吸收；第四轮 C5 改为"缓冲全程不清 + 集中结算"，重复滞留到最终草稿里一次性显形。

## 3 本次改动（G1：展示 / 发送分层）

文件：`frontend/src/composables/useVoiceComposer.ts`

- `applyInterim`：**只做实时显示**（`pushLiveText` → 蓝色 live 虚线块逐字刷新）；
  删除其中的 `fullText` 写入与 `replaceTail` 调用。interim 不再进入输入框、字段或发给 AI 的 chunk。
- `applyFinal`（ITN 定稿帧）：**唯一**执行 `fullText += transcript` 并参与 `scheduleSlices` 切片；
  若与缓冲尾部有精确重叠，仍沿用既有 `trimRestartOverlap` 裁剪兜底。
  同时删除旧的「`frameText === dedupTail` 时不追加」分支——interim 已不落缓冲，保留该分支会把定稿整段丢弃。
- 其余全部未动：切片五常量（1 / 12 / 800 / 800 / 200）、`stop`/`onend` 收尾时序、`stopping` 守卫、
  `onAllChunksSent` 链路、`trimRestartOverlap`、后端所有文件。
- `replaceTail` 自本轮起不再被调用（函数保留，可供追溯历史逻辑）。

预期效果：迟到定稿若是旧 utterance 的**首次定稿** → 唯一采纳；`十一月`(interim) 只出现在 live 块、
`11月`(final) 是唯一进入文本的版本 → 重复源失去入口。

## 4 已知边界（用户已接受）

- **说话过程中只有蓝色 live 虚线块在实时增长**；彩色正式文字块与字段值要等该段 `final` 定稿后才出现。
  这是"只让 ITN 定稿进发送层"的必然代价，不是渲染缺陷。
- 若浏览器在续接后**重吐已定稿的旧 utterance**，仍由 `trimRestartOverlap` 按精确重叠裁剪；
  若重吐内容又被 ITN 改写成不同字面（如"十一月"→"11月"），文本层仍无法识别——此时按既定结论
  **不再修文本层，直接启用 Plan B（取消自动续接、停顿即结算并提示）**，需用户拍板。
- 本轮为极简执行，**没有回归数字**；真机效果以用户自测为准。

## 5 静态契约检查口径同步（CI 修复轮）

`tests/frontend/check_contracts.py` 第 ㉔ 项（`C-VOICEUI@5 §2/§3`）的断言口径已按本轮
「展示 / 发送分层」更新，标题与通过文案改为「仅定稿追加路径接入」。旧口径要求
`applyInterim` 也调用 `trimResumedTranscript`，与本轮实现相反，现已删除。

现行断言（7 条）：

1. `utils/voiceSlicer.ts` 导出 `trimRestartOverlap`，且文件内无 `import`（纯函数、零依赖）。
2. `useVoiceComposer.ts` 从 `utils/voiceSlicer` 引入 `trimRestartOverlap`。
3. `trimResumedTranscript()` 调用 `trimRestartOverlap(`。
4. `applyInterim()` 含 `pushLiveText(transcript)`，且不含 `trimResumedTranscript(` /
   `fullText.value` / `sentIndex` / `scheduleSlices(` / `enqueue(` / `streamParse(`
   ——临时结果只展示，不落缓冲、不切片、不发 AI。
5. `applyFinal()` 含 `trimResumedTranscript(` 且首次出现早于 `fullText.value +=`；
   含 `if (!frameText)` 空帧守卫，守卫分支内有 `return` 且无 `fullText.value +=`。
6. `replaceTail()` 内不出现 `trimResumedTranscript(` / `trimRestartOverlap(`。
7. 文件含 `RESUMED_RESTART_FRAME_BUDGET = 3`；`resetLocalBuffer()` 含
   `resumedRestartFrames = 0`。

> 本节只记录检查口径的更新，不写任何未发生的验证结论。
> `useVoiceComposer.ts` / `voiceSlicer.ts` 未做任何改动。
