/**
 * 认证 API（契约 C-FEAPI@1 / C-AUTH@1）。
 */
import { request, USER_KEY, setToken } from './client'
import type { LoginResult, User } from '../types/models'

/** 登录（成功后内部写入 token 与本地用户缓存） */
export async function login(username: string): Promise<LoginResult> {
  const result = await request<LoginResult>('POST', '/api/auth/login', { username })
  setToken(result.token)
  try {
    window.localStorage.setItem(USER_KEY, JSON.stringify(result.user))
  } catch {
    // 本地缓存失败不影响登录流程
  }
  return result
}

/** 用当前 token 拉取用户信息（刷新页面后恢复会话） */
export function fetchMe(): Promise<User> {
  return request<User>('GET', '/api/auth/me')
}