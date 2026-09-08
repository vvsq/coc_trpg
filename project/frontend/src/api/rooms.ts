import { client } from './client'
import type {
  AgentMode,
  CardStateSnapshot,
  RoomCreated,
  RoomListItem,
  RollResultPayload,
  StatusChangedPayload,
  WsMember,
} from '@/types/ws'

// 说明：响应拦截器已返回 response.data，统一用 axios 第二泛型取响应体。

/** KP 建房：返回 8 位短码房间号 */
export async function createRoom(name: string, kpName: string): Promise<RoomCreated> {
  return client.post<RoomCreated, RoomCreated>('/rooms', { name, kp_name: kpName })
}

/** 玩家加入房间：card_id 可空（先进房再绑卡），返回全量成员列表 */
export async function joinRoom(
  roomId: string,
  playerName: string,
  cardId: string | null,
): Promise<WsMember[]> {
  return client.post<WsMember[], WsMember[]>(`/rooms/${roomId}/join`, {
    player_name: playerName,
    card_id: cardId,
  })
}

/** 大厅：等待中的房间列表 */
export async function listRooms(): Promise<RoomListItem[]> {
  return client.get<RoomListItem[], RoomListItem[]>('/rooms')
}

/** 房间详情（轻量）：退出房间时判断是否提示 KP 解散用；scene 供进房恢复场景标题栏；
 * agent_mode（4.1）供 KP 控制台 AI 建议面板回显；style（4.4）供 KP 风格面板回显 */
export interface RoomDetail {
  room_id: string
  name: string
  kp_name: string
  status: 'waiting' | 'playing'
  scene: { scene_title: string; scene_desc: string }
  agent_mode: AgentMode
  style: { style_id: string; style_name: string }
}

export async function getRoom(roomId: string): Promise<RoomDetail> {
  return client.get<RoomDetail, RoomDetail>(`/rooms/${roomId}`)
}

/** KP 解散房间（kp_name 校验失败返回 403，由拦截器统一提示） */
export async function dissolveRoom(roomId: string, kpName: string): Promise<void> {
  await client.delete(`/rooms/${roomId}`, { params: { kp_name: kpName } })
}

// ==================== 阶段 3.3：KP 控制台 ====================

/** POST /rooms/{id}/status 响应（clamp 后的绝对值） */
export interface StatusResult extends CardStateSnapshot {
  target: string
}

/** KP 改成员 HP/SAN：hp/sanity 传"变更后的绝对值"（服务端 clamp 到 [0, derived]），
 * reason 必填（D9：一切数值变更必须可溯源） */
export interface RoomStatusChange {
  kp_name: string
  target: string
  hp?: number
  sanity?: number
  reason: string
}

export async function updateRoomStatus(
  roomId: string,
  body: RoomStatusChange,
): Promise<StatusResult> {
  return client.post<StatusResult, StatusResult>(`/rooms/${roomId}/status`, body)
}

/** KP 更新场景标题栏（本地 scene 由 scene_changed 广播回填，不在调用处自改） */
export async function updateRoomScene(
  roomId: string,
  body: { kp_name: string; scene_title: string; scene_desc?: string },
): Promise<void> {
  await client.put(`/rooms/${roomId}/scene`, body)
}

/** KP 宣布开团：waiting → playing（幂等；开团后大厅不再展示本房间） */
export async function startGame(
  roomId: string,
  kpName: string,
): Promise<{ status: 'playing'; already_started: boolean }> {
  return client.put(`/rooms/${roomId}/start`, { kp_name: kpName })
}

// ==================== 阶段 3.4：历史 / 快照 / 存读档 ====================

/** room_state 快照（GET /rooms/{id}/state 响应；WS room_state 信封 payload 同构） */
export interface RoomStateSnapshot {
  members: WsMember[]
  scene: { scene_title: string; scene_desc: string }
  hp_sanity: Record<string, CardStateSnapshot>
  style?: { style_id: string; style_name: string }
}

/** history 接口的一行（与后端 _history_payload 一一对应）。
 * payload 是落库时的结构化原始数据：dice 行为 RollResultPayload、
 * status 行为 StatusChangedPayload、text 行为 {role}；旧行/异常行可能为 null */
export interface HistoryMessage {
  id: number
  channel: 'narrative' | 'ooc' | 'system'
  type: 'text' | 'dice' | 'sys' | 'status' | 'check_request'
  sender: string
  content: string
  secret: boolean
  payload: Record<string, any> | null
  role: 'kp' | 'player' | 'system'
  created_at: string
}

/** 消息历史（id 倒序返回，前端回放前 reverse）。暗骰行服务端已按 viewer 过滤 */
export interface RoomHistory {
  messages: HistoryMessage[]
}

/** 拉历史：一次拉全量（limit 500），翻页接口有 before_id 但 MVP 不做无限滚动 */
export async function getRoomHistory(
  roomId: string,
  viewer: string,
  limit = 500,
): Promise<RoomHistory> {
  return client.get<RoomHistory, RoomHistory>(`/rooms/${roomId}/history`, {
    params: { viewer, limit },
  })
}

/** room_state 全量快照：重连成功后主动拉一次补齐成员/场景/HP·SAN */
export async function getRoomState(roomId: string): Promise<RoomStateSnapshot> {
  return client.get<RoomStateSnapshot, RoomStateSnapshot>(`/rooms/${roomId}/state`)
}

/** POST /rooms/{id}/save 响应 */
export interface SaveCreated {
  save_id: number
  name: string
  created_at: string
}

/** KP 存档：快照 = 成员花名册 + 各卡完整 card_data + 场景 */
export async function saveGame(roomId: string, kpName: string, name: string): Promise<SaveCreated> {
  return client.post<SaveCreated, SaveCreated>(`/rooms/${roomId}/save`, {
    kp_name: kpName,
    name,
  })
}

/** GET /rooms/{id}/saves 列表项 */
export interface SaveMeta {
  id: number
  name: string
  created_at: string
}

export async function listSaves(roomId: string): Promise<SaveMeta[]> {
  return client.get<SaveMeta[], SaveMeta[]>(`/rooms/${roomId}/saves`)
}

/** KP 读档：快照原子写回，返回 room_state 快照；界面由 room_state 广播驱动 */
export async function loadSave(
  roomId: string,
  saveId: number,
  kpName: string,
): Promise<RoomStateSnapshot> {
  return client.post<RoomStateSnapshot, RoomStateSnapshot>(
    `/rooms/${roomId}/load/${saveId}`,
    { kp_name: kpName },
  )
}

// ==================== 4.3+：检定下放 ====================

/** KP 手动发起检定下放（collab/manual 模式的「要求玩家投骰」；auto 由 AI 发起）。
 * 服务端按目标角色卡查技能值（D5），落 check_request 消息并 chat_new 广播 */
export async function createCheckRequest(
  roomId: string,
  body: {
    kp_name: string
    target: string
    skill_name: string
    difficulty: 'standard' | 'hard' | 'extreme'
    reason: string
  },
): Promise<{ status: string; request_id: string; target: string }> {
  return client.post(`/rooms/${roomId}/check-requests`, body)
}

/** 被点名的玩家投掷检定：服务端按请求里存好的技能值判定（D5，玩家无自掷空间）。
 * 结算结果同时落 type=dice 行 + roll_result 广播；auto 模式下唤醒 AI 继续 */
export async function rollCheckRequest(
  roomId: string,
  requestId: string,
  playerName: string,
): Promise<RollResultPayload> {
  return client.post<RollResultPayload, RollResultPayload>(
    `/rooms/${roomId}/check-requests/${requestId}/roll`,
    { player_name: playerName },
  )
}
