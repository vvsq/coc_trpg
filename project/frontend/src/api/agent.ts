/**
 * 阶段 4.1：协同建议 / LLM 状态 REST 封装。
 * 结果统一由 WS suggestions 信封送达（后端 202 即返回），REST 只负责触发与查询。
 * 4.1+：LLM 设置面板（GET /llm/status 含预设表、PUT /llm/config、GET /llm/models 探测）。
 */
import { client } from './client'
import type { AgentMode, KpStyleParams, SuggestionsPayload } from '@/types/ws'

// 说明：响应拦截器已返回 response.data，统一用 axios 第二泛型取响应体。

/** KP 切换 Agent 模式；回显由 agent_mode_changed 广播驱动，不在调用处自改 */
export async function setAgentMode(
  roomId: string,
  body: { kp_name: string; mode: AgentMode },
): Promise<{ agent_mode: AgentMode }> {
  return client.put<{ agent_mode: AgentMode }, { agent_mode: AgentMode }>(
    `/rooms/${roomId}/agent-mode`,
    body,
  )
}

/** KP 手动触发生成：立即返回 request_id，建议经 WS 信封送达 */
export async function generateSuggestions(
  roomId: string,
  body: { kp_name: string; focus?: string },
): Promise<{ request_id: string; status: 'generating' }> {
  return client.post<{ request_id: string; status: 'generating' }, { request_id: string; status: 'generating' }>(
    `/rooms/${roomId}/suggestions/generate`,
    body,
  )
}

/** 供应商静态预设（D11：models 仅为推荐，真实列表以 /llm/models 探测为准） */
export interface ProviderPreset {
  key: string
  label: string
  base_url: string
  models: string[]
  key_hint: string
}

/** Token 消耗全局总账（4.4；缓存命中观测 2026-09-10）
 *
 * prompt_tokens 是**名义输入**，其中命中前缀缓存的部分记在 cached_tokens
 * （供应商按折扣计价），cache_hit_rate = cached / prompt（0~1）。
 */
export interface LlmUsage {
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cached_tokens?: number
  cache_hit_rate?: number
}

/** GET /llm/status 响应（key 只回掩码，明文永不回传） */
export interface LlmStatus {
  enabled: boolean
  provider: string
  base_url: string
  model: string
  api_key_masked: string
  timeout: number
  retries: number
  disable_thinking: boolean
  mock_mode: boolean
  light_base_url: string
  light_model: string
  light_api_key_masked: string
  usage: LlmUsage
  presets: ProviderPreset[]
}

export async function getLlmStatus(): Promise<LlmStatus> {
  return client.get<LlmStatus, LlmStatus>('/llm/status')
}

/** PUT /llm/config 请求体：api_key 空 = 保持现有 key（掩码语义）；
 * light_* 留空 = 清除轻任务配置（跟随主模型）；
 * timeout/retries/disable_thinking 运行时可调（4.4+ 修复配置悬空） */
export interface LlmConfigBody {
  base_url?: string
  api_key?: string
  model?: string
  light_base_url?: string
  light_api_key?: string
  light_model?: string
  timeout?: number
  retries?: number
  disable_thinking?: boolean
}

/** 保存 LLM 配置（写 backend/.env 并热重载），返回保存后的状态 */
export async function saveLlmConfig(body: LlmConfigBody): Promise<LlmStatus> {
  return client.put<LlmStatus, LlmStatus>('/llm/config', body)
}

/** GET /llm/models 响应：实时探测供应商可用模型；ok=false 时手填兜底 */
export interface LlmModelsResult {
  ok: boolean
  models: string[]
  provider?: string
  category?: string
  error?: string
}

export async function probeLlmModels(): Promise<LlmModelsResult> {
  return client.get<LlmModelsResult, LlmModelsResult>('/llm/models')
}

/** POST /llm/test 响应：真实打一次 LLM；失败也 200，ok=false 带中文原因。
 * 配置了轻任务模型时一并 ping（light_ok=false 表示轻模型不通） */
export interface LlmTestResult {
  ok: boolean
  latency_ms?: number
  model?: string
  provider?: string
  category?: string
  error?: string
  light_latency_ms?: number
  light_model?: string
  light_ok?: boolean
  light_error?: string
}

/** 真实打一次 LLM。默认 axios 超时 10s 对慢模型偏紧（实测主模型 8.8s），
 * 这里放宽到 90s——解析页的「检测模型」门禁依赖它，超时会误判不可用。 */
export async function testLlm(): Promise<LlmTestResult> {
  return client.post<LlmTestResult, LlmTestResult>('/llm/test', {}, { timeout: 90000 })
}

/** 本房间（一场次）token 消耗，仅 KP 可查（2026-09-10 用户反馈 #3） */
export interface RoomUsageResult {
  room_id: string
  usage: LlmUsage
}

export async function getRoomUsage(roomId: string, kpName: string): Promise<RoomUsageResult> {
  return client.get<RoomUsageResult, RoomUsageResult>(`/rooms/${roomId}/usage`, {
    params: { kp_name: kpName },
  })
}

// ==================== 检卡（用户反馈 #5：AI 检查角色卡是否合理合规） ====================

/** 单条问题；severity 两级：建议 / 明显不合理 */
export interface CardReviewIssue {
  severity: 'suggestion' | 'major'
  title: string
  detail: string
  advice: string
}

export interface CardReviewPlayer {
  player_name: string
  overall: 'ok' | 'suggestion' | 'major'
  issues: CardReviewIssue[]
}

export interface CardReviewResult {
  players: CardReviewPlayer[]
  model: string
  module_mounted?: boolean
  note?: string
}

/** 让 AI 逐卡检查（技能是否配得上背景、物品是否与模组冲突…）。
 * 仅建议不拦截开团；服务端同步调一次 LLM，故单独放宽超时。 */
export async function reviewRoomCards(roomId: string, kpName: string): Promise<CardReviewResult> {
  return client.post<CardReviewResult, CardReviewResult>(
    `/rooms/${roomId}/card-review`,
    { kp_name: kpName },
    { timeout: 180000 },
  )
}

/** 类型再导出：面板组件从本模块取 SuggestionsPayload（REST/WS 同构） */
export type { SuggestionsPayload }

// ==================== 4.4：KP 风格系统（goal §6.2） ====================

/** 内置/自定义风格条目 */
export interface KpStyleItem {
  id: string
  name: string
  description?: string // 仅内置
  params: KpStyleParams
  created_at?: string // 仅自定义
}

/** GET /kp-styles 响应 */
export interface KpStyleList {
  builtins: KpStyleItem[]
  customs: KpStyleItem[]
  created?: KpStyleItem // POST 时的返回附加字段
}

/** 风格列表：内置三种 + 自定义 */
export async function listKpStyles(): Promise<KpStyleList> {
  return client.get<KpStyleList, KpStyleList>('/kp-styles')
}

/** 保存自定义风格（新建 / 导入 JSON 同一入口） */
export async function createKpStyle(name: string, params: KpStyleParams): Promise<KpStyleList> {
  return client.post<KpStyleList, KpStyleList>('/kp-styles', { name, params })
}

/** 删除自定义风格（内置 id 返回 405） */
export async function deleteKpStyle(styleId: string): Promise<{ deleted: string }> {
  return client.delete<{ deleted: string }, { deleted: string }>(`/kp-styles/${styleId}`)
}

/** KP 切换房间风格：回显由 kp_style_changed 全员广播驱动 */
export async function setRoomStyle(
  roomId: string,
  body: { kp_name: string; style_id: string },
): Promise<{ style: { style_id: string; style_name: string } }> {
  return client.put(`/rooms/${roomId}/kp-style`, body)
}
