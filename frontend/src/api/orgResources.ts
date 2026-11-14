/**
 * 组织资料库 API（契约 `C-ORG-LIBRARY@1`，design.md S3 §2.2）。
 *
 * 仅组织 admin/collaborator 可调用（服务端按组织角色校验，越权返回 4030）；
 * 下载走同源 Cookie，前端只负责拼 URL，不额外携带令牌。
 */
import { request } from './client'
import type { ArchiveSubmissionPayload, OrgResource } from '../types/models'

export interface OrgResourceListResult {
  items: OrgResource[]
}

/** 上传文件载荷：纯 base64（不含 dataURL 前缀），`size` 必须与解码后字节数一致 */
export interface OrgResourceFilePayload {
  name: string
  mime: string
  size: number
  data_base64: string
}

/** `file` 与 `url` 二选一，同时给或都不给由服务端返回 4001 */
export interface OrgResourceCreatePayload {
  org_id: number
  title: string
  summary?: string | null
  url?: string | null
  file?: OrgResourceFilePayload | null
}

/** PATCH 只修改传入字段；`allow_student_ai` / `archived` 接受 bool（服务端存 0/1） */
export interface OrgResourcePatchPayload {
  title?: string
  summary?: string | null
  allow_student_ai?: boolean
  archived?: boolean
}

/** `GET /api/org-resources`：按 `created_at DESC` 返回，默认不含已归档 */
export function listOrgResources(p: {
  org_id: number
  include_archived?: boolean
}): Promise<OrgResourceListResult> {
  return request<OrgResourceListResult>('GET', '/api/org-resources', undefined, p)
}

/** `POST /api/org-resources`：解析失败仍保存资料（`text_status=failed`），上传不因此失败 */
export function createOrgResource(p: OrgResourceCreatePayload): Promise<OrgResource> {
  return request<OrgResource>('POST', '/api/org-resources', p)
}

/** `PATCH /api/org-resources/{id}`：开关与归档即时生效，无缓存旁路 */
export function patchOrgResource(
  id: number,
  p: OrgResourcePatchPayload
): Promise<OrgResource> {
  return request<OrgResource>('PATCH', `/api/org-resources/${id}`, p)
}

/** 文件下载地址：仅 `resource_type=file` 可用（链接资料打开 `url`） */
export function downloadOrgResourceUrl(id: number): string {
  return `/api/org-resources/${id}/download`
}
/**
 * 把已验收成果归档为组织资料（契约 `C-ARCHIVE@1`）。
 * 归档结果固定 `allow_student_ai=0`，需辅导员在 Library 再显式开启学生 AI 检索。
 */
export function archiveSubmission(
  payload: ArchiveSubmissionPayload
): Promise<OrgResource> {
  return request<OrgResource>('POST', '/api/org-resources/from-submission', payload)
}