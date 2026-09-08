/**
 * 房间 store — 阶段 3.1，3.2/3.3 加骰子与状态分派，3.4 加重连补齐 + room_state。
 *
 * 职责：持有房间会话状态（身份/成员/双聊天流/连接状态），把 WS 信封按
 * type/channel 分派到对应状态；连接恢复（false→true）时全量拉 history+state
 * 补齐离线期间错过的消息与最新房间状态。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { getRoomHistory, getRoomState, joinRoom } from '@/api/rooms'
import type { HistoryMessage } from '@/api/rooms'
import { wsClient } from '@/api/ws'
import type {
  AgentMode,
  AgentModeChangedPayload,
  CardStateSnapshot,
  Channel,
  ChatEnvelope,
  ChatItem,
  CheckRequestPayload,
  KpStyleChangedPayload,
  KpStyleRef,
  RollResultPayload,
  RoomStatePayload,
  SceneChangedPayload,
  StatusChangedPayload,
  SuggestionsPayload,
  WsMember,
} from '@/types/ws'

const roomKey = (roomId: string) => `coc_room_${roomId}`

/** delta 的展示符号：-3 → "-3"，+2 → "+2" */
const fmtDelta = (d: number) => (d >= 0 ? `+${d}` : `${d}`)

export const useRoomStore = defineStore('room', () => {
  // ---------- 身份 ----------
  const roomId = ref('')
  const playerName = ref('')
  const cardId = ref<string | null>(null)

  // ---------- 会话状态 ----------
  const members = ref<WsMember[]>([])
  const narrativeMsgs = ref<ChatItem[]>([])
  const oocMsgs = ref<ChatItem[]>([])
  const connected = ref(false)
  /** 各成员角色卡状态快照（status_changed 广播驱动，按 player_name 索引）；
   * 展示时优先于卡面值，无快照的成员回退各自拉到的卡 */
  const cardStates = ref<Record<string, CardStateSnapshot>>({})

  // 4.4+：关网页/刷新时 WS 帧发不出去，用 sendBeacon 显式告知「离开房间」。
  // 服务端只认显式 leave（WS leave 消息 / 本 beacon）为退出，其余断开按掉线
  // 处理——切标签页、后台节流、网络抖动都不会再把人判为退出。
  let leaveBeaconBound = false
  function bindLeaveBeacon(): void {
    if (leaveBeaconBound) return
    leaveBeaconBound = true
    window.addEventListener('pagehide', () => {
      if (!roomId.value || !playerName.value) return
      const blob = new Blob([JSON.stringify({ player_name: playerName.value })], {
        type: 'application/json',
      })
      navigator.sendBeacon(`/api/rooms/${roomId.value}/leave`, blob)
    })
  }
  /** 当前场景标题栏（scene_changed 广播 + GET /rooms/{id} 恢复） */
  const scene = ref<{ scene_title: string; scene_desc: string } | null>(null)
  // ---------- 4.1 协同建议 / 4.2 全自动主持 ----------
  /** Agent 模式（agent_mode_changed 广播 + GET /rooms/{id} 恢复驱动，不在本地先改） */
  const agentMode = ref<AgentMode>('manual')
  /** 最近一批候选建议（suggestions 信封，只定向发 KP）；degraded 时 error 有值 */
  const lastSuggestions = ref<SuggestionsPayload | null>(null)
  /** 生成中标记：玩家在协同模式下发剧情行动 / KP 点生成即置位，信封到达清除 */
  const suggestionsPending = ref(false)
  /** 4.2：AI 正在主持一轮（auto 模式下剧情推进置位，AI 叙事到达清除） */
  const keeperPending = ref(false)
  /** 4.4：房间当前 KP 风格（详情/state/切换广播三路驱动，回显不做本地先改） */
  const kpStyle = ref<KpStyleRef | null>(null)
  /** 4.3+ 检定下放：已结算的请求 id 集合（roll_result 带 request_id 或历史回放标记） */
  const fulfilledRequests = ref<Set<string>>(new Set())

  function markFulfilled(requestId: string): void {
    if (!fulfilledRequests.value.has(requestId)) {
      fulfilledRequests.value = new Set([...fulfilledRequests.value, requestId])
    }
  }

  /** 我的身份（从花名册按名对号；KP 重进/玩家重连都不会丢角色） */
  const myRole = computed<'kp' | 'player'>(() =>
    members.value.find((m) => m.player_name === playerName.value)?.role ?? 'player',
  )

  /** 信封分派：chat_new / roll_result 按频道入流，member_changed 整表替换 */
  function handleEnvelope(msg: ChatEnvelope): void {
    if (msg.type === 'chat_new') {
      const item: ChatItem = {
        sender: msg.sender,
        text: msg.payload.text ?? '',
        ts: msg.ts,
        channel: msg.channel,
        role: msg.payload.role,
        ai: msg.payload.ai,
        keeper: msg.payload.keeper,
        options: msg.payload.options,
        checkRequest: msg.payload.check_request === true
          ? (msg.payload as unknown as CheckRequestPayload)
          : undefined,
      }
      if (msg.channel === 'narrative') {
        // D8 兜底：keeper 行只应到达 KP 连接（服务端定向发送），非 KP 丢弃
        if (item.keeper && myRole.value !== 'kp') return
        // AI 主持叙事到达：清除「AI 主持中」状态
        if (item.ai) keeperPending.value = false
        narrativeMsgs.value.push(item)
        // 4.1：协同模式下玩家剧情行动会触发后台生成（仅 KP 面板感知），
        // 这里先置"生成中"，信封到达后清除——自动触发的即时 UI 反馈
        if (
          myRole.value === 'kp' &&
          agentMode.value === 'collab' &&
          item.role === 'player' &&
          item.text
        ) {
          suggestionsPending.value = true
        }
        // 4.2：全自动模式下剧情推进触发 AI 整轮主持（KP/玩家端都置「主持中」）
        if (agentMode.value === 'auto' && !item.ai && item.role !== 'system' && item.text) {
          keeperPending.value = true
        }
      } else if (msg.channel === 'ooc') {
        oocMsgs.value.push(item)
      } else {
        // 系统消息（进出房/开团等，已落库）固定渲染在剧情流（§8 布局图）。
        // 与流末行完全相同的系统行去重跳过：首连时历史回放与实时广播存在
        // 竞态窗口，同一行可能既被回放又被实时追加
        const last = narrativeMsgs.value[narrativeMsgs.value.length - 1]
        if (last && last.channel === 'system' && last.text === item.text && last.sender === item.sender) {
          return
        }
        narrativeMsgs.value.push(item)
      }
    } else if (msg.type === 'room_dissolved') {
      // KP 解散房间（解散端点在删数据前广播）：在线成员统一退出回大厅。
      // KP 本人由 quitRoom 的本地流程处理（exitRoom + 跳转已做），跳过避免双份提示
      if (msg.payload.operator === playerName.value || !roomId.value) return
      ElMessage.warning('KP 已解散房间，你已被移出本房间')
      exitRoom()
      router.push('/')
    } else if (msg.type === 'roll_result') {
      const roll = msg.payload as RollResultPayload
      // 暗骰兜底过滤（D8）：3.3 起服务端已定向发送（玩家连接协议层收不到），
      // 这里只防旧后端/异常路径泄漏
      if (roll.secret && myRole.value !== 'kp') return
      if (roll.request_id) markFulfilled(roll.request_id)
      narrativeMsgs.value.push({
        sender: msg.sender,
        text: '', // 骰子消息渲染彩色徽章，不使用 text
        ts: msg.ts,
        channel: 'narrative',
        role: members.value.find((m) => m.player_name === msg.sender)?.role ?? 'player',
        roll,
      })
    } else if (msg.type === 'status_changed') {
      const p = msg.payload as StatusChangedPayload
      // 剧情流灰色系统行：按旧快照算 delta（无旧值时退化为绝对值），含 reason（D9）
      const prev = cardStates.value[p.target]
      const parts: string[] = []
      if (prev) {
        if (p.hp !== prev.hp) {
          parts.push(`HP ${fmtDelta(p.hp - prev.hp)}（残余 ${p.hp}/${p.hp_max}）`)
        }
        if (p.sanity !== prev.sanity) {
          parts.push(`SAN ${fmtDelta(p.sanity - prev.sanity)}（残余 ${p.sanity}/${p.sanity_max}）`)
        }
      } else {
        parts.push(`HP ${p.hp}/${p.hp_max}`, `SAN ${p.sanity}/${p.sanity_max}`)
      }
      narrativeMsgs.value.push({
        sender: p.operator,
        text: `将 ${p.target} ${parts.join('、')}：${p.reason}`,
        ts: msg.ts,
        channel: 'narrative',
        status: p,
      })
      cardStates.value = {
        ...cardStates.value,
        [p.target]: { hp: p.hp, sanity: p.sanity, hp_max: p.hp_max, sanity_max: p.sanity_max },
      }
    } else if (msg.type === 'scene_changed') {
      const p = msg.payload as SceneChangedPayload
      scene.value = { scene_title: p.scene_title, scene_desc: p.scene_desc }
      // 与后端落库的 sys 文案保持一致（3.4 历史补齐时两边可对上）
      narrativeMsgs.value.push({
        sender: p.operator,
        text: `更新了场景：「${p.scene_title}」${p.scene_desc ? `（${p.scene_desc}）` : ''}`,
        ts: msg.ts,
        channel: 'system',
      })
    } else if (msg.type === 'room_state') {
      // 读档广播（3.4）：整表替换成员/场景/HP·SAN 快照；聊天流不动（时间线不回滚）
      const p = msg.payload as RoomStatePayload
      members.value = p.members ?? []
      scene.value = { ...p.scene }
      cardStates.value = { ...p.hp_sanity }
      if (p.style) kpStyle.value = { style_id: p.style.style_id, style_name: p.style.style_name }
    } else if (msg.type === 'suggestions') {
      // 4.1：候选建议批次（只定向发 KP，D8 同款定向；此处仅防异常路径泄漏）
      if (myRole.value !== 'kp') return
      const p = msg.payload as SuggestionsPayload
      lastSuggestions.value = p
      suggestionsPending.value = false
      // 4.4 遗留修复：auto 模式降级时后端也会发 suggestions 降级信封，
      // 据此清掉「AI 主持中」骨架（此前 keeperPending 只等 AI 叙事清除，失败时永久残留）
      if (p.status === 'degraded') keeperPending.value = false
    } else if (msg.type === 'kp_style_changed') {
      // 4.4：KP 切换风格全员广播——回显 + 系统行（后端 sys 消息已落库，历史回放同文案）
      const p = msg.payload as KpStyleChangedPayload
      kpStyle.value = { style_id: p.style_id, style_name: p.style_name }
      narrativeMsgs.value.push({
        sender: 'system',
        text: `KP ${p.operator} 将 KP 风格切换为「${p.style_name}」`,
        ts: msg.ts,
        channel: 'system',
      })
    } else if (msg.type === 'agent_mode_changed') {
      // 4.1/4.2：模式切换（KP 操作或连续失败自动降级）全员广播，回显驱动
      const p = msg.payload as AgentModeChangedPayload
      agentMode.value = p.agent_mode
      if (p.agent_mode === 'manual') {
        lastSuggestions.value = null
        suggestionsPending.value = false
        keeperPending.value = false
      } else if (p.agent_mode === 'auto') {
        // 切入全自动：建议面板清空，进入「AI 主持中」待命
        lastSuggestions.value = null
        suggestionsPending.value = false
      }
    } else if (msg.type === 'member_changed') {
      members.value = msg.payload.members ?? []
    } else if (msg.type === 'error') {
      console.error('服务端错误:', msg.payload.detail)
    }
  }

  // ==================== 3.4：历史回放 + 重连补齐 ====================

  /** 历史行按 type 还原成 ChatItem（与 handleEnvelope 各分支的渲染约定一致）。
   * 服务端按 id 倒序返回，这里正序回放；status 行用本地 map 模拟 delta 文案，
   * 不写 cardStates（cardStates 以 state 快照为准）。payload 缺失的行兜底
   * 渲染落库的可读文本。 */
  function replayHistory(rows: HistoryMessage[]): { narrative: ChatItem[]; ooc: ChatItem[] } {
    const narrative: ChatItem[] = []
    const ooc: ChatItem[] = []
    const statusSim: Record<string, CardStateSnapshot> = {}
    for (const r of [...rows].reverse()) {
      const ts = r.created_at
      if (r.type === 'dice') {
        const roll = (r.payload ?? null) as RollResultPayload | null
        if (roll?.request_id) markFulfilled(roll.request_id)
        narrative.push({
          sender: r.sender,
          text: roll?.roll ? '' : r.content, // 有结构化 payload 走彩色徽章，否则退化为文本
          ts,
          channel: 'narrative',
          role: r.role,
          roll: roll?.roll ? roll : undefined,
        })
      } else if (r.type === 'status') {
        const p = (r.payload ?? null) as StatusChangedPayload | null
        if (!p) {
          narrative.push({ sender: r.sender, text: r.content, ts, channel: 'narrative' })
          continue
        }
        const prev = statusSim[p.target]
        const parts: string[] = []
        if (prev) {
          if (p.hp !== prev.hp) {
            parts.push(`HP ${fmtDelta(p.hp - prev.hp)}（残余 ${p.hp}/${p.hp_max}）`)
          }
          if (p.sanity !== prev.sanity) {
            parts.push(`SAN ${fmtDelta(p.sanity - prev.sanity)}（残余 ${p.sanity}/${p.sanity_max}）`)
          }
        } else {
          parts.push(`HP ${p.hp}/${p.hp_max}`, `SAN ${p.sanity}/${p.sanity_max}`)
        }
        statusSim[p.target] = {
          hp: p.hp, sanity: p.sanity, hp_max: p.hp_max, sanity_max: p.sanity_max,
        }
        narrative.push({
          sender: p.operator,
          text: `将 ${p.target} ${parts.join('、')}：${p.reason}`,
          ts,
          channel: 'narrative',
          status: p,
        })
      } else if (r.type === 'check_request') {
        // 检定下放请求行（4.3+）：payload 缺失时退化为可读文本
        const cr = (r.payload ?? null) as CheckRequestPayload | null
        narrative.push(
          cr
            ? { sender: r.sender, text: '', ts, channel: 'narrative', role: r.role, checkRequest: cr }
            : { sender: r.sender, text: r.content, ts, channel: 'narrative', role: r.role },
        )
      } else if (r.type === 'sys') {
        // 场景变更/读档/进出房等系统行（均落库，历史回放可还原）
        narrative.push({ sender: r.sender, text: r.content, ts, channel: 'system', role: r.role })
      } else {
        // text：按落库 channel 入流（4.2：AI 主持行带 ai/options，keeper 行带 keeper）
        const item: ChatItem = {
          sender: r.sender, text: r.content, ts, channel: r.channel, role: r.role,
          ai: (r.payload as Record<string, unknown> | null)?.ai === true,
          keeper: (r.payload as Record<string, unknown> | null)?.keeper === true,
          options: (r.payload as Record<string, unknown> | null)?.options as string[] | undefined,
        }
        if (r.channel === 'ooc') {
          ooc.push(item)
        } else {
          narrative.push(item)
        }
      }
    }
    // 历史回放统一打标：徽章动画 class 据此跳过，重连/进房不重播入场动画（2.5②）
    for (const item of [...narrative, ...ooc]) item.history = true
    return { narrative, ooc }
  }

  let syncInFlight = false
  let everConnected = false

  /**
   * 连接恢复（false→true）后的状态补齐：全量拉 history + state。
   * 服务端先落库后广播，同步窗口内极小概率漏的消息由下次补齐兜底
   * （MVP 用全量拉取替代 seq 增量同步，翻页/无限滚动明确不做）。
   * isReconnect=false 为首次连上（进房/刷新页面），同样补齐但不弹 toast。
   */
  async function syncAfterReconnect(isReconnect: boolean): Promise<void> {
    if (!roomId.value || syncInFlight) return
    syncInFlight = true
    try {
      const beforeCount = narrativeMsgs.value.length + oocMsgs.value.length
      const [history, state] = await Promise.all([
        getRoomHistory(roomId.value, playerName.value),
        getRoomState(roomId.value),
      ])
      members.value = state.members
      scene.value = { ...state.scene }
      cardStates.value = { ...state.hp_sanity }
      if (state.style) kpStyle.value = { style_id: state.style.style_id, style_name: state.style.style_name }
      const replayed = replayHistory(history.messages)
      narrativeMsgs.value = replayed.narrative
      oocMsgs.value = replayed.ooc
      const missed = Math.max(0, history.messages.length - beforeCount)
      if (isReconnect && missed > 0) {
        ElMessage.success(`已同步 ${missed} 条离线消息`)
      }
    } catch {
      // 拦截器已提示；连接还在，下次重连再补齐
    } finally {
      syncInFlight = false
    }
  }

  /**
   * 进房：记身份 → 本地留档（刷新页面免重输）→ 建立 WS 连接。
   * 路由 query 带身份时优先用 query，否则从 localStorage 恢复。
   * 换房进入（ roomId 变化）时清空上一间房的会话状态——cardStates 按
   * 玩家名索引，不清会把旧房的 HP/SAN 快照带进新房（同名开新房血条沿用旧值的 bug）。
   */
  function enterRoom(id: string, name: string, cid: string | null): void {
    if (roomId.value && roomId.value !== id) {
      members.value = []
      narrativeMsgs.value = []
      oocMsgs.value = []
      cardStates.value = {}
      scene.value = null
      kpStyle.value = null
      // 4.1：建议是 KP 屏内的会话态，换房不带走（agent_mode 由详情接口/广播回填）
      lastSuggestions.value = null
      suggestionsPending.value = false
      keeperPending.value = false
      fulfilledRequests.value = new Set()
      agentMode.value = 'manual'
      everConnected = false // 换房后首次连上不算重连
    }
    roomId.value = id
    playerName.value = name
    cardId.value = cid
    bindLeaveBeacon()
    localStorage.setItem(roomKey(id), JSON.stringify({ playerName: name, cardId: cid }))
    // 幂等补行（4.4+）：显式 leave（含刷新页面的 pagehide beacon）会删花名册行，
    // 而 WS join 不建行——这里按"行在则幂等返回、删了则带 card_id 重建"补齐，
    // 修复"刷新页面后被 beacon 判离房、身份恢复后花名册缺行"的回归。
    // 解散后的房间 404 静默吞掉（此时页面马上会被 room_dissolved/守卫带走）。
    void joinRoom(id, name, cid).catch(() => {})
    wsClient.connect(id, name, handleEnvelope, (ok) => {
      const was = connected.value
      connected.value = ok
      // false→true（含首次连上）：拉 history + state 补齐；仅真重连弹 toast
      if (ok && !was) {
        const isReconnect = everConnected
        everConnected = true
        void syncAfterReconnect(isReconnect)
      }
    })
  }

  /** 只读窥视本地房间身份（不建连）：KP 控制台守卫先验证身份再决定是否 enterRoom */
  function peekIdentity(id: string): { playerName: string; cardId: string | null } | null {
    const raw = localStorage.getItem(roomKey(id))
    if (!raw) return null
    try {
      const saved = JSON.parse(raw) as { playerName: string; cardId: string | null }
      if (!saved.playerName) return null
      return saved
    } catch {
      return null
    }
  }

  /** 尝试从本地恢复房间身份（刷新页面场景），恢复成功返回 true */
  function restoreIdentity(id: string): boolean {
    const raw = localStorage.getItem(roomKey(id))
    if (!raw) return false
    try {
      const saved = JSON.parse(raw) as { playerName: string; cardId: string | null }
      if (!saved.playerName) return false
      enterRoom(id, saved.playerName, saved.cardId)
      return true
    } catch {
      return false
    }
  }

  /** 发聊天消息（channel 决定进剧情流还是闲聊流） */
  function sendChat(channel: Exclude<Channel, 'system'>, text: string): void {
    wsClient.send('chat_send', { channel, text })
  }

  /** 离开房间：主动断开，服务端会广播离开消息 */
  function leaveRoom(): void {
    wsClient.close()
    connected.value = false
  }

  /** 退出房间并清空会话状态（回大厅前调用；解散等动作由视图层先处理） */
  function exitRoom(): void {
    leaveRoom()
    localStorage.removeItem(roomKey(roomId.value))
    roomId.value = ''
    playerName.value = ''
    cardId.value = null
    members.value = []
    narrativeMsgs.value = []
    oocMsgs.value = []
    cardStates.value = {}
    scene.value = null
    kpStyle.value = null
    lastSuggestions.value = null
    suggestionsPending.value = false
    keeperPending.value = false
    fulfilledRequests.value = new Set()
    agentMode.value = 'manual'
    everConnected = false
  }

  return {
    roomId,
    playerName,
    cardId,
    members,
    narrativeMsgs,
    oocMsgs,
    connected,
    cardStates,
    scene,
    myRole,
    agentMode,
    kpStyle,
    lastSuggestions,
    suggestionsPending,
    keeperPending,
    fulfilledRequests,
    markFulfilled,
    enterRoom,
    peekIdentity,
    restoreIdentity,
    sendChat,
    leaveRoom,
    exitRoom,
  }
})
