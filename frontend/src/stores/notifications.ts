/**
 * 通知 Store（契约 C-STORE@1）。
 *
 * state：unread / items / connected
 * actions：refresh（别名 fetchList）、markRead、push（别名 pushIncoming）、setUnread
 *
 * `push` 按 `id` 去重：重复推送只更新内容并返回 `false`，
 * 供 `useSSE` 判断是否需要弹 `ElNotification`（避免重连后重复弹窗）。
 */
import { defineStore } from 'pinia'

import { archiveNotifications, listNotifications, readNotifications } from '../api/notifications'
import type { NotificationItem } from '../types/models'

export const useNotificationsStore = defineStore('notifications', {
  state: (): {
    unread: number
    items: NotificationItem[]
    archivedItems: NotificationItem[]
    connected: boolean
  } => ({
    unread: 0,
    items: [],
    archivedItems: [],
    connected: false
  }),

  getters: {
    /** 未读通知（展示用，保持后端顺序；已失效提醒不计入未读） */
    unreadItems: (state): NotificationItem[] =>
      state.items.filter((item) => item.is_read === 0 && item.stale === 0)
  },

  actions: {
    /** 拉取通知列表（默认最近 50 条） */
    async refresh(limit = 50): Promise<void> {
      const result = await listNotifications({ limit })
      this.items = result.items
      this.unread = result.unread
    },

    /** `refresh` 的语义别名（任务说明中的命名） */
    fetchList(limit = 50): Promise<void> {
      return this.refresh(limit)
    },

    /** 拉取归档箱（`C-NOTICE-ARCHIVE@1`）：已处理通知只读列表 */
    async loadArchived(limit = 50): Promise<void> {
      const result = await listNotifications({ archived: true, limit })
      this.archivedItems = result.items
    },

    /** 批量归档：先本地移除，再重拉未归档与归档箱，保证未读数一致 */
    async archive(ids: number[]): Promise<number> {
      if (ids.length === 0) return 0
      const result = await archiveNotifications(ids)
      const idSet = new Set(ids)
      this.items = this.items.filter((item) => !idSet.has(item.id))
      await this.refresh()
      await this.loadArchived()
      return result.updated
    },

    /** 批量标记已读并同步本地计数 */
    async markRead(ids: number[]): Promise<void> {
      if (ids.length === 0) return
      const result = await readNotifications(ids)
      const idSet = new Set(ids)
      for (const item of this.items) {
        if (idSet.has(item.id) && item.stale === 0) item.is_read = 1
      }
      this.unread = Math.max(0, this.unread - result.updated)
    },

    /**
     * 接收 SSE 推送。
     * @returns `true` 表示是新通知（调用方可以弹提示），`false` 表示重复项
     */
    push(item: NotificationItem): boolean {
      const index = this.items.findIndex((existing) => existing.id === item.id)
      if (index >= 0) {
        this.items[index] = item
        return false
      }
      this.items.unshift(item)
      if (item.is_read === 0 && item.stale === 0) this.unread += 1
      return true
    },

    /** `push` 的语义别名（任务说明中的命名） */
    pushIncoming(item: NotificationItem): boolean {
      return this.push(item)
    },

    /** 直接设置未读数（红点兜底） */
    setUnread(n: number): void {
      this.unread = Math.max(0, n)
    },

    /** 设置 SSE 连接状态（useSSE 调用） */
    setConnected(value: boolean): void {
      this.connected = value
    },

    /** 退出登录时清空（额外提供，避免切换账号后残留旧通知） */
    reset(): void {
      this.unread = 0
      this.items = []
      this.connected = false
    }
  }
})