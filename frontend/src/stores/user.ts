/**
 * 用户会话 Store（契约 C-FE-AUTH@1）。
 *
 * - 会话凭据只存在于服务端 Cookie，store 不持有任何 token；
 * - `user` 在 localStorage 中仅作首屏展示缓存（`cta_user`），组织关系每次由 `/api/auth/me` 恢复；
 * - `restore` 用于首次导航前的会话恢复，`checked` 标记是否已确认过登录状态；
 * - `logout` 等待服务端撤销会话后再清空本地状态（网络失败也清空）。
 */
import { defineStore } from 'pinia'

import { fetchMe as apiFetchMe, login as apiLogin, logout as apiLogout } from '../api/auth'
import type { LoginPayload } from '../api/auth'
import { ApiError, USER_KEY, clearStoredUser } from '../api/client'
import type { LoginOut, OrgMembership, User } from '../types/models'

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

/** 写入本地用户展示缓存（不得写入任何凭据） */
function writeStoredUser(user: User | null): void {
  try {
    if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user))
    else clearStoredUser()
  } catch {
    // 本地缓存失败不影响会话内存状态
  }
}

export const useUserStore = defineStore('user', {
  state: (): { user: User | null; orgs: OrgMembership[]; checked: boolean } => ({
    user: readStoredUser(),
    orgs: [],
    checked: false
  }),

  getters: {
    /** 已建立会话（Cookie 有效性由接口 401 兜底） */
    isLoggedIn: (state): boolean => Boolean(state.user),
    /** 平台管理员：仅受 `/api/orgs` 与 `/api/admin/*` 加持 */
    isPlatformAdmin: (state): boolean => Boolean(state.user?.platform_admin),
    /** 可在某个组织内发布事务（组织管理员 / 协作者） */
    isPublisher: (state): boolean =>
      state.orgs.some((membership) => membership.role === 'admin' || membership.role === 'collaborator'),
    /** 至少一个组织的管理员 */
    isAdmin: (state): boolean => state.orgs.some((membership) => membership.role === 'admin'),
    /** 当前组织：第一个 active 成员关系 */
    currentOrg: (state): OrgMembership | null =>
      state.orgs.find((membership) => membership.status === 'active') ?? null,
    /** 顶栏展示名：优先 display_name，回退 username */
    displayName: (state): string => state.user?.display_name || state.user?.username || ''
  },

  actions: {
    /** 写入一次会话（登录 / 注册 / 恢复成功后调用） */
    setSession(user: User, orgs: OrgMembership[]): void {
      this.user = user
      this.orgs = Array.isArray(orgs) ? orgs : []
      this.checked = true
      writeStoredUser(user)
    },

    /** 更新本人头像（`null` 回退默认头像）：同步内存与本地展示缓存 */
    setAvatar(avatar: string | null): void {
      if (!this.user) return
      this.user = { ...this.user, avatar }
      writeStoredUser(this.user)
    },

    /** 账号密码登录：成功后同步会话到 store */
    async login(payload: LoginPayload): Promise<LoginOut> {
      const result = await apiLogin(payload)
      this.setSession(result.user, result.orgs)
      return result
    },

    /**
     * 强制刷新当前用户与组织关系（兼容既有 AdminConsole 的调用）。
     *
     * 先复位 `checked` 让 `restore()` 真正发起 `/api/auth/me`，再返回会话用户。
     */
    async fetchMe(): Promise<User> {
      this.checked = false
      await this.restore()
      if (!this.user) throw new ApiError(4010, '未登录或登录已过期')
      return this.user
    },

    /**
     * 首次导航前恢复会话。
     *
     * 401 视为未登录并清空本地状态；网络异常不代表未登录，保留展示缓存。
     */
    async restore(): Promise<void> {
      if (this.checked) return
      try {
        const me = await apiFetchMe()
        this.setSession(me.user, me.orgs)
      } catch (error) {
        if (error instanceof ApiError && error.code === 4010) {
          this.user = null
          this.orgs = []
          writeStoredUser(null)
        }
      } finally {
        this.checked = true
      }
    },

    /** 退出登录：先等服务端撤销会话，再清空本地状态（失败也清空） */
    async logout(): Promise<void> {
      try {
        await apiLogout()
      } catch {
        // 服务端不可用或会话已失效时仍需要清空本地状态
      } finally {
        this.user = null
        this.orgs = []
        this.checked = true
        writeStoredUser(null)
      }
    }
  }
})