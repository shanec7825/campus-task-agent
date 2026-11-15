<script setup lang="ts">
/**
 * AI 会话摘要单条（`C-AI-HISTORY@3` §5.3）。
 *
 * 只展示标题、更新时间与作用对象；点击由调用方决定跳转，组件不直接改 store。
 */
import { computed } from 'vue'

import type { AiConversationSummary } from '../../types/models'

const props = defineProps<{ conversation: AiConversationSummary }>()
const emit = defineEmits<{ select: [id: number] }>()

const href = computed<string>(() => `/ai?conversation=${props.conversation.id}`)

const scopeText = computed<string>(() => {
  const conversation = props.conversation
  if (conversation.scope_type === 'general') return '通用助手'
  return conversation.scope_type === 'activity'
    ? `活动 #${conversation.scope_id ?? ''}`
    : `任务 #${conversation.scope_id ?? ''}`
})

const updatedText = computed<string>(() => {
  const value = props.conversation.updated_at
  if (!value) return '—'
  return value.slice(0, 16).replace('T', ' ')
})
</script>

<template>
  <a
    class="history-entry"
    :href="href"
    :title="conversation.title"
    :aria-label="`打开会话：${conversation.title}`"
    @click.prevent="emit('select', conversation.id)"
  >
    <span class="history-entry__title">{{ conversation.title }}</span>
    <span class="history-entry__meta">{{ updatedText }} · {{ scopeText }}</span>
  </a>
</template>

<style scoped>
.history-entry {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  min-width: 0;
  min-height: var(--app-touch);
  padding: var(--app-space-1) var(--app-space-2);
  border-radius: var(--app-radius-sm);
  color: var(--app-text-secondary);
  text-decoration: none;
}

.history-entry:hover,
.history-entry:focus-visible {
  background: var(--app-surface-sunken);
  color: var(--app-text);
}

.history-entry__title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--app-font-aux-lg);
}

.history-entry__meta {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}
</style>