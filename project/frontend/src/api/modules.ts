/**
 * 模组库 REST 封装 — 阶段 5。
 *
 * 说明：axios 响应拦截器已统一弹错误提示，调用处 catch 里不要再重复 ElMessage。
 * 解析是后台任务（202 立即返回），进度由详情接口轮询，不走 WS。
 */
import { client } from './client'
import type { ModuleDetail, ModuleMeta, ModuleParsed } from '@/types/module'

/** 上传体积上限与后端 module_parser.MAX_UPLOAD_BYTES 对齐（10MB） */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

/** 列表（轻量，不含原文与结构化结果） */
export async function listModules(): Promise<ModuleMeta[]> {
  return client.get<ModuleMeta[], ModuleMeta[]>('/modules')
}

/** 上传并提取纯文本（不触发解析）；大文件放宽超时 */
export async function uploadModule(file: File): Promise<ModuleDetail> {
  const form = new FormData()
  form.append('file', file)
  return client.post<ModuleDetail, ModuleDetail>('/modules', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
}

export async function getModule(moduleId: number): Promise<ModuleDetail> {
  return client.get<ModuleDetail, ModuleDetail>(`/modules/${moduleId}`)
}

/** 人工校对：只提交被改动的字段（后端按局部覆盖处理） */
export async function updateModule(
  moduleId: number,
  body: { name?: string; parsed?: Partial<ModuleParsed> },
): Promise<ModuleDetail> {
  return client.put<ModuleDetail, ModuleDetail>(`/modules/${moduleId}`, body)
}

export async function deleteModule(moduleId: number): Promise<void> {
  return client.delete<void, void>(`/modules/${moduleId}`)
}

/** 手动触发结构化解析（model 留空 = 轻任务模型），202 后轮询详情看状态 */
export async function parseModule(
  moduleId: number,
  model?: string,
): Promise<{ module_id: number; parse_status: string; parse_model: string }> {
  return client.post<
    { module_id: number; parse_status: string; parse_model: string },
    { module_id: number; parse_status: string; parse_model: string }
  >(`/modules/${moduleId}/parse`, { model: model || null })
}
