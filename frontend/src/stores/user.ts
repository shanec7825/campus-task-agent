/**
 * 用户会话 Store（契约 C-STORE@1）。
 *
 * - token 与用户信息在 localStorage 持久化（`cta_token` / `cta_user`）；
 * - `login` 调用 `api/auth.login` 并由其写入本地存储；
 * - `fetchMe` 用于刷新页面后恢复会话；`logout` 同时清理 store 与本地存储。
 */
import { defineStore } from 'pinia'

import { fetchMe as apiFetchMe, login as apiLogin } from '../api/auth'
import { USER_KEY, clearStoredUser, getToken, setToken } from '../api/client'
import type { LoginResult, User } from '../types/models'

/** 读取本地缓存的用户信息（JSON 损坏时静默丢弃） */
function readStoredUser(): User | null {
  try {
    const raw = window.localStorage.getItem(USER_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return null
    const candidate = parsed as Partial<User>
    if (typeof candidate.id !== 'number' || typeof candidate.username !== 'string') return null
    return candidate as User
  } catch {
    return null
  }
}

/** 写入本地用户缓存 */
function writeStoredUser(user: User | null): void {
  try {
    if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user))
    else clearStoredUser()
  } catch {
    // 本地缓存失败不影响会话内存状态
  }
}

export const useUserStore = defineStore('user', {
  state: (): { token: string | null; user: User | null } => ({
    token: getToken(),
    user: readStoredUser()
  }),

  getters: {
    /** 是否有有效 token（过期由接口 401 兜底） */
    isLoggedIn: (state): boolean => Boolean(state.token),
    /** 发布者（教师）才有发布者后台入口（R10-AC5） */
    isPublisher: (state): boolean => state.user?.role === 'publisher',
    /** 管理员角色 */
    isAdmin: (state): boolean => state.user?.role === 'admin',
    /** 顶栏展示名：优先 display_name，回退 username */
    displayName: (state): string => state.user?.display_name || state.user?.username || ''
  },

  actions: {
    /** 登录：成功后同步 token / user 到 store 与本地存储 */
    async login(username: string): Promise<LoginResult> {
      const result = await apiLogin(username)
      this.token = result.token
      this.user = result.user
      setToken(result.token)
      writeStoredUser(result.user)
      return result
    },

    /** 用当前 token 拉取用户信息；token 失效时清空本地会话并向上抛出 */
    async fetchMe(): Promise<User> {
      try {
        const user = await apiFetchMe()
        this.user = user
        this.token = getToken()
        writeStoredUser(user)
        return user
      } catch (error) {
        if (!getToken()) {
          // 401 已由 client 清理本地凭证，同步清空 store
          this.token = null
          this.user = null
          writeStoredUser(null)
        }
        throw error
      }
    },

    /** 退出登录：清 token / user / 本地存储 */
    logout(): void {
      this.token = null
      this.user = null
      setToken(null)
      writeStoredUser(null)
    }
  }
})