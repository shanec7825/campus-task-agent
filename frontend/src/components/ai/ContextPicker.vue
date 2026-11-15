<script setup lang="ts">
/**
 * AI 输入框 `@` 上下文选择面板（契约 `C-AI-PAGE@1` / `C-AI-CONTEXT@1`）。
 *
 * 只负责取数、过滤与派发选择事件；作用域与资料状态的归属在 `aiChat` store，
 * 因此面板自身不保存选中态，选中结果由完整页以 chip 展示。
 */
import { computed, ref, watch } from 'vue'

import { listActivities } from '../../api/activities'
import { ApiError } from '../../api/client'
import { listLibraryRefs } from '../../api/library'
import { listTasks } from '../../api/tasks'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  (e: 'select-task', id: number, title: string): void
  (e: 'select-activity', id: number, title: string): void
  (e: 'toggle-resource', id: number, title: string): void
  (e: 'close'): void
}>()

interface PickerOption {
  id: number
  title: string
}

const filter = ref('')
const loading = ref(false)
const error = ref('')
const loaded = ref(false)
const tasks = ref<PickerOption[]>([])
const activities = ref<PickerOption[]>([])
const resources = ref<PickerOption[]>([])

function matches(title: string): boolean {
  const keyword = filter.value.trim().toLowerCase()
  return keyword === '' || title.toLowerCase().includes(keyword)
}

const visibleTasks = computed(() => tasks.value.filter((item) => matches(item.title)))
const visibleActivities = computed(() => activities.value.filter((item) => matches(item.title)))
const visibleResources = computed(() => resources.value.filter((item) => matches(item.title)))

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message || '读取失败'
  return '读取失败，请稍后重试'
}

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  error.value = ''
  try {
    const [taskResult, activityResult, refResult] = await Promise.all([
      listTasks({ scope: 'mine', include_sub: false }),
      listActivities({ scope: 'mine' }),
      listLibraryRefs()
    ])
    tasks.value = taskResult.items.map((item) => ({ id: item.id, title: item.title }))
    activities.value = activityResult.items.map((item) => ({ id: item.id, title: item.title }))
    resources.value = refResult.items.map((item) => ({ id: item.resource_id, title: item.title }))
    loaded.value = true
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open) {
      filter.value = ''
      return
    }
    if (!loaded.value) void load()
  }
)
</script>

<template>
  <div v-if="open" class="context-picker" role="dialog" aria-label="选择 AI 上下文">
    <div class="context-picker__head">
      <span class="context-picker__title">添加上下文</span>
      <button
        type="button"
        class="context-picker__close"
        aria-label="关闭上下文面板"
        @click="emit('close')"
      >
        ×
      </button>
    </div>

    <input
      v-model="filter"
      class="context-picker__filter"
      type="search"
      placeholder="过滤任务、活动或资料"
      aria-label="过滤上下文"
    />

    <p v-if="loading" class="context-picker__hint">正在读取…</p>
    <div v-else-if="error" class="context-picker__error">
      <span>{{ error }}</span>
      <button type="button" class="context-picker__retry" @click="load">重试</button>
    </div>

    <div v-else class="context-picker__groups">
      <section class="context-picker__group" aria-label="我的任务">
        <h2 class="context-picker__group-title">我的任务</h2>
        <p v-if="visibleTasks.length === 0" class="context-picker__hint">暂无匹配任务</p>
        <ul v-else class="context-picker__list">
          <li v-for="item in visibleTasks" :key="`task-${item.id}`">
            <button
              type="button"
              class="context-picker__item"
              @click="emit('select-task', item.id, item.title)"
            >
              {{ item.title }}
            </button>
          </li>
        </ul>
      </section>

      <section class="context-picker__group" aria-label="我的活动">
        <h2 class="context-picker__group-title">我的活动</h2>
        <p v-if="visibleActivities.length === 0" class="context-picker__hint">暂无匹配活动</p>
        <ul v-else class="context-picker__list">
          <li v-for="item in visibleActivities" :key="`activity-${item.id}`">
            <button
              type="button"
              class="context-picker__item"
              @click="emit('select-activity', item.id, item.title)"
            >
              {{ item.title }}
            </button>
          </li>
        </ul>
      </section>

      <section class="context-picker__group" aria-label="Library 资料">
        <h2 class="context-picker__group-title">Library 资料</h2>
        <p v-if="visibleResources.length === 0" class="context-picker__hint">暂无匹配资料</p>
        <ul v-else class="context-picker__list">
          <li v-for="item in visibleResources" :key="`resource-${item.id}`">
            <button
              type="button"
              class="context-picker__item"
              @click="emit('toggle-resource', item.id, item.title)"
            >
              {{ item.title }}
            </button>
          </li>
        </ul>
      </section>
    </div>
  </div>
</template>

<style scoped>
.context-picker {
  position: absolute;
  right: 0;
  bottom: calc(100% + var(--app-space-2));
  left: 0;
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  max-height: 320px;
  padding: var(--app-space-3);
  overflow-y: auto;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-raised);
  box-shadow: var(--app-shadow-md);
}

.context-picker__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}

.context-picker__title {
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
}

.context-picker__close {
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  cursor: pointer;
}

.context-picker__filter {
  box-sizing: border-box;
  width: 100%;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text);
  font-size: var(--app-font-body);
}

.context-picker__groups {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.context-picker__group-title {
  margin: 0 0 var(--app-space-1);
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  color: var(--app-text-secondary);
}

.context-picker__list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}

.context-picker__item {
  width: 100%;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text);
  font-size: var(--app-font-body);
  text-align: left;
  word-break: break-word;
  cursor: pointer;
}

.context-picker__item:hover {
  border-color: var(--app-border-strong);
  background: var(--app-primary-soft);
}

.context-picker__hint {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-muted);
}

.context-picker__error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--el-color-danger);
  font-size: var(--app-font-aux-lg);
}

.context-picker__retry {
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text);
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}
</style>