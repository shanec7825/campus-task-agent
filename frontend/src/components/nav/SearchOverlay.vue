<script setup lang="ts">
/**
 * 顶部搜索面板（契约 C-NAV-GROUPS@3 / C-MY-SEARCH@1，design.md §9.3）。
 *
 * 只经 `api/search` 调 `GET /api/search/mine`：输入即查（250ms 防抖），
 * 用请求序号丢弃过期响应，旧词的结果不会覆盖新词；结果按活动 / 任务分组，
 * 点击落到既有独立详情页并关闭面板。
 */
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../../api/client'
import { MY_SEARCH_MAX_QUERY, searchMine, type MySearchResult } from '../../api/search'
import { statusText } from '../task/StatusTag.vue'
import type { Activity, TaskItem } from '../../types/models'
import NavIcon from './NavIcon.vue'

const SEARCH_DEBOUNCE_MS = 250
const SEARCH_LIMIT = 5
/** 搜索上下文（`{ q, from: 'search' }`）：跳转详情后返回，重开面板据此恢复 */
const SEARCH_RETURN_KEY = 'cta_search_return'

const props = defineProps<{ modelValue: boolean; initialQuery?: string }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const router = useRouter()

const query = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const panelRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const error = ref('')
const searchedQuery = ref('')
const result = ref<MySearchResult | null>(null)

/** 打开面板前的焦点元素，关闭后归还（`aria-modal` 的焦点恢复） */
let previousActiveElement: HTMLElement | null = null

let debounceTimer: ReturnType<typeof setTimeout> | null = null
let requestSeq = 0

const activityItems = computed<Activity[]>(() => result.value?.activities.items ?? [])
const taskItems = computed<TaskItem[]>(() => result.value?.tasks.items ?? [])
const hasResults = computed<boolean>(
  () => activityItems.value.length > 0 || taskItems.value.length > 0
)
const showEmpty = computed<boolean>(
  () => Boolean(searchedQuery.value) && !loading.value && !error.value && !hasResults.value
)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请稍后重试'
    return err.message || '搜索失败'
  }
  return '搜索失败，请稍后重试'
}

function clearDebounce(): void {
  if (debounceTimer === null) return
  clearTimeout(debounceTimer)
  debounceTimer = null
}

function safeSessionStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage
  } catch {
    // 隐私模式等场景下访问 sessionStorage 可能抛异常
    return null
  }
}

/** 写入 / 清除搜索上下文；空关键词表示用户已清空，删除键避免误恢复 */
function persistSearchContext(keyword: string): void {
  const storage = safeSessionStorage()
  if (!storage) return
  try {
    if (!keyword) {
      storage.removeItem(SEARCH_RETURN_KEY)
      return
    }
    storage.setItem(SEARCH_RETURN_KEY, JSON.stringify({ q: keyword, from: 'search' }))
  } catch {
    // 存储不可用时静默，不影响搜索与跳转
  }
}

/** 读取上次搜索关键词（仅接受 `from=search` 的上下文），失败返回空串 */
function readSearchReturn(): string {
  const storage = safeSessionStorage()
  if (!storage) return ''
  try {
    const raw = storage.getItem(SEARCH_RETURN_KEY)
    if (!raw) return ''
    const parsed = JSON.parse(raw) as { q?: unknown; from?: unknown }
    if (parsed.from !== 'search') return ''
    return typeof parsed.q === 'string' ? parsed.q.trim() : ''
  } catch {
    return ''
  }
}

async function runSearch(keyword: string, token: number): Promise<void> {
  try {
    const data = await searchMine(keyword, SEARCH_LIMIT)
    if (token !== requestSeq) return
    result.value = data
    searchedQuery.value = keyword
    error.value = ''
  } catch (err) {
    if (token !== requestSeq) return
    result.value = null
    searchedQuery.value = keyword
    error.value = errorMessage(err)
  } finally {
    if (token === requestSeq) loading.value = false
  }
}

function retry(): void {
  const keyword = query.value.trim()
  if (!keyword) return
  requestSeq += 1
  const token = requestSeq
  loading.value = true
  error.value = ''
  void runSearch(keyword, token)
}

watch(query, () => {
  const keyword = query.value.trim()
  clearDebounce()
  // 输入即记录当前词：改词覆盖、清空删除，避免下次打开误恢复旧词
  persistSearchContext(keyword)
  // 每次输入都推进序号，未返回的旧请求即使晚到也会被丢弃
  requestSeq += 1
  error.value = ''
  if (!keyword) {
    result.value = null
    searchedQuery.value = ''
    loading.value = false
    return
  }
  const token = requestSeq
  loading.value = true
  debounceTimer = setTimeout(() => {
    debounceTimer = null
    void runSearch(keyword, token)
  }, SEARCH_DEBOUNCE_MS)
})

/**
 * 打开面板时恢复上次搜索词：仅当输入为空时回填，赋值后由 `watch(query)`
 * 复用既有防抖与序号守卫自动发起一次查询。返回是否发生了回填。
 */
function restoreSearchContext(): boolean {
  if (query.value.trim()) return false
  // 外部（AppLayout）传入的词优先，其次才读上次搜索上下文
  const external = (props.initialQuery ?? '').trim()
  const keyword = (external || readSearchReturn()).slice(0, MY_SEARCH_MAX_QUERY)
  if (!keyword) return false
  query.value = keyword
  return true
}

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      clearDebounce()
      loading.value = false
      restoreFocus()
      return
    }
    previousActiveElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const restored = restoreSearchContext()
    void nextTick(() => inputRef.value?.focus())
    // 关闭期间若输入已变更但没有发起请求，重新打开时补一次（回填已自动发起时不重复）
    if (!restored && query.value.trim() && result.value === null && !loading.value) retry()
  }
)

function openActivity(item: Activity): void {
  const keyword = query.value.trim()
  persistSearchContext(keyword)
  close()
  void router.push({
    name: 'activity',
    params: { id: item.id },
    query: { from: 'search', q: keyword }
  })
}

function openTask(item: TaskItem): void {
  const keyword = query.value.trim()
  persistSearchContext(keyword)
  close()
  void router.push({
    name: 'detail',
    params: { id: item.id },
    query: { from: 'search', q: keyword }
  })
}
    function restoreFocus(): void {
  const target = previousActiveElement
  previousActiveElement = null
  if (!target || !document.contains(target)) return
  void nextTick(() => target.focus())
}

/** 面板内可聚焦元素，用于 Tab 循环 */
function focusableElements(): HTMLElement[] {
  const root = panelRef.value
  if (!root) return []
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  )
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Tab') return
  const nodes = focusableElements()
  if (nodes.length === 0) {
    event.preventDefault()
    return
  }
  const first = nodes[0]
  const last = nodes[nodes.length - 1]
  const active = document.activeElement as HTMLElement | null
  const inside = active !== null && nodes.includes(active)
  if (event.shiftKey) {
    if (!inside || active === first) {
      event.preventDefault()
      last.focus()
    }
    return
  }
  if (!inside || active === last) {
    event.preventDefault()
    first.focus()
  }
}

function close(): void {
  clearDebounce()
  emit('update:modelValue', false)
}


function dateText(value: string | null): string {
  if (!value) return '未设置截止'
  return `截止 ${value.length > 16 ? value.slice(0, 16) : value}`
}

onBeforeUnmount(() => {
  clearDebounce()
})
</script>

<template>
  <div
    v-if="modelValue"
    class="search-overlay"
    role="dialog"
    aria-modal="true"
    aria-label="搜索我的活动与任务"
    data-testid="search-overlay"
    @keydown="onKeydown"
    @keydown.esc="close"
  >
    <div class="search-overlay__backdrop" aria-hidden="true" @click="close" />

    <div ref="panelRef" class="search-overlay__panel">
      <div class="search-overlay__head">
        <NavIcon name="search" :size="20" />
        <input
          ref="inputRef"
          v-model="query"
          type="search"
          class="search-overlay__input"
          placeholder="搜索我的活动与任务"
          aria-label="搜索关键词"
          :maxlength="MY_SEARCH_MAX_QUERY"
        />
        <button
          type="button"
          class="search-overlay__close"
          data-testid="search-close"
          aria-label="关闭搜索"
          title="关闭搜索"
          @click="close"
        >
          关闭
        </button>
      </div>

      <p class="search-overlay__hint">只搜索我的活动与任务，不包含全组织或其他人的内容。</p>

      <div class="search-overlay__body" role="status" aria-live="polite">
        <template v-if="loading">
          <p class="search-overlay__state">搜索中…</p>
        </template>

        <template v-else-if="error">
          <div class="search-overlay__error" role="alert">
            <p class="search-overlay__state">{{ error }}</p>
            <button type="button" class="search-overlay__retry" @click="retry">重试</button>
          </div>
        </template>

        <template v-else-if="!searchedQuery">
          <p class="search-overlay__state">输入关键词开始搜索，例如活动名或任务名。</p>
        </template>

        <template v-else-if="showEmpty">
          <p class="search-overlay__state">
            没有找到与「{{ searchedQuery }}」匹配的活动或任务。
          </p>
        </template>

        <template v-else>
          <section
            v-if="activityItems.length > 0"
            class="search-overlay__group"
            aria-label="我的活动"
          >
            <h2 class="search-overlay__group-title">
              我的活动
              <span class="search-overlay__group-count">{{ result?.activities.total }}</span>
            </h2>
            <ul class="search-overlay__list">
              <li v-for="item in activityItems" :key="`activity-${item.id}`">
                <button type="button" class="search-overlay__item" @click="openActivity(item)">
                  <span class="search-overlay__item-title">{{ item.title }}</span>
                  <span class="search-overlay__item-meta">
                    活动 · {{ item.owner_name }} · {{ dateText(item.deadline) }}
                  </span>
                </button>
              </li>
            </ul>
          </section>

          <section v-if="taskItems.length > 0" class="search-overlay__group" aria-label="我的任务">
            <h2 class="search-overlay__group-title">
              我的任务
              <span class="search-overlay__group-count">{{ result?.tasks.total }}</span>
            </h2>
            <ul class="search-overlay__list">
              <li v-for="item in taskItems" :key="`task-${item.id}`">
                <button type="button" class="search-overlay__item" @click="openTask(item)">
                  <span class="search-overlay__item-title">{{ item.title }}</span>
                  <span class="search-overlay__item-meta">
                    任务 · {{ statusText(item.status) }} · {{ dateText(item.deadline) }}
                  </span>
                </button>
              </li>
            </ul>
          </section>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.search-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: var(--app-space-6) var(--app-space-4) var(--app-space-4);
}

.search-overlay__backdrop {
  position: absolute;
  inset: 0;
  background: rgb(15 23 42 / 45%);
}

.search-overlay__panel {
  position: relative;
  display: flex;
  flex-direction: column;
  width: min(640px, 100%);
  max-height: calc(100vh - var(--app-space-6) - var(--app-space-4));
  box-sizing: border-box;
  padding: var(--app-space-4);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-md);
}

.search-overlay__head {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  color: var(--app-text-muted);
}

.search-overlay__input {
  flex: 1;
  min-width: 0;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-body);
}

.search-overlay__input:focus-visible {
  border-color: var(--app-border-strong);
  outline: 2px solid var(--app-primary-soft);
}

.search-overlay__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
  color: var(--app-text-secondary);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.search-overlay__close:hover,
.search-overlay__close:focus-visible {
  background: var(--app-surface-sunken);
  color: var(--app-text);
}

.search-overlay__hint {
  margin: var(--app-space-2) 0 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

.search-overlay__body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  margin-top: var(--app-space-3);
  overflow-y: auto;
  min-height: 0;
}

.search-overlay__state {
  margin: 0;
  padding: var(--app-space-4) var(--app-space-2);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  text-align: center;
}

.search-overlay__error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-2);
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
}

.search-overlay__error .search-overlay__state {
  padding: 0;
  color: var(--el-color-danger);
}

.search-overlay__retry {
  min-height: var(--app-touch);
  min-width: 96px;
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.search-overlay__retry:hover,
.search-overlay__retry:focus-visible {
  background: var(--app-surface-sunken);
}

.search-overlay__group {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

.search-overlay__group-title {
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.search-overlay__group-count {
  margin-left: var(--app-space-1);
  color: var(--app-text-secondary);
}

.search-overlay__list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.search-overlay__item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  box-sizing: border-box;
  min-height: var(--app-touch);
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  background: none;
  color: var(--app-text);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.search-overlay__item:hover {
  background: var(--app-surface-sunken);
}

.search-overlay__item:focus-visible {
  border-color: var(--app-border-strong);
  outline: 2px solid var(--app-primary-soft);
}

.search-overlay__item-title {
  font-size: var(--app-font-body);
  font-weight: 600;
  overflow-wrap: break-word;
}

.search-overlay__item-meta {
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

@media (max-width: 768px) {
  .search-overlay {
    padding: var(--app-space-3);
  }

  .search-overlay__panel {
    padding: var(--app-space-3);
    max-height: calc(100vh - var(--app-space-3) * 2 - var(--app-safe-bottom));
  }
}
</style>