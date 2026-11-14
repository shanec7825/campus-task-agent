<script setup lang="ts">
/**
 * 发布活动（R-03 / R-07，`C-NAV-SHARED-ACTIVITY@2`）。
 *
 * - 仅组织 admin/collaborator 进入（路由 `requiresManager`）；服务端仍会再次校验组织发布权。
 * - 预览复用 `ActivityInfoSection`，与活动详情使用同一组字段与顺序。
 * - 活动整体任务发布事务属于 AIW-11，本页只创建活动本体。
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { createActivity } from '../api/activities'
import { ApiError } from '../api/client'
import ActivityInfoSection from '../components/activity/ActivityInfoSection.vue'
import { useUserStore } from '../stores/user'
import type { Activity } from '../types/models'

const router = useRouter()
const userStore = useUserStore()

const saving = ref(false)
const form = reactive({
  title: '',
  description: '',
  location: '',
  start_time: '',
  deadline: '',
  org_id: null as number | null
})

/** 只列出本人有发布权的组织；成员组织不冒充可选 */
const publishableOrgs = computed(() =>
  userStore.orgs.filter(
    (org) =>
      org.status === 'active' && (org.role === 'admin' || org.role === 'collaborator')
  )
)

const selectedOrgName = computed<string>(() => {
  if (form.org_id === null) return ''
  return publishableOrgs.value.find((org) => org.org_id === form.org_id)?.name ?? ''
})

/** 预览对象：字段来源与详情一致，不含任何服务端派生数据 */
const preview = computed<Activity>(() => ({
  id: 0,
  title: form.title.trim() || '活动名称预览',
  description: form.description.trim() || null,
  location: form.location.trim() || null,
  start_time: form.start_time || null,
  deadline: form.deadline || null,
  owner_id: userStore.user?.id ?? 0,
  owner_name: userStore.displayName || '我',
  org: selectedOrgName.value || null,
  org_id: form.org_id,
  status: 'published',
  created_at: '',
  progress: {
    total_tasks: 0,
    completed_tasks: 0,
    cancelled_tasks: 0,
    subtask_total: 0,
    subtask_completed: 0,
    percent: 0,
    awaiting_owner_confirm: false
  }
}))

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function submit(): Promise<void> {
  const title = form.title.trim()
  if (!title) {
    ElMessage.warning('请填写活动名称')
    return
  }
  if (form.start_time && form.deadline && form.deadline < form.start_time) {
    ElMessage.warning('截止时间不能早于举办开始时间')
    return
  }
  saving.value = true
  try {
    const activity = await createActivity({
      title,
      description: form.description.trim() || null,
      location: form.location.trim() || null,
      start_time: form.start_time || null,
      deadline: form.deadline || null,
      org_id: form.org_id
    })
    ElMessage.success(`活动《${activity.title}》已发布`)
    void router.push({ name: 'activity', params: { id: activity.id } })
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="app-page publish-activity">
    <header class="app-page-header">
      <div>
        <h1 class="app-page-title">发布活动</h1>
        <p class="app-page-subtitle">
          先发布活动本体；任务与依赖的一次确认整体发布在后续阶段提供，本页不提前占用该语义。
        </p>
      </div>
    </header>

    <div class="publish-activity__grid">
      <form class="app-section-card publish-activity__form" @submit.prevent="submit">
        <el-form label-position="top">
          <el-form-item label="活动名称" required>
            <el-input v-model="form.title" maxlength="120" show-word-limit />
          </el-form-item>
          <el-form-item label="介绍">
            <el-input v-model="form.description" type="textarea" :rows="4" maxlength="2000" />
          </el-form-item>
          <el-form-item label="地点">
            <el-input v-model="form.location" maxlength="200" />
          </el-form-item>
          <el-form-item label="举办开始时间">
            <el-input v-model="form.start_time" type="datetime-local" />
          </el-form-item>
          <el-form-item label="活动截止时间">
            <el-input v-model="form.deadline" type="datetime-local" />
          </el-form-item>
          <el-form-item label="归属组织">
            <el-select v-model="form.org_id" clearable placeholder="不归属组织（仅本人可发布任务）">
              <el-option
                v-for="org in publishableOrgs"
                :key="org.org_id"
                :label="`${org.name} · ${org.role === 'admin' ? '管理员' : '协作者'}`"
                :value="org.org_id"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <div class="publish-activity__actions">
          <el-button :disabled="saving" @click="router.push({ name: 'published-activities' })">
            返回我发布的活动
          </el-button>
          <el-button type="primary" native-type="submit" :loading="saving">发布活动</el-button>
        </div>
      </form>

      <div class="publish-activity__preview" aria-label="活动预览">
        <p class="publish-activity__preview-hint">预览与活动详情共用同一字段区块</p>
        <ActivityInfoSection :activity="preview" title-tag="h2" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.publish-activity {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.publish-activity__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--app-space-4);
  align-items: start;
}

.publish-activity__form {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.publish-activity__preview {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.publish-activity__preview-hint {
  margin: 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.publish-activity__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--app-space-2);
}

.publish-activity__actions :deep(.el-button) {
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .publish-activity__grid {
    grid-template-columns: 1fr;
  }

  .publish-activity__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .publish-activity__actions :deep(.el-button) {
    width: 100%;
  }
}
</style>