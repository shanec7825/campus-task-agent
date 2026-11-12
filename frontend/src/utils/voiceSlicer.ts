/**
 * 语音切片纯函数（契约 C-VOICEUI@2 / T5 交付）
 *
 * 硬约束（写死，禁止运行时修改）：
 * 1. **零 import**（含类型 import），保证单文件可被 `tsc` 编译、可被 Node 直接执行（T8 算法单测）；
 * 2. 只做纯文本切分：不读 store、不读时钟、不碰浏览器 API、无副作用；
 * 3. 判定顺序固定为「空 → 标点 → 强制长度 → 继续累积」，与契约 2.2.5 B 节逐条一致。
 *
 * 第五轮（T2 / D3）新增 `trimRestartOverlap`：续接重启后裁掉浏览器重吐的前文
 * （最长「prevTail 后缀 = transcript 前缀」重叠），同样是零 import 纯函数，可独立单测。
 */

/** 切片标点：中文全角标点 + 常用 ASCII 半角标点 */
export const PUNCT_RE = /[，。？！?!.,]/g

/** 标点阈值：任一标点即切（P1 的 3 已作废，见 C-VOICEUI@2 A） */
export const PUNCT_THRESHOLD = 1

/** 无标点时的强制切片长度（字符数） */
export const MAX_CHUNK_CHARS = 12

/** 静默切片：连续该时长无新识别结果即把待发送文本发出（毫秒） */
export const SILENCE_CUT_MS = 800

/** 停止录音后等待最后一帧转写的延迟（毫秒） */
export const FINAL_DELAY_MS = 800

/** interim 文本渲染的节流上限（毫秒，刷新间隔不得超过该值） */
export const LIVE_MAX_REFRESH_MS = 200

/** 一次切分的结果：`chunk` 为本次发送的文本，`rest` 为剩余待发送文本 */
export interface ChunkSlice {
  chunk: string
  rest: string
}

/**
 * 按契约规则从 `pendingText` 中切出一片。
 *
 * 判定顺序（逐条短路）：
 * 1. 空文本 → `null`（无可切内容）；
 * 2. 存在标点（匹配数 >= `PUNCT_THRESHOLD`）→ 取**第一个**标点，`chunk` 为「该标点及其之前的全部字符」；
 * 3. 无标点但长度 >= `MAX_CHUNK_CHARS` → 前 12 个字符为 `chunk`；
 * 4. 否则 → `null`（继续累积，等待更多识别结果）。
 *
 * 例：
 * - `"明天。下午"` → `{ chunk: "明天。", rest: "下午" }`
 * - `"我们明天下午两点在操场集合"`（13 字，无标点）→ `{ chunk: "我们明天下午两点在操", rest: "场集合" }`
 * - `"我们明天下午"`（6 字，无标点）→ `null`
 */
export function sliceChunk(pendingText: string): ChunkSlice | null {
  // ① 空文本：无可切内容
  if (!pendingText) return null

  // ② 任一标点即切。matchAll 内部会复制正则（CreateRegExpStringIterator），
  //    因此不会污染 `PUNCT_RE` 的 lastIndex，多次调用结果稳定。
  const punctuationMatches = Array.from(pendingText.matchAll(PUNCT_RE))
  if (punctuationMatches.length >= PUNCT_THRESHOLD) {
    const firstMatch = punctuationMatches[0]
    const cut = (firstMatch?.index ?? 0) + (firstMatch?.[0]?.length ?? 0)
    return { chunk: pendingText.slice(0, cut), rest: pendingText.slice(cut) }
  }

  // ③ 无标点但已达强制长度：切前 MAX_CHUNK_CHARS 个字符
  if (pendingText.length >= MAX_CHUNK_CHARS) {
    return {
      chunk: pendingText.slice(0, MAX_CHUNK_CHARS),
      rest: pendingText.slice(MAX_CHUNK_CHARS)
    }
  }

  // ④ 不足阈值：继续累积
  return null
}

/**
 * 续接重启后，浏览器可能重吐前文：裁掉 transcript 与 prevTail 的最长后缀=前缀重叠。
 *
 * 语义：令 `k` 为满足 `prevTail.slice(-k) === transcript.slice(0, k)` 的**最大**值
 * （`0 ≤ k ≤ min(prevTail.length, transcript.length)`），返回 `transcript.slice(k)`：
 * - `k === 0`（无重叠）→ 原样返回 `transcript`；
 * - 任一入参为空串 → 原样返回 `transcript`；
 * - 完全重叠（`transcript` 就是 `prevTail` 的尾部）→ 返回空串 `''`。
 *
 * 例：
 * - `("明天下午两点", "明天下午两点去操场")` → `"去操场"`（k=6）
 * - `("abc", "abc")` → `""`（k=3）
 * - `("abc", "xyz")` → `"xyz"`（k=0）
 * - `("一二三四五", "三四五六七八")` → `"六七八"`（k=3）
 *
 * 纯函数（零 import、无副作用），供接入层在续接窗口内做「重吐前文」裁剪。
 */
export function trimRestartOverlap(prevTail: string, transcript: string): string {
  if (!prevTail || !transcript) return transcript

  const maxOverlap = Math.min(prevTail.length, transcript.length)
  for (let k = maxOverlap; k > 0; k -= 1) {
    if (prevTail.slice(-k) === transcript.slice(0, k)) {
      return transcript.slice(k)
    }
  }
  return transcript
}