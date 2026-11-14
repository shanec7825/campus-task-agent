<script setup lang="ts">
/**
 * Library（契约 C-NAV-GROUPS@3 / C-LIBRARY@1）。
 *
 * 两个分区互不共享：「我的参考链接」只走 `/api/library/links`（owner 由服务端判定），
 * 「我可见的活动 / 任务资料」复用既有 `GET /api/resources` 的可见范围。
 */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '../api/client'
import {
  createLibraryLink,
  listLibraryLinks,
  updateLibraryLink,
  type LibraryLink
} from '../api/library'
import { listResources } from '../api/resources'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import type { ResourceItem } from '../types/models'

const RESOURCE_LIMIT = 20
const LINK_PAGE_SIZE = 20
const TITLE_MAX = 200
const URL_MAX = 1000
const NOTE_MAX = 2000

const resources = ref<ResourceItem[]>([])
const resourceLoading = ref(false)
const resourceError = ref('')

const links = ref<LibraryLink[]>([])
const linkTotal = ref(0)
const linkLoading = ref(false)
const linkError = ref('')
const saving = ref(false)
const formError = ref('')
const editingId = ref<number | null>(null)

const form = reactive({ title: '', url: '', note: '' })

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.length > 16 ? value.slice(0, 16) : value
}

async function loadResources(): Promise<void> {
  resourceLoading.value = true
  resourceError.value = ''
  try {
    resources.value = (await listResources({ limit: RESOURCE_LIMIT })).items
  } catch (err) {
    resources.value = []
    resourceError.value = errorMessage(err)
  } finally {
    resourceLoading.value = false
  }
}

async function loadLinks(append = false): Promise<void> {
  linkLoading.value = true
  linkError.value = ''
  try {
    const offset = append ? links.value.length : 0
    const result = await listLibraryLinks({ offset, limit: LINK_PAGE_SIZE })
    links.value = append ? [...links.value, ...result.items] : result.items
    linkTotal.value = result.total
  } catch (err) {
    if (!append) links.value = []
    linkError.value = errorMessage(err)
  } finally {
    linkLoading.value = false
  }
}

function startEdit(link: LibraryLink): void {
  editingId.value = link.id
  form.title = link.title
  form.url = link.url
  form.note = link.note ?? ''
  formError.value = ''
}

function resetForm(): void {
  editingId.value = null
  form.title = ''
  form.url = ''
  form.note = ''
  formError.value = ''
}

async function submitLink(): Promise<void> {
  const title = form.title.trim()
  const url = form.url.trim()
  const note = form.note.trim()
  if (!title) {
    formError.value = '请填写标题'
    return
  }
  if (!/^https?:\/\//i.test(url)) {
    formError.value = '链接必须以 http:// 或 https:// 开头'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    if (editingId.value !== null) {
      const updated = await updateLibraryLink(editingId.value, { title, url, note: note || null })
      links.value = links.value.map((item) => (item.id === updated.id ? updated : item))
      ElMessage.success('已更新参考链接')
    } else {
      const payload = note ? { title, url, note } : { title, url }
      const created = await createLibraryLink(payload)
      links.value = [created, ...links.value]
      linkTotal.value += 1
      ElMessage.success('已添加参考链接')
    }
    resetForm()
  } catch (err) {
    formError.value = errorMessage(err)
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void loadLinks()
  void loadResources()
})
</script>

<template>
  <section class="app-page library-page" :aria-busy="linkLoading || resourceLoading ? 'true' : 'false'">
    <header class="library-page__header">
      <h1 class="app-page-title">Library</h1>
      <p class="app-page-subtitle">我的参考链接，以及我有权查看的活动 / 任务资料。</p>
    </header>

    <section
      class="library-section"
      aria-labelledby="library-private-title"
      data-testid="library-private"
    >
      <h2 id="library-private-title" class="library-section__title">我的参考链接</h2>
      <p class="library-section__hint">仅本人可见，同组织成员与管理员都不可读取。</p>

      <form class="library-form" @submit.prevent="submitLink">
        <div class="library-form__field">
          <label class="library-form__label" for="library-link-title">标题</label>
          <el-input
            id="library-link-title"
            v-model="form.title"
            :maxlength="TITLE_MAX"
            show-word-limit
            placeholder="例如：学期志愿活动手册"
            aria-label="链接标题"
            autocomplete="off"
          />
        </div>
        <div class="library-form__field">
          <label class="library-form__label" for="library-link-url">链接（http / https）</label>
          <el-input
            id="library-link-url"
            v-model="form.url"
            :maxlength="URL_MAX"
            placeholder="https://example.com/reference"
            aria-label="链接地址"
            autocomplete="off"
          />
        </div>
        <div class="library-form__field">
          <label class="library-form__label" for="library-link-note">说明（可选）</label>
          <el-input
            id="library-link-note"
            v-model="form.note"
            type="textarea"
            :rows="2"
            :maxlength="NOTE_MAX"
            show-word-limit
            placeholder="这条链接的用途或备注"
            aria-label="链接说明"
          />
        </div>

        <p v-if="formError" class="library-form__error" role="alert">{{ formError }}</p>

        <div class="library-form__actions">
          <el-button type="primary" native-type="submit" :loading="saving">
            {{ editingId === null ? '添加链接' : '保存修改' }}
          </el-button>
          <el-button v-if="editingId !== null" :disabled="saving" @click="resetForm">
            取消编辑
          </el-button>
        </div>
      </form>

      <LoadingState v-if="linkLoading && links.length === 0" :rows="2" />

      <ErrorState
        v-else-if="linkError && links.length === 0"
        :message="linkError"
        detail="个人参考链接加载失败，请检查后端服务后重试。"
        retryable
        @retry="loadLinks"
      />

      <EmptyState
        v-else-if="links.length === 0"
        title="还没有个人参考链接"
        description="在上方填写标题与 http(s) 地址即可添加，只有你自己能看到。"
      />

      <template v-else>
        <ul class="library-links">
          <li v-for="link in links" :key="link.id" class="library-link">
            <div class="library-link__head">
              <h3 class="library-link__title">{{ link.title }}</h3>
              <span class="library-link__meta">更新于 {{ dateText(link.updated_at) }}</span>
            </div>
            <p v-if="link.note" class="library-link__note">{{ link.note }}</p>
            <div class="library-link__actions">
              <a
                class="library-link__url"
                :href="link.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                打开链接
              </a>
              <el-button size="small" :disabled="saving" @click="startEdit(link)">
                编辑
              </el-button>
            </div>
          </li>
        </ul>

        <p v-if="linkError" class="library-form__error" role="alert">{{ linkError }}</p>

        <el-button
          v-if="links.length < linkTotal"
          class="library-links__more"
          :loading="linkLoading"
          @click="loadLinks(true)"
        >
          加载更多
        </el-button>
      </template>
    </section>

    <section
      class="library-section"
      aria-labelledby="library-shared-title"
      data-testid="library-shared"
    >
      <h2 id="library-shared-title" class="library-section__title">我可见的活动 / 任务资料</h2>
      <p class="library-section__hint">可见范围由后端按活动、任务与组织成员关系判定。</p>

      <LoadingState v-if="resourceLoading" :rows="3" />

      <ErrorState
        v-else-if="resourceError"
        :message="resourceError"
        detail="共享资料加载失败，请检查后端服务后重试。"
        retryable
        @retry="loadResources"
      />

      <EmptyState
        v-else-if="resources.length === 0"
        title="暂无可见资料"
        description="加入活动或任务后，负责人共享的资料会出现在这里。"
      />

      <ul v-else class="library-resources">
        <li v-for="item in resources" :key="item.id" class="library-resource">
          <div class="library-resource__head">
            <h3 class="library-resource__title">{{ item.title }}</h3>
            <span class="library-resource__type">{{ item.resource_type }}</span>
          </div>
          <p v-if="item.summary" class="library-resource__summary">{{ item.summary }}</p>
          <p v-if="item.activity_title" class="library-resource__meta">
            关联活动：{{ item.activity_title }}
          </p>
          <a
            class="library-resource__link"
            :href="item.url"
            target="_blank"
            rel="noopener noreferrer"
          >
            打开资料
          </a>
        </li>
      </ul>
    </section>
  </section>
</template>

<style scoped>
.library-page {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-5);
}

.library-page__header {
  min-width: 0;
}

.library-section {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  padding: var(--app-space-4);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.library-section__title {
  margin: 0;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  color: var(--app-text);
}

.library-section__hint {
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

.library-form {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  margin: var(--app-space-2) 0 0;
  padding: var(--app-space-3);
  background: var(--app-surface-raised);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.library-form__field {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

.library-form__label {
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  font-weight: 500;
}

.library-form__error {
  margin: 0;
  color: var(--el-color-danger);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
}

.library-form__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
}

.library-form__actions :deep(.el-button) {
  min-height: var(--app-touch);
}

.library-links,
.library-resources {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.library-link,
.library-resource {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  padding: var(--app-space-3);
  background: var(--app-surface-raised);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.library-link__head,
.library-resource__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--app-space-2);
}

.library-link__title,
.library-resource__title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  overflow-wrap: break-word;
}

.library-link__meta,
.library-resource__type {
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

.library-link__note {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  overflow-wrap: break-word;
}

.library-link__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-1);
}

.library-link__actions :deep(.el-button) {
  min-height: var(--app-touch);
}

.library-link__url,
.library-resource__link {
  align-self: flex-start;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  color: var(--app-primary);
  font-size: var(--app-font-aux-lg);
  line-height: var(--app-touch);
  text-decoration: none;
}

.library-link__url:hover,
.library-resource__link:hover {
  text-decoration: underline;
}

.library-links__more {
  align-self: flex-start;
  min-height: var(--app-touch);
  margin-top: var(--app-space-2);
}

.library-resource__summary {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
}

.library-resource__meta {
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

@media (max-width: 768px) {
  .library-section {
    padding: var(--app-space-3);
  }

  .library-form {
    padding: var(--app-space-2);
  }
}
</style>