/**
 * 统一 HTTP 客户端（契约 C-FEAPI@1）。
 *
 * - 自动注入 `Authorization: Bearer <token>`；
 * - 统一解包 `{code,msg,data}`：`code === 0` 返回 `data`，否则抛 `ApiError`；
 * - HTTP 401：清空本地 token/user，并交由已注册的未登录处理器跳转登录页；
 * - 空响应体（204）按 `data = null` 处理，不抛解析异常。
 */
import type { ApiEnvelope } from '../types/models'

/** 业务 / 网络错误（code=-1 表示网络或响应解析失败） */
export class ApiError extends Error {
  code: number

  constructor(code: number, msg: string) {
    super(msg)
    this.name = 'ApiError'
    this.code = code
  }
}

/** localStorage 键：登录 token */
export const TOKEN_KEY = 'cta_token'
/** localStorage 键：User JSON（刷新后恢复会话） */
export const USER_KEY = 'cta_user'

/** 401 后的跳转处理器（由 router 注册，避免 client 反向依赖 router） */
type UnauthorizedHandler = () => void
let unauthorizedHandler: UnauthorizedHandler | null = null

/** 注册 / 清除全局 401 处理器（传 null 清除） */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

function safeLocalStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage
  } catch {
    // 隐私模式等场景下访问 localStorage 可能抛异常
    return null
  }
}

/** 写入 token（null 表示清除） */
export function setToken(token: string | null): void {
  const storage = safeLocalStorage()
  if (!storage) return
  if (token) storage.setItem(TOKEN_KEY, token)
  else storage.removeItem(TOKEN_KEY)
}

/** 读取 token */
export function getToken(): string | null {
  const storage = safeLocalStorage()
  return storage ? storage.getItem(TOKEN_KEY) : null
}

/** 清除本地缓存的用户信息（登出 / 401 时调用） */
export function clearStoredUser(): void {
  const storage = safeLocalStorage()
  if (storage) storage.removeItem(USER_KEY)
}

/** 401 统一处理：清凭证 + 通知路由跳转 */
function handleUnauthorized(): void {
  setToken(null)
  clearStoredUser()
  if (unauthorizedHandler) {
    unauthorizedHandler()
    return
  }
  // router 尚未注册处理器时的兜底跳转
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.replace('/login')
  }
}

function buildQueryString(query?: Record<string, string | number | boolean | undefined>): string {
  if (!query) return ''
  const parts: string[] = []
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
  }
  return parts.length > 0 ? `?${parts.join('&')}` : ''
}

/**
 * 发起请求并解包统一响应体。
 *
 * @param method HTTP 方法（契约只允许 GET / POST / PATCH）
 * @param path   以 `/api` 开头的同源路径（依赖 Vite 代理）
 * @param body   请求体对象；`undefined` 时不发送 body 与 Content-Type
 * @param query  查询参数（undefined 的键会被忽略）
 */
export async function request<T>(
  method: 'GET' | 'POST' | 'PATCH',
  path: string,
  body?: unknown,
  query?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response: Response
  try {
    response = await fetch(`${path}${buildQueryString(query)}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body)
    })
  } catch {
    throw new ApiError(-1, '网络异常，请检查后端服务是否启动')
  }

  if (response.status === 401) {
    handleUnauthorized()
    throw new ApiError(4010, '未登录或登录已过期')
  }

  // 只读取一次响应文本：204 / 空体按 data=null 处理
  const rawText = await response.text()
  if (!rawText.trim()) {
    if (!response.ok) throw new ApiError(-1, `请求失败（HTTP ${response.status}）`)
    return null as unknown as T
  }

  let envelope: ApiEnvelope<T>
  try {
    envelope = JSON.parse(rawText) as ApiEnvelope<T>
  } catch {
    throw new ApiError(-1, `响应解析失败（HTTP ${response.status}）`)
  }

  if (typeof envelope.code !== 'number') {
    throw new ApiError(-1, `响应格式异常（HTTP ${response.status}）`)
  }
  if (envelope.code !== 0) {
    throw new ApiError(envelope.code, envelope.msg || '请求失败')
  }
  if (!response.ok) {
    throw new ApiError(-1, `请求失败（HTTP ${response.status}）`)
  }
  return envelope.data
}