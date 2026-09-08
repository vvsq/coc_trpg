<script setup lang="ts">
/**
 * KP 控制台（三栏）— 阶段 3.3。
 *
 * 左：玩家面板（成员卡片：名字/职业/HP·SAN 条，≤30% 红色预警；点开 el-drawer 拉整卡）
 * 中：剧情聊天流（复用 components/ChatStream.vue，与玩家视图同源）
 * 右：KP 工具箱（场景标题栏编辑 / 掷骰面板沿用 3.2 且暗骰默认勾选 / 扣 HP·SAN / 存档读档占位）
 *
 * 身份与守卫：房间表 kp_name 即唯一 KP（花名册同源不变量），REST 先于 WS 建连
 * 校验——非 KP 访客不连 WS 直接弹回 /room/:id（路由守卫无法等待异步数据，故在视图内做）。
 * 数值改动不在本地自改：调 status API 后由 status_changed 广播驱动全部界面。
 */
import { computed, reactive, ref, watch, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createCheckRequest,
  getRoom,
  listSaves,
  loadSave,
  saveGame,
  startGame,
  updateRoomScene,
  updateRoomStatus,
  type RoomDetail,
  type RoomStatusChange,
  type SaveMeta,
} from '@/api/rooms'
import { getCard } from '@/api/cards'
import { useRoomStore } from '@/stores/room'
import { useQuitRoom } from '@/composables/useQuitRoom'
import ChatStream from '@/components/ChatStream.vue'
import SkillCheckPanel from '@/components/SkillCheckPanel.vue'
import AiSuggestionPanel from '@/components/AiSuggestionPanel.vue'
import KpStylePanel from '@/components/KpStylePanel.vue'
import LlmSettingsDialog from '@/components/LlmSettingsDialog.vue'
import { eraLabel, skillValue, type Investigator, type Skill } from '@/types/investigator'
import type { WsMember } from '@/types/ws'

const route = useRoute()
const router = useRouter()
const room = useRoomStore()
const { quitRoom } = useQuitRoom()

/** 本视图是否真的建立过连接（守卫弹回路径未建连，卸载时不得拆连接） */
let didConnect = false

// ---------- 玩家面板：成员卡缓存 ----------
/** 成员 → 整卡（职业与卡面 HP/SAN 由此来；status_changed 快照会覆盖展示值） */
const cardMap = ref<Record<string, Investigator>>({})

async function fetchMissingCards(members: WsMember[]): Promise<void> {
  const jobs = members
    .filter((m) => m.card_id && !cardMap.value[m.player_name])
    .map(async (m) => {
      try {
        const card = await getCard(m.card_id as string)
        cardMap.value = { ...cardMap.value, [m.player_name]: card }
      } catch {
        // 单张卡失败不阻塞面板（拦截器已提示）
      }
    })
  await Promise.all(jobs)
}

// 成员进出场（member_changed）时增量补拉新绑卡的成员
watch(() => room.members, (v) => void fetchMissingCards(v), { immediate: true })

/** 成员展示状态：status_changed 快照优先（广播驱动），否则回退卡面值 */
function memberState(name: string) {
  const snap = room.cardStates[name]
  const card = cardMap.value[name]
  return {
    hp: snap?.hp ?? card?.state.current_hp ?? 0,
    hp_max: snap?.hp_max ?? card?.derived.HP ?? 0,
    sanity: snap?.sanity ?? card?.state.current_sanity ?? 0,
    sanity_max: snap?.sanity_max ?? card?.derived.SAN ?? 0,
    occupation: card?.occupation ?? '',
    hasCard: Boolean(card),
  }
}

const LOW_RATIO = 0.3

function isLow(cur: number, max: number): boolean {
  return max > 0 && cur / max <= LOW_RATIO
}

function barColor(cur: number, max: number, base: string): string {
  return isLow(cur, max) ? '#f56c6c' : base
}

function memberBars(name: string) {
  const s = memberState(name)
  return [
    { label: 'HP', cur: s.hp, max: s.hp_max, color: barColor(s.hp, s.hp_max, '#F56C6C') },
    { label: 'SAN', cur: s.sanity, max: s.sanity_max, color: barColor(s.sanity, s.sanity_max, '#9B59B6') },
  ]
}

function isWarn(name: string): boolean {
  const s = memberState(name)
  return isLow(s.hp, s.hp_max) || isLow(s.sanity, s.sanity_max)
}

// ---------- 整卡抽屉 ----------
const drawerVisible = ref(false)
const drawerMember = ref<WsMember | null>(null)
const drawerCard = ref<Investigator | null>(null)
const drawerLoading = ref(false)

const ATTR_LABELS: Record<string, string> = {
  STR: '力量', CON: '体质', SIZ: '体型', DEX: '敏捷', APP: '外貌',
  INT: '智力', POW: '意志', EDU: '教育', LUK: '幸运',
}

const BG_LABELS: Record<string, string> = {
  personal_description: '个人描述',
  ideology_beliefs: '思想信念',
  significant_people: '重要之人',
  meaningful_location: '意义之地',
  treasured_possession: '宝贵之物',
  traits: '特质',
  scars_injuries: '伤痕',
  cash_assets: '资产',
}

async function openCardDrawer(m: WsMember): Promise<void> {
  if (!m.card_id) return
  drawerMember.value = m
  drawerVisible.value = true
  drawerLoading.value = true
  try {
    drawerCard.value = await getCard(m.card_id)
  } catch {
    // 拦截器已弹错误提示
  } finally {
    drawerLoading.value = false
  }
}

// ---------- 开团（waiting → playing 状态流转） ----------
const gameStatus = ref<'waiting' | 'playing'>('waiting')
const starting = ref(false)

async function onStart(): Promise<void> {
  starting.value = true
  try {
    await startGame(room.roomId, room.playerName)
    gameStatus.value = 'playing'
    // 本地 scene 由 scene_changed 广播回填的思路一致：开团提示行走 chat_new 广播，
    // 这里只切本地面板状态
    ElMessage.success('已宣布开团，大厅不再展示本房间')
  } catch {
    // 拦截器统一提示
  } finally {
    starting.value = false
  }
}

// ---------- 场景标题栏 ----------
const sceneForm = reactive({ scene_title: '', scene_desc: '' })
const sceneSubmitting = ref(false)

// 读档/重连补齐会把 room.scene 整体替换（room_state 广播），表单跟随同步
watch(
  () => room.scene,
  (s) => {
    if (s) {
      sceneForm.scene_title = s.scene_title
      sceneForm.scene_desc = s.scene_desc
    }
  },
)

async function submitScene(): Promise<void> {
  if (!sceneForm.scene_title.trim()) {
    ElMessage.warning('场景标题不能为空')
    return
  }
  sceneSubmitting.value = true
  try {
    await updateRoomScene(room.roomId, {
      kp_name: room.playerName,
      scene_title: sceneForm.scene_title.trim(),
      scene_desc: sceneForm.scene_desc.trim(),
    })
    // 本地 scene 由 scene_changed 广播回填，不在这里自改
  } catch {
    // 拦截器统一提示
  } finally {
    sceneSubmitting.value = false
  }
}

// ---------- 扣 HP / 扣 SAN ----------
const statusForm = reactive({
  target: '',
  hpDelta: 0,
  sanDelta: 0,
  reason: '',
})
const statusSubmitting = ref(false)
/** 提交成功后自增，强制重挂两个 el-input-number（防止显示残留旧调整量） */
const statusFormTick = ref(0)

/** 扣血目标 = 在线绑卡成员 ∪ cardStates 花名册成员（3.4）。
 * cardStates 的键来自 state 接口，按持久花名册给全——玩家断线时 KP 也能扣他的血，
 * 正是断线补齐场景的核心动作 */
const statusTargets = computed<WsMember[]>(() => {
  const online = room.members.filter((m) => m.card_id)
  const onlineNames = new Set(online.map((m) => m.player_name))
  const offline = Object.keys(room.cardStates)
    .filter((n) => !onlineNames.has(n))
    .map((n) => ({ player_name: n, role: 'player' as const, card_id: null }))
  return [...online, ...offline]
})

async function submitStatus(): Promise<void> {
  if (!statusForm.target) {
    ElMessage.warning('先选择要调整的成员')
    return
  }
  if (!statusForm.reason.trim()) {
    ElMessage.warning('变更原因必填（D9：一切数值变更必须可溯源）')
    return
  }
  if (!statusForm.hpDelta && !statusForm.sanDelta) {
    ElMessage.warning('HP / SAN 调整量至少填一个非零值')
    return
  }
  const st = memberState(statusForm.target)
  const body: RoomStatusChange = {
    kp_name: room.playerName,
    target: statusForm.target,
    reason: statusForm.reason.trim(),
  }
  if (statusForm.hpDelta) body.hp = Math.max(0, st.hp + statusForm.hpDelta)
  if (statusForm.sanDelta) body.sanity = Math.max(0, st.sanity + statusForm.sanDelta)
  statusSubmitting.value = true
  try {
    const res = await updateRoomStatus(room.roomId, body)
    ElMessage.success(`已调整 ${res.target}：HP ${res.hp}/${res.hp_max} · SAN ${res.sanity}/${res.sanity_max}`)
    statusForm.hpDelta = 0
    statusForm.sanDelta = 0
    statusForm.reason = ''
    statusFormTick.value++
  } catch {
    // 拦截器统一提示
  } finally {
    statusSubmitting.value = false
  }
}

// ---------- 检定下放（4.4+：KP 手动「要求玩家投骰」，collab/manual 模式可用） ----------
const crForm = reactive({
  target: '',
  skill: '',
  difficulty: 'standard' as 'standard' | 'hard' | 'extreme',
  reason: '',
})
const crSubmitting = ref(false)

/** 目标玩家的卡面技能选项（下拉数据源），label 带当前值 */
const crSkillOptions = computed<{ label: string; name: string }[]>(() => {
  const card = crForm.target ? cardMap.value[crForm.target] : null
  if (!card) return []
  return card.skills.map((s: Skill) => ({
    label: `${s.name}${s.detail ? `（${s.detail}）` : ''} ${skillValue(s)}`,
    name: s.name,
  }))
})

async function submitCheckRequest(): Promise<void> {
  if (!crForm.target) {
    ElMessage.warning('先选择被点名投骰的成员')
    return
  }
  if (!crForm.skill.trim()) {
    ElMessage.warning('先选择或输入技能名')
    return
  }
  if (!crForm.reason.trim()) {
    ElMessage.warning('检定缘由必填（会展示给玩家）')
    return
  }
  crSubmitting.value = true
  try {
    await createCheckRequest(room.roomId, {
      kp_name: room.playerName,
      target: crForm.target,
      skill_name: crForm.skill.trim(),
      difficulty: crForm.difficulty,
      reason: crForm.reason.trim(),
    })
    ElMessage.success(`已要求 ${crForm.target} 投掷，等 TA 在剧情流点「投掷」`)
    crForm.skill = ''
    crForm.reason = ''
  } catch {
    // 拦截器统一提示（技能不在其卡上 / 目标未绑卡等）
  } finally {
    crSubmitting.value = false
  }
}

// ---------- 存档 / 读档（3.4） ----------
const saving = ref(false)
const savesLoading = ref(false)
const loadingSave = ref(false)
const loadDialogVisible = ref(false)
const saves = ref<SaveMeta[]>([])
const selectedSaveId = ref<number | null>(null)

// ---------- LLM 设置（4.1+ 最小 KP 设置面板） ----------
const llmSettingsVisible = ref(false)

async function onSave(): Promise<void> {
  let name: string
  try {
    const { value } = await ElMessageBox.prompt('给这个时点起个名字，如：第一章·码头夜战', '创建存档', {
      confirmButtonText: '存档',
      cancelButtonText: '取消',
      inputPattern: /\S+/,
      inputErrorMessage: '存档名称不能为空',
    })
    name = value.trim()
  } catch {
    return // 用户取消
  }
  saving.value = true
  try {
    const created = await saveGame(room.roomId, room.playerName, name)
    ElMessage.success(`已创建存档「${created.name}」`)
  } catch {
    // 拦截器统一提示
  } finally {
    saving.value = false
  }
}

async function onOpenLoadDialog(): Promise<void> {
  loadDialogVisible.value = true
  savesLoading.value = true
  selectedSaveId.value = null
  try {
    saves.value = await listSaves(room.roomId)
  } catch {
    // 拦截器统一提示
  } finally {
    savesLoading.value = false
  }
}

function fmtSaveTime(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ')
}

async function confirmLoad(): Promise<void> {
  if (!selectedSaveId.value) return
  const target = saves.value.find((s) => s.id === selectedSaveId.value)
  try {
    await ElMessageBox.confirm(
      '读档将以存档时点覆盖当前房间的成员、角色卡状态与场景，且不可撤销。确定继续？',
      '覆盖警告',
      { type: 'warning', confirmButtonText: '覆盖读档', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  loadingSave.value = true
  try {
    await loadSave(room.roomId, selectedSaveId.value, room.playerName)
    ElMessage.success(`已回到存档「${target?.name ?? ''}」的时点`)
    loadDialogVisible.value = false
    // 界面由 room_state 广播驱动（D5）；卡面缓存清掉重拉，防止展示读档前的旧值
    cardMap.value = {}
    void fetchMissingCards(room.members)
  } catch {
    // 拦截器统一提示
  } finally {
    loadingSave.value = false
  }
}

onMounted(async () => {
  const id = String(route.params.id)
  const name = String(route.query.name ?? '')
  const cid = route.query.card_id ? String(route.query.card_id) : null

  // 房间与 KP 守卫先于建连：候选身份 = query name > localStorage（peek 只读不建连），
  // 非 KP 访客在不建立任何 WS 连接的情况下直接弹回（修复弹回竞态导致的僵尸连接）
  let detail: RoomDetail
  try {
    detail = await getRoom(id)
  } catch {
    router.replace('/')
    return
  }
  const candidate = name || room.peekIdentity(id)?.playerName || ''
  if (!candidate) {
    ElMessage.error('缺少身份，请从大厅重新进入房间')
    router.replace('/')
    return
  }
  if (candidate !== detail.kp_name) {
    ElMessage.warning('只有 KP 能进入控制台，已回到房间页')
    router.replace(`/room/${id}`)
    return
  }

  // 确认是 KP 才建连
  didConnect = true
  if (name) {
    room.enterRoom(id, name, cid)
  } else {
    room.restoreIdentity(id)
  }

  // 场景标题栏初值（此后由 scene_changed 广播驱动）
  room.scene = detail.scene
  sceneForm.scene_title = detail.scene.scene_title
  sceneForm.scene_desc = detail.scene.scene_desc
  // KP 风格回显（此后由 kp_style_changed 广播驱动）
  room.kpStyle = { style_id: detail.style.style_id, style_name: detail.style.style_name }
  // 开团状态面板初值（读档/重开均以房间表为准）
  gameStatus.value = detail.status === 'playing' ? 'playing' : 'waiting'
})

onUnmounted(() => {
  // 导航仍落在房间系路由（控制台⇄房间页互跳）时不拆连接，由目标视图接管；
  // 只有真正离开房间系路由才断开
  const toName = router.currentRoute.value.name
  if (!didConnect || toName === 'room' || toName === 'kp-console') return
  room.leaveRoom()
})
</script>

<template>
  <main class="kp-page">
    <!-- 顶栏：房间信息 + 场景标题栏 + 连接状态 -->
    <header class="room-header">
      <div class="room-title">
        <span class="room-tag">房间</span>
        <span class="room-code">{{ room.roomId }}</span>
        <el-tooltip
          v-if="room.scene?.scene_title"
          :content="room.scene.scene_desc || room.scene.scene_title"
          placement="bottom"
        >
          <span class="scene-chip">📍 {{ room.scene.scene_title }}</span>
        </el-tooltip>
      </div>
      <div class="header-right">
        <el-tag :type="room.connected ? 'success' : 'danger'" effect="dark" size="small" round>
          {{ room.connected ? '已连接' : '重连中…' }}
        </el-tag>
        <span class="me">{{ room.playerName }}</span>
        <el-tag type="warning" size="small" effect="plain">KP 控制台</el-tag>
        <el-button text size="small" class="quit-btn" @click="quitRoom">退出房间</el-button>
      </div>
    </header>

    <div class="kp-body">
      <!-- 左栏：玩家面板 -->
      <aside class="player-panel">
        <h3 class="panel-title">调查团（{{ room.members.length }}）</h3>
        <div
          v-for="m in room.members"
          :key="m.player_name"
          class="member-card"
          :class="{ 'member-card--warn': isWarn(m.player_name) }"
          @click="openCardDrawer(m)"
        >
          <div class="member-head">
            <span class="avatar">{{ m.player_name.slice(0, 1) }}</span>
            <div class="member-info">
              <div class="member-name-row">
                <span class="member-name">{{ m.player_name }}</span>
                <el-tag :type="m.role === 'kp' ? 'warning' : 'info'" size="small" effect="plain">
                  {{ m.role === 'kp' ? 'KP' : '玩家' }}
                </el-tag>
              </div>
              <p class="member-occ">
                {{ memberState(m.player_name).occupation || '未绑定角色卡' }}
              </p>
            </div>
          </div>
          <template v-if="memberState(m.player_name).hasCard">
            <div v-for="b in memberBars(m.player_name)" :key="b.label" class="stat-row">
              <span class="stat-label">{{ b.label }}</span>
              <el-progress
                class="stat-bar"
                :percentage="b.max > 0 ? Math.round((b.cur / b.max) * 100) : 0"
                :stroke-width="8"
                :color="b.color"
              />
              <span class="stat-num">{{ b.cur }}/{{ b.max }}</span>
            </div>
          </template>
          <div v-if="isWarn(m.player_name)" class="warn-row">
            <el-tag type="danger" size="small" effect="dark">⚠ HP/SAN ≤30% 预警</el-tag>
          </div>
          <p v-if="!m.card_id" class="member-hint">
            {{ m.role === 'kp' ? 'KP 无需角色卡' : '未绑定角色卡' }}
          </p>
        </div>
        <p class="panel-hint">点击成员卡片查看整张角色卡</p>
      </aside>

      <!-- 中栏：剧情聊天流（复用组件） -->
      <div class="kp-mid">
        <ChatStream />
      </div>

      <!-- 右栏：KP 工具箱 -->
      <aside class="toolbox">
        <!-- 开团（waiting → playing）：开团后大厅不再展示本房间，KP 退出改为保留 -->
        <div class="panel-card">
          <h3 class="panel-title">开团</h3>
          <template v-if="gameStatus === 'playing'">
            <el-tag type="success" class="tb-row" effect="dark">已开团 · 游戏进行中</el-tag>
          </template>
          <template v-else>
            <p class="start-hint">宣布开团后房间进入游戏状态，大厅不再展示，退出时不再解散。</p>
            <el-button
              type="success"
              class="tb-btn"
              size="small"
              :loading="starting"
              @click="onStart"
            >
              宣布开团
            </el-button>
          </template>
        </div>

        <!-- 场景标题栏 -->
        <div class="panel-card">
          <h3 class="panel-title">场景标题栏</h3>
          <el-input
            v-model="sceneForm.scene_title"
            class="tb-row"
            placeholder="地点 / 时间，如：雾都码头 · 深夜"
            maxlength="100"
            size="small"
          />
          <el-input
            v-model="sceneForm.scene_desc"
            class="tb-row"
            type="textarea"
            :rows="2"
            placeholder="场景描述（全员可见，悬停顶栏查看）"
            maxlength="500"
            size="small"
          />
          <el-button
            type="primary"
            class="tb-btn"
            size="small"
            :loading="sceneSubmitting"
            @click="submitScene"
          >
            更新场景
          </el-button>
        </div>

        <!-- 掷骰面板（3.2 手动模式复用；KP 无卡自动走手输，暗骰默认勾选） -->
        <div class="panel-card">
          <h3 class="panel-title">技能检定</h3>
          <SkillCheckPanel :default-secret="true" />
        </div>

        <!-- 检定下放（4.4+）：KP 定技能/难度/后果，被点名玩家本人在剧情流点「投掷」。
             此前只有 auto 模式 AI 能发起，collab/manual 没有 KP 入口（实测反馈修复） -->
        <div class="panel-card">
          <h3 class="panel-title">检定下放</h3>
          <el-select
            v-model="crForm.target"
            class="tb-row"
            placeholder="要求谁投骰（须已绑卡）"
            size="small"
            filterable
          >
            <el-option
              v-for="m in statusTargets"
              :key="m.player_name"
              :label="m.player_name + (cardMap[m.player_name]?.occupation ? ` · ${cardMap[m.player_name]?.occupation}` : '')"
              :value="m.player_name"
            />
          </el-select>
          <el-select
            v-model="crForm.skill"
            class="tb-row"
            placeholder="选择或输入技能名（按其卡查值）"
            size="small"
            filterable
            allow-create
            default-first-option
          >
            <el-option v-for="o in crSkillOptions" :key="o.name" :label="o.label" :value="o.name" />
          </el-select>
          <el-select v-model="crForm.difficulty" class="tb-row" size="small">
            <el-option label="常规" value="standard" />
            <el-option label="困难" value="hard" />
            <el-option label="极难" value="extreme" />
          </el-select>
          <el-input
            v-model="crForm.reason"
            class="tb-row"
            placeholder="检定缘由（必填，如：撬开书房的门锁）"
            maxlength="200"
            size="small"
          />
          <el-button
            type="warning"
            class="tb-btn"
            size="small"
            :loading="crSubmitting"
            @click="submitCheckRequest"
          >
            要求投掷
          </el-button>
        </div>

        <!-- AI 建议（4.1 协同建议模式：玩家行动 → LLM 候选建议，仅 KP 可见） -->
        <div class="panel-card">
          <h3 class="panel-title">AI 建议</h3>
          <AiSuggestionPanel />
        </div>

        <!-- KP 风格（4.4 §6.2：三内置 + 自定义，实时切换全员可见） -->
        <div class="panel-card">
          <h3 class="panel-title">KP 风格</h3>
          <KpStylePanel />
        </div>

        <!-- LLM 设置（4.1+：最小 KP 设置面板，写 .env 全局生效；DB 入库留 4.4） -->
        <div class="panel-card">
          <h3 class="panel-title">LLM 设置</h3>
          <p class="llm-hint">供应商 / Key / 模型，全局生效。</p>
          <el-button size="small" class="tb-btn" @click="llmSettingsVisible = true">
            打开设置
          </el-button>
        </div>

        <!-- 扣 HP / 扣 SAN -->
        <div class="panel-card">
          <h3 class="panel-title">调整 HP / SAN</h3>
          <el-select
            v-model="statusForm.target"
            class="tb-row"
            placeholder="选择成员（须已绑卡）"
            size="small"
          >
            <el-option
              v-for="m in statusTargets"
              :key="m.player_name"
              :label="m.player_name + (cardMap[m.player_name]?.occupation ? ` · ${cardMap[m.player_name]?.occupation}` : '')"
              :value="m.player_name"
            />
          </el-select>
          <div class="tb-row delta-row">
            <span class="delta-label">HP</span>
            <el-input-number
              v-model="statusForm.hpDelta"
              :key="`hp-${statusFormTick}`"
              :min="-99"
              :max="99"
              controls-position="right"
              size="small"
              class="delta-input"
            />
          </div>
          <div class="tb-row delta-row">
            <span class="delta-label">SAN</span>
            <el-input-number
              v-model="statusForm.sanDelta"
              :key="`san-${statusFormTick}`"
              :min="-99"
              :max="99"
              controls-position="right"
              size="small"
              class="delta-input"
            />
          </div>
          <el-input
            v-model="statusForm.reason"
            class="tb-row"
            placeholder="变更原因（必填，如：受到步枪射击）"
            maxlength="200"
            size="small"
          />
          <el-button
            type="danger"
            class="tb-btn"
            size="small"
            :loading="statusSubmitting"
            @click="submitStatus"
          >
            应用变更
          </el-button>
        </div>

        <!-- 存档 / 读档（3.4）：读档会覆盖当前状态，confirm 里已警告 -->
        <div class="panel-card">
          <h3 class="panel-title">存档</h3>
          <div class="tb-row save-row">
            <el-button size="small" class="tb-btn" :loading="saving" @click="onSave">
              存档
            </el-button>
            <el-button size="small" class="tb-btn" @click="onOpenLoadDialog">读档</el-button>
          </div>
        </div>
      </aside>
    </div>

    <!-- 读档弹窗：选一条 → confirm 覆盖警告 → load（界面由 room_state 广播刷新） -->
    <el-dialog v-model="loadDialogVisible" title="读取存档" width="380px">
      <div v-loading="savesLoading" class="saves-list">
        <p v-if="!savesLoading && saves.length === 0" class="saves-empty">
          这个房间还没有存档
        </p>
        <div
          v-for="s in saves"
          :key="s.id"
          class="save-item"
          :class="{ 'save-item--active': selectedSaveId === s.id }"
          @click="selectedSaveId = s.id"
        >
          <span class="save-name">{{ s.name }}</span>
          <span class="save-time">{{ fmtSaveTime(s.created_at) }}</span>
        </div>
      </div>
      <template #footer>
        <el-button size="small" @click="loadDialogVisible = false">取消</el-button>
        <el-button
          type="danger"
          size="small"
          :disabled="!selectedSaveId"
          :loading="loadingSave"
          @click="confirmLoad"
        >
          读档
        </el-button>
      </template>
    </el-dialog>

    <!-- LLM 设置对话框（4.1+）：base_url / key（掩码）/ 模型探测 + 手填兜底 -->
    <LlmSettingsDialog v-model:visible="llmSettingsVisible" />

    <!-- 整卡抽屉 -->
    <el-drawer
      v-model="drawerVisible"
      :title="drawerMember ? `${drawerMember.player_name} 的角色卡` : '角色卡'"
      size="420px"
    >
      <div v-loading="drawerLoading" class="drawer-body">
        <template v-if="drawerCard">
          <h2 class="drawer-name">{{ drawerCard.name }}</h2>
          <p class="drawer-meta">
            {{ drawerCard.gender }} · {{ drawerCard.age }} 岁 · {{ drawerCard.occupation }}
            · {{ eraLabel(drawerCard.era) }}
          </p>
          <div v-for="b in [
            { label: 'HP', cur: drawerCard.state.current_hp, max: drawerCard.derived.HP, color: '#F56C6C' },
            { label: 'MP', cur: drawerCard.state.current_mp, max: drawerCard.derived.MP, color: '#409EFF' },
            { label: 'SAN', cur: drawerCard.state.current_sanity, max: drawerCard.derived.SAN, color: '#9B59B6' },
            { label: '幸运', cur: drawerCard.state.current_luck, max: 99, color: '#67C23A' },
          ]" :key="b.label" class="stat-row">
            <span class="stat-label">{{ b.label }}</span>
            <el-progress
              class="stat-bar"
              :percentage="b.max > 0 ? Math.round((b.cur / b.max) * 100) : 0"
              :stroke-width="8"
              :color="b.color"
            />
            <span class="stat-num">{{ b.cur }}/{{ b.max }}</span>
          </div>

          <h4 class="drawer-sec">属性</h4>
          <div class="attr-grid">
            <div v-for="(v, k) in drawerCard.attributes" :key="k" class="attr-item">
              <span class="attr-label">{{ ATTR_LABELS[k] ?? k }}</span>
              <span class="attr-val">{{ v }}</span>
            </div>
          </div>

          <template v-if="drawerCard.weapons.length">
            <h4 class="drawer-sec">武器</h4>
            <div v-for="(w, i) in drawerCard.weapons" :key="i" class="weapon-row">
              <b>{{ w.name }}</b>
              <span>伤害 {{ w.damage }} · 射程 {{ w.rng || '—' }} · 每轮 {{ w.attacks || '—' }}</span>
            </div>
          </template>

          <h4 class="drawer-sec">技能（{{ drawerCard.skills.length }}）</h4>
          <div class="skill-list">
            <span v-for="(s, i) in drawerCard.skills" :key="i" class="skill-chip">
              {{ s.name }}{{ s.detail ? `（${s.detail}）` : '' }} {{ s.base + s.increment }}
            </span>
          </div>

          <h4 class="drawer-sec">背景</h4>
          <div
            v-for="(text, key) in drawerCard.background"
            :key="key"
            class="bg-row"
          >
            <template v-if="text">
              <b class="bg-label">{{ BG_LABELS[key] ?? key }}：</b>{{ text }}
            </template>
          </div>
        </template>
      </div>
    </el-drawer>
  </main>
</template>

<style scoped>
.kp-page {
  display: flex;
  flex-direction: column;
  /* 减去 App 导航栏高度（含边框），避免整页溢出滚动 */
  height: calc(100vh - 55px);
  background: #1b2431;
  color: #e8eaed;
}

.room-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  background: #151c26;
  border-bottom: 1px solid #2c3e50;
}

.room-title {
  display: flex;
  align-items: center;
  gap: 10px;
}

.room-tag {
  font-size: 13px;
  color: #909399;
}

.room-code {
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 4px;
  color: #e6a23c;
}

.scene-chip {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding: 2px 10px;
  border-radius: 10px;
  background: rgba(230, 162, 60, 0.15);
  border: 1px solid rgba(230, 162, 60, 0.4);
  color: #e6a23c;
  font-size: 13px;
  cursor: default;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.me {
  font-size: 14px;
}

.quit-btn {
  color: #909399;
}

.quit-btn:hover {
  color: #f56c6c;
}

.kp-body {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 16px;
  padding: 16px;
}

.panel-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #e6a23c;
}

/* ---------- 左栏玩家面板 ---------- */
.player-panel {
  display: flex;
  width: 300px;
  flex-shrink: 0;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
}

.member-card {
  padding: 12px 14px;
  background: #222d3d;
  border: 1px solid #2c3e50;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.member-card:hover {
  border-color: #e6a23c;
}

/* ≤30% 红色预警：卡片边框转红 + 预警标签 */
.member-card--warn,
.member-card--warn:hover {
  border-color: #f56c6c;
}

.member-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: #2c3e50;
  color: #e8eaed;
  font-size: 14px;
  flex-shrink: 0;
}

.member-info {
  flex: 1;
  min-width: 0;
}

.member-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.member-name {
  font-size: 14px;
  font-weight: 600;
}

.member-occ {
  margin: 2px 0 0;
  font-size: 12px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.stat-label {
  width: 30px;
  font-size: 12px;
  color: #909399;
}

.stat-bar {
  flex: 1;
}

.stat-num {
  width: 48px;
  text-align: right;
  font-size: 12px;
  color: #e8eaed;
}

.warn-row {
  margin-top: 4px;
}

.member-hint {
  margin: 4px 0 0;
  font-size: 12px;
  color: #909399;
}

.panel-hint {
  margin: 0;
  font-size: 12px;
  color: #6b7686;
  text-align: center;
}

/* ---------- 中栏：ChatStream 自带 flex:1，容器只负责占位 ---------- */
.kp-mid {
  display: flex;
  flex: 1;
  min-width: 0;
}

/* ---------- 右栏工具箱 ---------- */
.toolbox {
  display: flex;
  width: 330px;
  flex-shrink: 0;
  flex-direction: column;
  gap: 16px;
  overflow-y: auto;
}

.panel-card {
  background: #222d3d;
  border: 1px solid #2c3e50;
  border-radius: 10px;
  padding: 14px 16px;
}

.tb-row {
  width: 100%;
  margin-bottom: 10px;
}

.delta-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.delta-label {
  width: 34px;
  font-size: 12px;
  color: #909399;
}

.delta-input {
  flex: 1;
}

.tb-btn {
  width: 100%;
}

.start-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: #909399;
  line-height: 1.6;
}

.llm-hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: #7f8fa6;
  line-height: 1.6;
}

.save-row {
  display: flex;
  gap: 10px;
}

/* ---------- 读档弹窗列表 ---------- */
.saves-list {
  min-height: 80px;
  max-height: 320px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.saves-empty {
  margin: 24px 0;
  text-align: center;
  font-size: 13px;
  color: #909399;
}

.save-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}

.save-item:hover {
  border-color: #e6a23c;
}

.save-item--active {
  border-color: #e6a23c;
  background: #fdf6ec;
}

.save-name {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.save-time {
  font-size: 12px;
  color: #909399;
  flex-shrink: 0;
}

/* ---------- 整卡抽屉（浅色文档风） ---------- */
.drawer-body {
  min-height: 200px;
  color: #303133;
}

.drawer-name {
  margin: 0;
  font-size: 22px;
}

.drawer-meta {
  margin: 4px 0 16px;
  font-size: 13px;
  color: #909399;
}

.drawer-sec {
  margin: 18px 0 8px;
  font-size: 14px;
  color: #e6a23c;
  border-bottom: 1px solid #ebeef5;
  padding-bottom: 4px;
}

.attr-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
}

.attr-item {
  display: flex;
  justify-content: space-between;
  padding: 6px 10px;
  background: #f5f7fa;
  border-radius: 6px;
  font-size: 13px;
}

.attr-label {
  color: #909399;
}

.attr-val {
  font-weight: 600;
}

.weapon-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 0;
  font-size: 13px;
}

.weapon-row span {
  color: #606266;
}

.skill-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.skill-chip {
  padding: 2px 8px;
  background: #f0f2f5;
  border-radius: 10px;
  font-size: 12px;
  color: #303133;
}

.bg-row {
  font-size: 13px;
  line-height: 1.7;
  color: #606266;
  margin-bottom: 4px;
  word-break: break-word;
}

.bg-label {
  color: #303133;
}
</style>
