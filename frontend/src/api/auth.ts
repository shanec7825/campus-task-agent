/**
 * 认证 API（契约 C-FE-AUTH@1 / C-AUTH-API@1）。
 *
 * 会话由服务端通过同源 Cookie 维护，本模块不读写任何会话令牌。
 */
import { request } from './client'
import type { LoginOut, MeOut, PasswordResetIn, RegisterIn, User } from '../types/models'

/** 登录入参（`LoginIn`） */
export interface LoginPayload {
  username: string
  password: string
}

/** 登录：成功后服务端下发会话与 CSRF Cookie */
export function login(payload: LoginPayload): Promise<LoginOut> {
  return request<LoginOut>('POST', '/api/auth/login', payload)
}

/** 退出登录：撤销服务端会话（无会话时 `revoked` 为 false） */
export function logout(): Promise<{ revoked: boolean }> {
  return request<{ revoked: boolean }>('POST', '/api/auth/logout')
}

/** 当前用户与其组织成员关系（刷新后恢复会话） */
export function fetchMe(): Promise<MeOut> {
  return request<MeOut>('GET', '/api/auth/me')
}

/** 凭邀请注册：成功后自动建立会话 */
export function register(payload: RegisterIn): Promise<LoginOut> {
  return request<LoginOut>('POST', '/api/auth/register', payload)
}

/** 凭一次性重置凭据修改密码 */
export function resetPassword(payload: PasswordResetIn): Promise<{ reset: boolean }> {
  return request<{ reset: boolean }>('POST', '/api/auth/reset-password', payload)
}
/** 本人头像写入：`avatar` 为 data URL，`null` 表示移除并回退默认头像 */
export function updateAvatar(avatar: string | null): Promise<User> {
  return request<User>('PATCH', '/api/auth/avatar', { avatar })
}