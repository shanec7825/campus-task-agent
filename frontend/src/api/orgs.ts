/**
 * 组织 API（契约 C-ORG@1）。
 */
import { request } from './client'
import type { OrgMembership } from '../types/models'

/** 我的组织列表（仅 active 成员关系，按组织名升序） */
export function listMyOrgs(): Promise<{ items: OrgMembership[] }> {
  return request<{ items: OrgMembership[] }>('GET', '/api/orgs/mine')
}