<script setup lang="ts">
/**
 * Library（契约 C-LIBRARY-PAGE@1 / C-ORG-LIBRARY@1）。
 *
 * 三个分区互不共享：「我的引用资料」只走 `/api/library/refs`（只返回仍可访问项），
 * 「我可见的活动 / 任务资料」复用既有 `GET /api/resources` 的可见范围，
 * 「组织资料」只对组织 admin/collaborator 显示（按所选组织走 `/api/org-resources`）。
 */
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { ApiError } from '../api/client'
import { listLibraryRefs } from '../api/library'
import {
  createOrgResource,
  downloadOrgResourceUrl,
  listOrgResources,
  patchOrgResource,
  type OrgResourceCreatePayload,
  type OrgResourcePatchPayload
} from '../api/orgResources'
import { listResources } from '../api/resources'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useUserStore } from '../stores/user'
import type {
  LibraryRef,
  OrgResource,
  OrgResourceTextStatus,
  ResourceItem
} from '../types/models'

const RESOURCE_LIMIT = 20

const TITLE_MAX = 200
const URL_MAX = 1000
const NOTE_MAX = 2000

/** 与 `C-DOC-PARSE@1` 的 PARSEABLE_EXTS 一致；扩展名不在其中时服务端返回 4001 */
const ORG_FILE_EXTS = ['.pdf', '.docx', '.txt', '.md']
const ORG_FILE_MAX_BYTES = 20 * 1024 * 1024
/** 开关文案即风险声明：AI 检索命中不等于文件本身对外保密 */
const ORG_AI_NOTICE = '开启后学生可能通过 AI 回答看到资料内容，不等于文件保密'

type OrgResourceMode = 'file' | 'link'

const ORG_TEXT_STATUS: Record<
  OrgResourceTextStatus,
  { label: string; tone: 'info' | 'success' | 'danger' }
> = {
  pending: { label: '解析待处理', tone: 'info' },
  ready: { label: '正文已解析', tone: 'success' },
  failed: { label: '正文解析失败', tone: 'danger' }
}

const resources = ref<ResourceItem[]>([])
const resourceLoading = ref(false)
const resourceError = ref('')

/** AI 引用收藏（`C-LIB-REF@1`）：服务端只返回仍可访问项，`revoked_count` 单独提示 */
const libraryRefs = ref<LibraryRef[]>([])
const refRevokedCount = ref(0)
const refsLoading = ref(false)
const refsError = ref('')

const userStore = useUserStore()
/** 只列本人有管理权的组织；成员组织不出现，避免提交后才收到 4030 */
const manageableOrgs = computed(() =>
  userStore.orgs.filter(
    (org) => org.status === 'active' && (org.role === 'admin' || org.role === 'collaborator')
  )
)

const selectedOrgId = ref<number | null>(null)
const orgResources = ref<OrgResource[]>([])
const orgLoading = ref(false)
const orgError = ref('')
const orgIncludeArchived = ref(false)
const orgSaving = ref(false)
const orgFormError = ref('')
const orgFileInput = ref<HTMLInputElement | null>(null)
const orgForm = reactive({
  title: '',
  summary: '',
  mode: 'file' as OrgResourceMode,
  url: '',
  file: null as File | null
})

/** 后端按 0/1 存开关与归档，schema 也可能以 bool 暴露，这里统一读取 */
function flagOn(value: boolean | number | null | undefined): boolean {
  return value === true || value === 1
}

function statusMeta(status: OrgResourceTextStatus): { label: string; tone: 'info' | 'success' | 'danger' } {
  return ORG_TEXT_STATUS[status] ?? ORG_TEXT_STATUS.pending
}

function fileSizeText(size: number | null): string {
  if (!size || size <= 0) return '大小未知'
  if (size >= 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`
  if (size >= 1024) return `${Math.round(size / 1024)} KB`
  return `${size} B`
}

/** 读取文件为纯 base64（去掉 dataURL 前缀），与成果上传接口的零依赖做法一致 */
function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('读取文件失败'))
    reader.readAsDataURL(file)
  })
}

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

function refTypeLabel(type: LibraryRef['resource_type']): string {
  if (type === 'file') return '文件'
  if (type === 'link') return '链接'
  return type
}

async function loadRefs(): Promise<void> {
  refsLoading.value = true
  refsError.value = ''
  try {
    const result = await listLibraryRefs()
    libraryRefs.value = result.items
    refRevokedCount.value = result.revoked_count
  } catch (err) {
    libraryRefs.value = []
    refRevokedCount.value = 0
    refsError.value = errorMessage(err)
  } finally {
    refsLoading.value = false
  }
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


async function loadOrgResources(): Promise<void> {
  const orgId = selectedOrgId.value
  if (orgId === null) {
    orgResources.value = []
    return
  }
  orgLoading.value = true
  orgError.value = ''
  try {
    const result = await listOrgResources({
      org_id: orgId,
      include_archived: orgIncludeArchived.value
    })
    orgResources.value = result.items
  } catch (err) {
    orgResources.value = []
    orgError.value = errorMessage(err)
  } finally {
    orgLoading.value = false
  }
}

function onOrgFileChange(event: Event): void {
  const input = event.target as HTMLInputElement | null
  orgForm.file = input?.files?.[0] ?? null
  if (orgForm.file && !orgForm.title.trim()) {
    orgForm.title = orgForm.file.name.replace(/\.[^.]+$/, '')
  }
}

function resetOrgForm(): void {
  orgForm.title = ''
  orgForm.summary = ''
  orgForm.url = ''
  orgForm.file = null
  orgFormError.value = ''
  if (orgFileInput.value) orgFileInput.value.value = ''
}

async function submitOrgResource(): Promise<void> {
  const orgId = selectedOrgId.value
  if (orgId === null) {
    orgFormError.value = '请先选择组织'
    return
  }
  const title = orgForm.title.trim()
  if (!title) {
    orgFormError.value = '请填写资料标题'
    return
  }
  const summary = orgForm.summary.trim() || null
  const file = orgForm.mode === 'file' ? orgForm.file : null
  const url = orgForm.mode === 'link' ? orgForm.url.trim() : ''
  if (orgForm.mode === 'file') {
    if (!file) {
      orgFormError.value = '请选择要上传的文件'
      return
    }
    const ext = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (!ORG_FILE_EXTS.includes(ext)) {
      orgFormError.value = `仅支持 ${ORG_FILE_EXTS.join(' / ')} 格式`
      return
    }
    if (file.size > ORG_FILE_MAX_BYTES) {
      orgFormError.value = '单个文件不能超过 20MB'
      return
    }
  } else if (!/^https?:\/\//i.test(url)) {
    orgFormError.value = '链接必须以 http:// 或 https:// 开头'
    return
  }

  orgSaving.value = true
  orgFormError.value = ''
  try {
    const payload: OrgResourceCreatePayload = { org_id: orgId, title, summary }
    if (file) {
      payload.file = {
        name: file.name,
        mime: file.type || 'application/octet-stream',
        size: file.size,
        data_base64: await readFileBase64(file)
      }
    } else {
      payload.url = url
    }
    const created = await createOrgResource(payload)
    orgResources.value = [created, ...orgResources.value]
    resetOrgForm()
    ElMessage.success('已保存组织资料')
  } catch (err) {
    orgFormError.value = errorMessage(err)
  } finally {
    orgSaving.value = false
  }
}

/** 开关与归档即时写库：成功后按当前筛选条件就地更新（关闭时归档项直接移出列表） */
async function patchOrgFlag(
  item: OrgResource,
  body: OrgResourcePatchPayload,
  successText: string
): Promise<void> {
  orgError.value = ''
  try {
    const updated = await patchOrgResource(item.id, body)
    if (!orgIncludeArchived.value && flagOn(updated.archived)) {
      orgResources.value = orgResources.value.filter((row) => row.id !== updated.id)
    } else {
      orgResources.value = orgResources.value.map((row) =>
        row.id === updated.id ? updated : row
      )
    }
    ElMessage.success(successText)
  } catch (err) {
    orgError.value = errorMessage(err)
  }
}

function toggleOrgAi(item: OrgResource, value: boolean | string | number): void {
  const enabled = value === true
  void patchOrgFlag(
    item,
    { allow_student_ai: enabled },
    enabled ? '已允许学生通过 AI 检索' : '已关闭学生 AI 检索'
  )
}

function toggleOrgArchived(item: OrgResource): void {
  const archived = !flagOn(item.archived)
  void patchOrgFlag(item, { archived }, archived ? '已归档，学生检索不再命中' : '已恢复')
}


watch(
  manageableOrgs,
  (orgs) => {
    if (selectedOrgId.value === null && orgs.length > 0) selectedOrgId.value = orgs[0].org_id
  },
  { immediate: true }
)

watch([selectedOrgId, orgIncludeArchived], () => {
  void loadOrgResources()
})

onMounted(() => {

  void loadRefs()
  void loadResources()
})
</script>

<template>
  <section class="app-page library-page" :aria-busy="refsLoading || resourceLoading ? 'true' : 'false'">
    <header class="library-page__header">
      <h1 class="app-page-title">Library</h1>
      <p class="app-page-subtitle">AI 引用资料，以及你有权查看的活动 / 任务资料。</p>
    </header>

    <section
      class="library-section"
      aria-labelledby="library-refs-title"
      data-testid="library-refs"
    >
      <h2 id="library-refs-title" class="library-section__title">我的引用资料</h2>
      <p class="library-section__hint">
        AI 回答引用组织资料后自动收藏，只展示当前仍可访问的资料；不复制文件。
      </p>
      <p v-if="refRevokedCount > 0" class="library-refs__revoked" role="note">
        有 {{ refRevokedCount }} 条引用已撤回或归档，不再展示。
      </p>

      <LoadingState v-if="refsLoading && libraryRefs.length === 0" :rows="2" />

      <ErrorState
        v-else-if="refsError && libraryRefs.length === 0"
        :message="refsError"
        detail="引用资料加载失败，请检查后端服务后重试。"
        retryable
        @retry="loadRefs"
      />

      <EmptyState
        v-else-if="libraryRefs.length === 0"
        title="还没有引用资料"
        description="在 AI 中引用后自动收藏；被撤回或归档的资料不会出现在这里。"
      />

      <template v-else>
        <ul class="library-refs">
          <li v-for="ref in libraryRefs" :key="ref.resource_id" class="library-ref">
            <div class="library-ref__head">
              <h3 class="library-ref__title">{{ ref.title }}</h3>
              <el-tag size="small" type="info">{{ refTypeLabel(ref.resource_type) }}</el-tag>
            </div>
            <p v-if="ref.summary" class="library-ref__summary">{{ ref.summary }}</p>
            <p class="library-ref__meta">最近使用 {{ dateText(ref.last_used_at) }}</p>
            <div class="library-ref__actions">
              <a
                v-if="ref.resource_type === 'file'"
                class="library-link__url"
                :href="downloadOrgResourceUrl(ref.resource_id)"
              >
                下载文件
              </a>
              <a
                v-else-if="ref.url"
                class="library-link__url"
                :href="ref.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                打开链接
              </a>
            </div>
          </li>
        </ul>

        <p v-if="refsError" class="library-form__error" role="alert">{{ refsError }}</p>
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

    <section
      v-if="manageableOrgs.length > 0"
      class="library-section"
      aria-labelledby="library-org-title"
      data-testid="library-org"
    >
      <h2 id="library-org-title" class="library-section__title">组织资料</h2>
      <p class="library-section__hint">
        仅本组织管理员与协作者可见；学生本阶段看不到本区，能否进入 AI 回答由每份资料的检索开关决定（新增资料默认关闭）。
      </p>
      <p class="library-org__notice" role="note">
        <strong>默认关闭：</strong>{{ ORG_AI_NOTICE }}。
      </p>

      <div class="library-org__toolbar">
        <label class="library-form__label" for="library-org-select">组织</label>
        <el-select
          id="library-org-select"
          v-model="selectedOrgId"
          class="library-org__select"
          placeholder="选择要管理的组织"
          aria-label="要管理的组织"
        >
          <el-option
            v-for="org in manageableOrgs"
            :key="org.org_id"
            :label="org.name"
            :value="org.org_id"
          />
        </el-select>
        <label class="library-org__switch">
          <el-switch v-model="orgIncludeArchived" aria-label="显示已归档资料" />
          <span>显示已归档</span>
        </label>
      </div>

      <form class="library-form" @submit.prevent="submitOrgResource">
        <div class="library-form__field">
          <el-radio-group v-model="orgForm.mode" aria-label="资料形式">
            <el-radio-button value="file">上传文件</el-radio-button>
            <el-radio-button value="link">登记链接</el-radio-button>
          </el-radio-group>
          <span class="library-org__mode-hint">
            支持 PDF / DOCX / TXT / MD，单个文件不超过 20MB；解析失败也会保存资料。
          </span>
        </div>

        <div class="library-org__grid">
          <div class="library-form__field">
            <label class="library-form__label" for="library-org-form-title">标题</label>
            <el-input
              id="library-org-form-title"
              v-model="orgForm.title"
              :maxlength="TITLE_MAX"
              show-word-limit
              placeholder="例如：迎新策划书"
              aria-label="组织资料标题"
              autocomplete="off"
            />
          </div>
          <div class="library-form__field">
            <label class="library-form__label" for="library-org-form-summary">说明（可选）</label>
            <el-input
              id="library-org-form-summary"
              v-model="orgForm.summary"
              :maxlength="NOTE_MAX"
              show-word-limit
              placeholder="这份资料的用途或适用范围"
              aria-label="组织资料说明"
            />
          </div>
        </div>

        <div v-if="orgForm.mode === 'file'" class="library-form__field">
          <label class="library-form__label" for="library-org-form-file">文件</label>
          <input
            id="library-org-form-file"
            ref="orgFileInput"
            class="library-org__file"
            type="file"
            :accept="ORG_FILE_EXTS.join(',')"
            aria-label="选择组织资料文件"
            @change="onOrgFileChange"
          />
        </div>
        <div v-else class="library-form__field">
          <label class="library-form__label" for="library-org-form-url">链接（http / https）</label>
          <el-input
            id="library-org-form-url"
            v-model="orgForm.url"
            :maxlength="URL_MAX"
            placeholder="https://example.com/handbook"
            aria-label="组织资料链接"
            autocomplete="off"
          />
        </div>

        <p v-if="orgFormError" class="library-form__error" role="alert">{{ orgFormError }}</p>

        <div class="library-form__actions">
          <el-button type="primary" native-type="submit" :loading="orgSaving">
            保存资料
          </el-button>
        </div>
      </form>

      <LoadingState v-if="orgLoading && orgResources.length === 0" :rows="3" />

      <ErrorState
        v-else-if="orgError && orgResources.length === 0"
        :message="orgError"
        detail="组织资料加载失败，请检查后端服务与组织权限后重试。"
        retryable
        @retry="loadOrgResources"
      />

      <EmptyState
        v-else-if="orgResources.length === 0"
        title="还没有组织资料"
        :description="`上传 ${ORG_FILE_EXTS.join(' / ')} 或登记链接后，可在这里逐份管理学生 AI 检索权限。`"
      />

      <template v-else>
        <p v-if="orgError" class="library-form__error" role="alert">{{ orgError }}</p>

        <ul class="library-orgs">
          <li v-for="item in orgResources" :key="item.id" class="library-org">
            <div class="library-org__head">
              <h3 class="library-org__title">{{ item.title }}</h3>
              <el-tag size="small" :type="statusMeta(item.text_status).tone">
                {{ statusMeta(item.text_status).label }}
              </el-tag>
              <el-tag v-if="flagOn(item.archived)" size="small" type="info">已归档</el-tag>
            </div>
            <p v-if="item.summary" class="library-org__summary">{{ item.summary }}</p>
            <p class="library-org__meta">
              <template v-if="item.resource_type === 'file'">
                文件：{{ item.file_name || '未命名' }}（{{ fileSizeText(item.file_size) }}）
              </template>
              <template v-else>外部链接</template>
              <span class="library-org__meta-time">上传于 {{ dateText(item.created_at) }}</span>
            </p>
            <p v-if="item.text_status === 'failed'" class="library-org__parse-note">
              正文解析失败，资料本身已保存；未开启检索开关时学生不会通过 AI 看到该资料。
            </p>
            <div class="library-org__controls">
              <label class="library-org__switch">
                <el-switch
                  :model-value="flagOn(item.allow_student_ai)"
                  :aria-label="`允许学生通过 AI 检索：${item.title}`"
                  @change="(value: boolean | string | number) => toggleOrgAi(item, value)"
                />
                <span>允许学生通过 AI 检索</span>
              </label>
              <span class="library-org__switch-note">{{ ORG_AI_NOTICE }}</span>
            </div>
            <div class="library-org__actions">
              <a
                v-if="item.resource_type === 'file'"
                class="library-link__url"
                :href="downloadOrgResourceUrl(item.id)"
              >
                下载文件
              </a>
              <a
                v-else-if="item.url"
                class="library-link__url"
                :href="item.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                打开链接
              </a>
              <el-button size="small" @click="toggleOrgArchived(item)">
                {{ flagOn(item.archived) ? '恢复' : '归档' }}
              </el-button>
            </div>
          </li>
        </ul>
      </template>
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

.library-resources {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.library-resource {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  padding: var(--app-space-3);
  background: var(--app-surface-raised);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.library-resource__head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--app-space-2);
}

.library-resource__title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  overflow-wrap: break-word;
}

.library-resource__type {
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
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

.library-refs__revoked {
  margin: 0;
  padding: var(--app-space-2) var(--app-space-3);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  background: var(--app-surface-raised);
  border-left: 3px solid var(--el-color-warning);
  border-radius: var(--app-radius-sm);
}

.library-refs {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.library-ref {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  padding: var(--app-space-3);
  background: var(--app-surface-raised);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.library-ref__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}

.library-ref__title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  overflow-wrap: break-word;
}

.library-ref__summary {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  overflow-wrap: break-word;
}

.library-ref__meta {
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

.library-ref__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-1);
}

.library-org__notice {
  margin: 0;
  padding: var(--app-space-2) var(--app-space-3);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  background: var(--app-surface-raised);
  border-left: 3px solid var(--el-color-warning);
  border-radius: var(--app-radius-sm);
}

.library-org__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-2);
}

.library-org__select {
  min-width: 200px;
  min-height: var(--app-touch);
}

.library-org__select :deep(.el-select__wrapper) {
  min-height: var(--app-touch);
}

.library-org__switch {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-2);
  min-height: var(--app-touch);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
}

.library-org__mode-hint {
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
  line-height: 1.6;
}

.library-org__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--app-space-3);
}

.library-org__file {
  width: 100%;
  min-height: var(--app-touch);
  padding: var(--app-space-2);
  color: var(--app-text-secondary);
  font: inherit;
  background: var(--app-surface);
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-sm);
}

.library-orgs {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.library-org {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  padding: var(--app-space-3);
  background: var(--app-surface-raised);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.library-org__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}

.library-org__title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  overflow-wrap: break-word;
}

.library-org__summary {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  overflow-wrap: break-word;
}

.library-org__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

.library-org__parse-note {
  margin: 0;
  color: var(--el-color-danger);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
}

.library-org__controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-1);
}

.library-org__switch-note {
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
  line-height: 1.6;
}

.library-org__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-1);
}

.library-org__actions :deep(.el-button) {
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .library-section {
    padding: var(--app-space-3);
  }

  .library-form {
    padding: var(--app-space-2);
  }

  .library-org__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .library-org__select {
    width: 100%;
  }

  .library-org__toolbar {
    align-items: stretch;
  }
}
</style>