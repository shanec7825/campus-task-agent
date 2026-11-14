/**
 * AI 作用域语音 sink（契约 `C-AI-VOICE@1`）。
 *
 * 定稿 chunk 只追加到创建时捕获的作用域输入，不覆盖用户原有文字；
 * interim 仅做实时预览，不进入 `committed`，停下后输入回到 `base + committed`。
 */
import { useAiChatStore } from '../stores/aiChat'
import type { StreamParseResult } from '../types/models'
import type { VoiceSink } from './useVoiceComposer'

/** 与输入框 `maxlength` 一致 */
const INPUT_MAX_LENGTH = 2000

export interface AiChatVoiceSink extends VoiceSink {
  /** 创建时捕获的作用域：晚到结果仍写回该目标 */
  scopeKey: string
}

function createSessionId(): string {
  const cryptoLike = globalThis.crypto as Crypto | undefined
  if (cryptoLike && typeof cryptoLike.randomUUID === 'function') {
    return cryptoLike.randomUUID()
  }
  return `voice-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/**
 * 为当前作用域创建语音 sink。
 *
 * 基文取创建瞬间的 `aiChat.input`；录音过程中用户原有文字始终保留在基文里，
 * 语音定稿只在其后追加。
 */
export function createAiChatVoiceSink(): AiChatVoiceSink {
  const aiChat = useAiChatStore()
  const scopeKey = aiChat.scopeKey
  const base = aiChat.input.slice(0, INPUT_MAX_LENGTH)
  let committed = ''

  function writeBack(text: string): void {
    aiChat.setInputForScope(scopeKey, text.slice(0, INPUT_MAX_LENGTH))
  }

  return {
    scopeKey,
    setLiveText(interim: string): void {
      writeBack(base + committed + interim)
    },
    clearLiveText(): void {
      writeBack(base + committed)
    },
    markRecording(): void {
      // AI 侧没有 streaming 模式，录音态由 composable 自身的 recording 表达
    },
    finishStreaming(): void {
      // 同上：无需切换草稿模式
    },
    newSession(): string {
      return createSessionId()
    },
    applyStream(_res: StreamParseResult, chunk: string): void {
      if (!chunk) return
      // 不使用 res.draft 覆盖输入：只把定稿 chunk 追加在基文之后
      committed = (committed + chunk).slice(0, INPUT_MAX_LENGTH)
      writeBack(base + committed)
    }
  }
}