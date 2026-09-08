/**
 * WS 客户端单例 — 阶段 3.1。
 *
 * 职责：连接管理 + 心跳 + 断线重连 + 统一信封收发；不认识业务消息的含义
 * （消息分派在 stores/room.ts）。
 *
 * 心跳协议（§5.3）：每 15s 发 ping；连续两个周期没收到 pong 视为假死，
 * 主动断开触发 onclose 重连。指数退避留待阶段 3.4（与 room_state 补齐一起做）。
 */
import type { ChatEnvelope } from '@/types/ws'

type EnvelopeHandler = (msg: ChatEnvelope) => void
type StatusHandler = (connected: boolean) => void

const HEARTBEAT_INTERVAL = 15_000
const RECONNECT_DELAY = 2_000

class WsClient {
  private ws: WebSocket | null = null
  private roomId = ''
  private playerName = ''
  private envelopeHandler: EnvelopeHandler | null = null
  private statusHandler: StatusHandler | null = null
  private heartbeatTimer: number | null = null
  private reconnectTimer: number | null = null
  private lastPongAt = 0
  private closedByUser = false

  /** 建立连接并自动发送 join 注册身份 */
  connect(roomId: string, playerName: string, onEnvelope: EnvelopeHandler, onStatus: StatusHandler): void {
    // 同房间同身份的重复 connect（3.3 起可能发生：KP 控制台弹回 /room/:id 会
    // 二次 enterRoom）只换回调不重开连接，避免双 socket 重复收发信封
    if (
      this.ws?.readyState === WebSocket.OPEN &&
      this.roomId === roomId &&
      this.playerName === playerName
    ) {
      this.envelopeHandler = onEnvelope
      this.statusHandler = onStatus
      this.statusHandler?.(true)
      return
    }
    if (this.ws) this.close() // 换房间/换身份：先关旧连接再开新的
    this.roomId = roomId
    this.playerName = playerName
    this.envelopeHandler = onEnvelope
    this.statusHandler = onStatus
    this.closedByUser = false
    this.open()
  }

  private open(): void {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/${this.roomId}`)
    this.ws = ws
    // 实例守卫：被替换/主动关闭的旧 socket 的迟到回调不得触碰共享的
    // 心跳、状态回调与重连定时器（close() 置空 this.ws 后旧回调全部失效）
    const isCurrent = () => this.ws === ws

    ws.onopen = () => {
      if (!isCurrent()) return
      this.statusHandler?.(true)
      this.lastPongAt = Date.now()
      this.startHeartbeat()
      // 重连后也要重新 join：服务端以 join 注册的身份做广播与落库署名
      this.send('join', { player_name: this.playerName })
    }

    ws.onmessage = (ev) => {
      if (!isCurrent()) return
      try {
        const msg = JSON.parse(ev.data as string) as ChatEnvelope
        if (msg.type === 'pong') {
          this.lastPongAt = Date.now()
          return
        }
        this.envelopeHandler?.(msg)
      } catch {
        console.error('WS 消息解析失败:', ev.data)
      }
    }

    ws.onerror = () => {
      // 浏览器随后必然触发 onclose，重连逻辑统一在 onclose 里做
      console.error('WS 连接错误')
    }

    ws.onclose = () => {
      if (!isCurrent()) return
      this.stopHeartbeat()
      this.statusHandler?.(false)
      if (!this.closedByUser) {
        this.scheduleReconnect()
      }
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = window.setInterval(() => {
      if (Date.now() - this.lastPongAt > HEARTBEAT_INTERVAL * 2) {
        // 连续两个周期无 pong：连接假死，主动断开走 onclose 重连
        this.ws?.close()
        return
      }
      this.send('ping', {})
    }, HEARTBEAT_INTERVAL)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer !== null) return // 已有待执行的重连
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.open()
    }, RECONNECT_DELAY)
  }

  /** 业务消息统一从这里出（ping 心跳也走这个口，保持信封一致） */
  send(msgType: string, payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: msgType, payload }))
    } else {
      console.error('WS 未连接，消息未发送:', msgType)
    }
  }

  /** 主动关闭（离开房间时调用），不再自动重连 */
  close(): void {
    this.closedByUser = true
    this.stopHeartbeat()
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }
}

/** 进程级单例：与 Pinia store 同级使用，全应用共享一条连接 */
export const wsClient = new WsClient()
