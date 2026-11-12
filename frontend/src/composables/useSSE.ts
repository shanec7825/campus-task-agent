/**
 * SSE 订阅（契约 C-STORE@1 / C-NOTIFY@1）。
 *
 * - 地址：`/api/notifications/stream?token=<token>`（EventSource 不能带 Authorization 头）；
 * - `event: notify` → 解析 JSON → `notificationsStore.pushIncoming` → 新通知才弹 `ElNotification`；
 * - `onerror` → 关闭连接，3 秒后重连（仅当仍有 token 且未主动 disconnect）；
 * - `disconnect()` → 关闭且不再重连；token 为空时 `connect()` 直接停止。
 */
import { ref, type Ref } from 'vue'
import { ElNotification } from 'element-plus'

import { getToken } from '../api/client'
import { streamUrl } from '../api/notifications'
import { useNotificationsStore } from '../stores/notifications'
import type { NotificationItem } from '../types/models'

/** 断线重连间隔（毫秒） */
export const RECONNECT_DELAY_MS = 3000

/** 运行时校验 SSE 载荷，避免脏数据进入 store */
function isNotificationItem(value: unknown): value is NotificationItem {
  if (typeof value !== 'object' || value === null) return false
  const record = value as Record<string, unknown>
  return (
    typeof record.id === 'number' &&
    typeof record.user_id === 'number' &&
    typeof record.title === 'string' &&
    typeof record.content === 'string' &&
    typeof record.created_at === 'string'
  )
}

function notificationType(level: string): 'success' | 'info' | 'warning' | 'error' {
  switch (level) {
    case 'warning':
      return 'warning'
    case 'urgent':
      return 'warning'
    case 'overdue':
      return 'error'
    default:
      return 'info'
  }
}

export function useSSE(): { connected: Ref<boolean>; connect(): void; disconnect(): void } {
  const store = useNotificationsStore()
  const connected = ref(false)

  let source: EventSource | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  /** 主动断开标记：为 true 时 onerror / 定时器均不再重连 */
  let manualClosed = false

  function handleNotify(event: MessageEvent): void {
    let payload: unknown
    try {
      payload = JSON.parse(event.data)
    } catch {
      // 非 JSON 载荷（如心跳注释）直接忽略
      return
    }
    if (!isNotificationItem(payload)) return

    const isNew = store.pushIncoming(payload)
    if (!isNew) return

    ElNotification({
      title: payload.title,
      message: payload.content,
      type: notificationType(payload.level),
      duration: 5000,
      position: 'top-right'
    })
  }

  function closeSource(): void {
    if (!source) return
    source.removeEventListener('notify', handleNotify)
    source.onopen = null
    source.onerror = null
    source.close()
    source = null
  }

  function setConnected(value: boolean): void {
    connected.value = value
    store.setConnected(value)
  }

  function scheduleReconnect(): void {
    if (manualClosed || reconnectTimer !== null) return
    if (!getToken()) return
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      if (!manualClosed && getToken()) connect()
    }, RECONNECT_DELAY_MS)
  }

  function handleError(): void {
    setConnected(false)
    closeSource()
    if (manualClosed) return
    // token 为空（登出 / 过期）时停止，不做无限重连
    if (!getToken()) return
    scheduleReconnect()
  }

  function connect(): void {
    const token = getToken()
    if (!token) {
      manualClosed = true
      closeSource()
      setConnected(false)
      return
    }
    if (typeof EventSource === 'undefined') {
      setConnected(false)
      return
    }
    // 已连接或正在连接：不重复创建
    if (source && source.readyState !== EventSource.CLOSED) return

    manualClosed = false
    closeSource()
    try {
      const es = new EventSource(streamUrl(token))
      source = es
      es.onopen = () => setConnected(true)
      es.onerror = () => handleError()
      es.addEventListener('notify', handleNotify)
    } catch {
      setConnected(false)
      scheduleReconnect()
    }
  }

  function disconnect(): void {
    manualClosed = true
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    closeSource()
    setConnected(false)
  }

  return { connected, connect, disconnect }
}