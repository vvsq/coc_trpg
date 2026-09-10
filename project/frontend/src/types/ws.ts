/**
 * WS 消息协议与房间相关 TS 类型 — 与后端 app/ws/manager.py 的
 * build_envelope() 信封一一对应，改动必须双侧同步（goal.md §5.3）。
 */

/** 频道：narrative 剧情流 / ooc 闲聊流 / system 系统提示 */
export type Channel = 'narrative' | 'ooc' | 'system'

/** 统一消息信封 */
export interface ChatEnvelope {
  type: string // chat_new / member_changed / pong / error
  room_id: string
  sender: string
  channel: Channel
  payload: Record<string, any>
  ts: string
}

/** 房间成员（REST join 返回值与 WS member_changed 广播共用） */
export interface WsMember {
  player_name: string
  role: 'kp' | 'player'
  card_id: string | null
}

/** 聊天流里的一条消息（信封 payload 摊平后的 UI 形态） */
export interface ChatItem {
  sender: string
  text: string
  ts: string
  channel: Channel
  role?: 'kp' | 'player' | 'system' // 随 chat_new 下发，前端区分 KP 剧情/玩家行动
  roll?: RollResultPayload // 掷骰消息（3.2）：有此字段按彩色徽章渲染，text 不用
  status?: StatusChangedPayload // 状态变更行（3.3）：有此字段按灰色小字渲染，含 reason
  history?: boolean // 历史回放行（2.5②）：重连/进房补齐的消息不重播骰子入场动画
  ai?: boolean // AI 主持叙事（4.2）：带头像标识 + 行动切口选项按钮
  keeper?: boolean // KP 专享行（4.2）：AI 的 keeper 笔记/暗骰详情，仅 KP 端可见
  options?: string[] // 行动切口（4.2）：ai 消息附带的可点击选项
  checkRequest?: CheckRequestPayload // 检定下放（4.3+）：被点名玩家可点「投掷」
}

/** POST /rooms 响应 */
export interface RoomCreated {
  room_id: string
  name: string
}

/** GET /rooms 列表项 */
export interface RoomListItem {
  room_id: string
  name: string
  kp_name: string
  created_at: string
}

// ==================== 阶段 3.2：掷骰结果 ====================

/** 成功等级（与后端 rules/coc7.py 的 SuccessLevel 一一对应） */
export type RollLevel = 'critical' | 'extreme' | 'hard' | 'regular' | 'fail' | 'fumble'

/** 骰值细节（后端 rules/dice.py 的 D100Roll 序列化） */
export interface RollDetail {
  units: number // 个位骰 0~9
  tens: number[] // 十位骰列表（奖惩骰时多个）
  value: number // 最终读数 1~100
  bonus: number // 净奖励骰数
  penalty: number // 净惩罚骰数
}

/** roll_result 信封 payload（与后端 api/dice.py 的 _result_payload 一一对应） */
export interface RollResultPayload {
  sender: string
  skill_name: string
  detail: string
  value: number // 技能当前值（检定目标的全值）
  difficulty: 'standard' | 'hard' | 'extreme'
  level: RollLevel
  level_label: string
  target: number // 按难度折算后的目标值
  roll: RollDetail
  secret: boolean
  request_id?: string // 检定下放（4.3+）：结算的请求 id，前端据此销按钮
}

/** 检定下放请求（4.3+：AI 定技能/难度/后果，玩家本人投掷；工具层与投掷端点同构） */
export interface CheckRequestPayload {
  request_id: string
  target: string
  skill_name: string
  difficulty: 'standard' | 'hard' | 'extreme'
  value: number // 服务端按角色卡查好的技能值（玩家不可篡改，D5）
  reason: string
  fulfilled: boolean
}

/** 等级 → 徽章配色（大成功金/极难蓝/困难绿/常规白/失败灰/大失败红）。
 * 常规与失败同属"无色系"，靠背景深浅区分：常规白底灰边，失败灰底灰字。 */
export const ROLL_BADGE_STYLES: Record<RollLevel, { border: string; bg: string; text: string }> = {
  critical: { border: '#d4a017', bg: '#fdf6ec', text: '#b8860b' }, // 金
  extreme: { border: '#409eff', bg: '#ecf5ff', text: '#2f7fd1' }, // 蓝
  hard: { border: '#67c23a', bg: '#f0f9eb', text: '#529b2e' }, // 绿
  regular: { border: '#dcdfe6', bg: '#ffffff', text: '#606266' }, // 白（中性）
  fail: { border: '#cdd0d6', bg: '#f4f4f5', text: '#909399' }, // 灰
  fumble: { border: '#f56c6c', bg: '#fef0f0', text: '#d03050' }, // 红
}

/** 等级 → 中文标签（后端有 level_label，此表仅作兜底） */
export const ROLL_LEVEL_LABELS: Record<RollLevel, string> = {
  critical: '大成功',
  extreme: '极难成功',
  hard: '困难成功',
  regular: '常规成功',
  fail: '失败',
  fumble: '大失败',
}

// ==================== 阶段 3.3：KP 控制台（状态变更 / 场景标题栏） ====================

/** status_changed 信封 payload（与后端 api/kp.py 的 update_status 一一对应）。
 * hp/sanity 是 clamp 后的绝对值，delta 由前端按 cardStates 旧值计算 */
export interface StatusChangedPayload {
  target: string
  hp: number
  sanity: number
  hp_max: number
  sanity_max: number
  reason: string // D9：变更原因必填
  operator: string // 操作者（KP 名）
}

/** scene_changed 信封 payload（与后端 api/kp.py 的 update_scene 一一对应） */
export interface SceneChangedPayload {
  scene_title: string
  scene_desc: string
  operator: string
}

/** 某玩家角色卡状态的最新快照：status_changed 广播驱动，展示时优先于卡面值 */
export interface CardStateSnapshot {
  hp: number
  sanity: number
  hp_max: number
  sanity_max: number
}

// ==================== 阶段 3.4：room_state 全量快照（重连补齐 / 读档广播） ====================

/** room_state 信封 payload（与 GET /rooms/{id}/state 及后端 build_room_state 一一对应）。
 * members 是"在线 ∩ 花名册"；hp_sanity 按持久花名册全量给（离线成员也有） */
export interface RoomStatePayload {
  members: WsMember[]
  scene: { scene_title: string; scene_desc: string }
  hp_sanity: Record<string, CardStateSnapshot>
  style?: KpStyleRef // 4.4：当前 KP 风格（重连/读档补齐用）
}

// ==================== 阶段 4.4：KP 风格系统（goal §6.2） ====================

/** 房间当前 KP 风格的展示摘要（详情接口 / state 快照 / 切换广播同构） */
export interface KpStyleRef {
  style_id: string
  style_name: string
}

/** 四旋钮风格参数（与后端 kp_styles.py VALID_KNOBS 一一对应） */
export interface KpStyleParams {
  narrative_density: 'high' | 'medium' | 'low'
  rule_explanation: 'high' | 'medium' | 'low'
  hidden_roll_transparency: 'high' | 'medium' | 'low'
  option_granularity: 'high' | 'medium' | 'fine' | 'coarse' | 'low'
  note?: string
}

/** kp_style_changed 信封 payload（KP 切换风格时全员广播，前端推系统行+回显） */
export interface KpStyleChangedPayload extends KpStyleRef {
  operator: string
}

// ==================== 阶段 5：房间挂载模组（goal §7） ====================

/** 房间当前模组的展示摘要（详情接口 / 切换广播同构）；未挂载时接口返回 null */
export interface RoomModuleRef {
  module_id: number
  module_name: string
  parse_status: string
}

/** module_changed 信封 payload：module 为 null 表示解绑（回退默认骨架） */
export interface ModuleChangedPayload {
  module: RoomModuleRef | null
  operator: string
}

// ==================== 阶段 4.1：协同建议模式（决策 D10） ====================

/** Agent 模式：manual 纯人工 / collab 协同建议 / auto 全自动主持（4.2） */
export type AgentMode = 'manual' | 'collab' | 'auto'

/** 建议附带的检定提示（difficulty 与后端 rules/coc7.py 的 Difficulty 一一对应） */
export interface SuggestionCheckHint {
  skill: string
  difficulty: 'standard' | 'hard' | 'extreme'
  stake: string
}

/** 单条候选建议 */
export interface SuggestionItem {
  text: string
  check_hint: SuggestionCheckHint | null
}

/** suggestions 信封 payload（后端 SuggestionEngine._payload 一一对应）。
 * 只定向广播给 KP（D8 同款定向）；status=degraded 时 error 为中文原因 */
export interface SuggestionsPayload {
  request_id: string
  status: 'ok' | 'degraded'
  suggestions: SuggestionItem[]
  trigger: 'auto' | 'manual'
  created_at: string
  model?: string
  error?: string
  category?: string
}

/** agent_mode_changed 信封 payload（KP 切换模式 / 连续失败自动降级时全员广播） */
export interface AgentModeChangedPayload {
  agent_mode: AgentMode
  operator?: string
}
