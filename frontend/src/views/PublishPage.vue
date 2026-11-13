<script setup lang="ts">
/**
 * 统一发布页（T7 / 需求 R2.1、R2.2、R2.4-AC1~AC3、R2.5-AC1~AC4、R10-AC4）
 *
 * 页面结构（《开发方案》6.1）：
 * - 顶部两个 Tab：手动兜底模式 / AI 智能模式；
 * - 两种模式共用同一 `draft` store 实例，用 `v-show` 切换**不销毁**内容，
 *   切回 AI 模式时草稿（文字块 / 字段 / 问号 / 拆解建议）完整保留；
 * - 手动模式永远可用（AI 不可用时的兜底，R2.1-AC3）；
 * - `draft.mockMode === true` 时显式展示「离线示例模式」标签（R9-AC2）。
 *
 * 具体交互实现下沉到子组件：
 * - `ManualForm`：完整表单 + extras 动态键值对 + credit_reward / reminder_rule；
 * - `AiPanel`：相似提示 → 解析 → 审核 → 块/面板染色 → 拆解卡片 → 发布。
 */
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import AiPanel from '../components/Publish/AiPanel.vue'
import ManualForm from '../components/Publish/ManualForm.vue'
import { useDraftStore } from '../stores/draft'

type PublishMode = 'manual' | 'ai'

const route = useRoute()
const draft = useDraftStore()

/** 解析 `?activity=<id>`：仅正整数有效，无效或缺省视为独立任务 */
function parseActivityId(raw: unknown): number | null {
  if (raw === null || raw === undefined || raw === '') return null
  const parsed = Number.parseInt(String(raw), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

/** 由活动详情进入时的活动归属；非空时默认手动模式（AI 模式本轮不带活动归属） */
const activityId = computed<number | null>(() => parseActivityId(route.query.activity))

/** 默认智能模式，手动为兜底：AI 不可用时用户仍可切到手动模式发布 */
const activeTab = ref<PublishMode>('ai')

/** 活动入口进入时默认手动模式（AI 模式本轮不带活动归属） */
if (activityId.value !== null) activeTab.value = 'manual'

/** AI 模式是否有未发布的草稿内容（用于 Tab 徽标与切换提醒） */
const hasDraftContent = computed<boolean>(
  () =>
    draft.blocks.length > 0 ||
    draft.fieldList.some((field) => field.value !== null && String(field.value).trim() !== '')
)

const mockMode = computed<boolean>(() => draft.mockMode)
</script>

<template>
  <section class="publish-page app-page">
    <header class="publish-page__header app-page-header">
      <div class="publish-page__heading">
        <h2 class="publish-page__title app-page-title">发布任务</h2>
        <p class="publish-page__subtitle app-page-subtitle">
          手动填写兜底，或用一句话让 AI 帮你整理成结构化任务；解析后还能继续补充（增量解析只改被说到的字段），
          每次 AI 建议、你的手改与补充都会在左侧留下可追溯的彩色块。
        </p>
      </div>

      <div class="publish-page__badges">
        <!-- Mock 模式必须显式可见（R9-AC2） -->
        <el-tag v-if="activeTab === 'ai' && mockMode" type="warning" effect="dark" size="small">
          离线示例模式
        </el-tag>
        <el-tag v-if="hasDraftContent" type="info" effect="plain" size="small">
          AI 草稿未发布
        </el-tag>
        <el-tag v-if="activeTab === 'ai'" type="success" effect="plain" size="small">
          AI 智能模式
        </el-tag>
        <el-tag v-else type="info" effect="plain" size="small">手动兜底模式</el-tag>
      </div>
    </header>

    <!-- Tab 切换：v-show 双面板同时挂载，绝不销毁 AI 草稿 -->
    <nav class="mode-tabs" role="tablist" aria-label="发布模式">
      <button
        type="button"
        role="tab"
        class="mode-tabs__item"
        :class="{ 'is-active': activeTab === 'manual' }"
        :aria-selected="activeTab === 'manual'"
        @click="activeTab = 'manual'"
      >
        手动兜底模式
      </button>
      <button
        type="button"
        role="tab"
        class="mode-tabs__item"
        :class="{ 'is-active': activeTab === 'ai' }"
        :aria-selected="activeTab === 'ai'"
        @click="activeTab = 'ai'"
      >
        AI 智能模式
      </button>
    </nav>

    <div v-show="activeTab === 'manual'" class="mode-panel" role="tabpanel" aria-label="手动兜底模式">
      <el-alert
        v-if="activityId !== null"
        type="info"
        :closable="false"
        show-icon
        :title="`任务将归属活动 #${activityId}`"
        class="mode-panel__notice"
      />
      <!-- 切回手动模式时提示 AI 草稿仍在（v-show 保活的直接证据） -->
      <el-alert
        v-if="hasDraftContent"
        type="success"
        :closable="false"
        show-icon
        title="AI 草稿仍然保留"
        description="切回「AI 智能模式」可继续编辑、继续增量补充，追溯块也会一并保留，本页不会销毁草稿。"
        class="mode-panel__notice"
      />
      <ManualForm :activity-id="activityId" />
    </div>

    <div v-show="activeTab === 'ai'" class="mode-panel" role="tabpanel" aria-label="AI 智能模式">
      <AiPanel />
    </div>
  </section>
</template>

<style scoped>
.publish-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: var(--app-content-max);
  margin: 0 auto;
}

.publish-page__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.publish-page__heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.publish-page__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--app-text);
}

.publish-page__subtitle {
  margin: 0;
  font-size: 14px;
  color: var(--app-text-secondary);
}

.publish-page__badges {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.mode-tabs {
  display: inline-flex;
  align-self: flex-start;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-sunken);
}

.mode-tabs__item {
  padding: 8px 20px;
  border: none;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text-secondary);
  font-size: 15px;
  line-height: 1.2;
  cursor: pointer;
  transition: background-color 0.16s ease, color 0.16s ease, box-shadow 0.16s ease;
}

.mode-tabs__item:hover {
  color: var(--app-primary);
}

.mode-tabs__item.is-active {
  background: var(--app-surface-raised);
  color: var(--app-primary);
  font-weight: 600;
  box-shadow: var(--app-shadow-sm);
}

.mode-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mode-panel__notice {
  border-radius: var(--app-radius-sm);
}

/* 移动端：标题与徽标上下排列，模式页签占满整行，阅读顺序固定为「说明 → 页签 → 表单」 */
@media (max-width: 768px) {
  .publish-page__header {
    flex-direction: column;
    align-items: stretch;
  }

  .mode-tabs {
    display: flex;
    width: 100%;
    align-self: stretch;
  }

  .mode-tabs__item {
    flex: 1;
    min-height: var(--app-touch);
    padding: 8px 12px;
    font-size: 15px;
  }
}
</style>