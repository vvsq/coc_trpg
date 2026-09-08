/**
 * 掷骰 REST 封装 — 阶段 3.2。
 *
 * 服务端权威（D5）：掷骰与判定只发生在这里调用的后端接口里，前端不本地
 * 掷骰、不本地插入结果——聊天流里的骰子徽章全部由 roll_result 广播驱动。
 */
import { client } from './client'
import type { RollResultPayload } from '@/types/ws'

/** POST /dice/check 请求体（与后端 CheckRequest 对应） */
export interface DiceCheckRequest {
  room_id: string
  sender: string
  skill_name: string
  detail: string
  difficulty: 'standard' | 'hard' | 'extreme'
  bonus: number
  penalty: number
  value: number // 技能当前值（MVP 由前端 skillValue() 算出后携带）
  secret: boolean
}

/** 发起技能检定：返回值只用于按钮反馈/异常提示，结果展示等广播 */
export async function diceCheck(payload: DiceCheckRequest): Promise<RollResultPayload> {
  return client.post<RollResultPayload, RollResultPayload>('/dice/check', payload)
}
