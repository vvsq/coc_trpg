<script setup lang="ts">
/**
 * 房间页（玩家双栏）— 阶段 3.1，3.3 复用组件化。
 *
 * 左栏：剧情聊天流（components/ChatStream.vue，与 KP 控制台共用）
 * 右栏：成员列表 + 我的角色卡简版 + 技能检定（components/SkillCheckPanel.vue）
 *
 * HP/SAN 条优先读 store 的 cardStates 快照（status_changed 广播驱动，
 * 不自改本地卡），无快照回退 REST 拉到的卡面值。
 * 身份来源：路由 query（建房/加入页跳转携带）→ localStorage（刷新恢复）→ 回首页。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getRoom } from '@/api/rooms'
import { getCard } from '@/api/cards'
import { useRoomStore } from '@/stores/room'
import { useQuitRoom } from '@/composables/useQuitRoom'
import ChatStream from '@/components/ChatStream.vue'
import SkillCheckPanel from '@/components/SkillCheckPanel.vue'
import type { Investigator } from '@/types/investigator'

const route = useRoute()
const router = useRouter()
const room = useRoomStore()
const { quitRoom } = useQuitRoom()

const myCard = ref<Investigator | null>(null)

/** 本视图是否真的建立过连接（守卫重定向路径未建连，卸载时不得拆连接） */
let didConnect = false

/** 我的卡状态展示值：status_changed 快照优先（广播驱动），否则回退卡面值 */
const myStatBars = computed(() => {
  if (!myCard.value) return []
  const snap = room.cardStates[room.playerName]
  return [
    { label: 'HP', cur: snap?.hp ?? myCard.value.state.current_hp, max: snap?.hp_max ?? myCard.value.derived.HP },
    { label: 'MP', cur: myCard.value.state.current_mp, max: myCard.value.derived.MP },
    { label: 'SAN', cur: snap?.sanity ?? myCard.value.state.current_sanity, max: snap?.sanity_max ?? myCard.value.derived.SAN },
  ]
})

onMounted(async () => {
  const id = String(route.params.id)
  const name = String(route.query.name ?? '')
  const cid = route.query.card_id ? String(route.query.card_id) : null

  if (name) {
    room.enterRoom(id, name, cid)
    didConnect = true
  } else if (!room.restoreIdentity(id)) {
    ElMessage.error('缺少玩家身份，请从大厅重新进入房间')
    router.replace('/')
    return
  } else {
    didConnect = true
  }

  // 场景标题栏初值：玩家进房即拿到当前场景（此后由 scene_changed 广播驱动）
  try {
    const detail = await getRoom(id)
    room.scene = detail.scene
  } catch {
    // 场景加载失败不阻塞进房
  }

  if (room.cardId) {
    try {
      myCard.value = await getCard(room.cardId)
    } catch {
      ElMessage.error('角色卡加载失败')
    }
  }
})

onUnmounted(() => {
  // 导航仍落在房间系路由（房间页⇄KP控制台互跳）时不拆连接，由目标视图接管
  const toName = router.currentRoute.value.name
  if (!didConnect || toName === 'room' || toName === 'kp-console') return
  room.leaveRoom()
})
</script>

<template>
  <main class="room-page">
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
        <el-tag :type="room.myRole === 'kp' ? 'warning' : 'info'" size="small" effect="plain">
          {{ room.myRole === 'kp' ? 'KP' : '玩家' }}
        </el-tag>
        <el-button text size="small" class="quit-btn" @click="quitRoom">退出房间</el-button>
      </div>
    </header>

    <div class="room-body">
      <!-- 左栏：剧情聊天流（复用组件） -->
      <ChatStream />

      <!-- 右栏：成员 + 我的角色卡 -->
      <aside class="side-panel">
        <div class="panel-card">
          <h3 class="panel-title">调查团（{{ room.members.length }}）</h3>
          <div v-for="m in room.members" :key="m.player_name" class="member-row">
            <span class="avatar">{{ m.player_name.slice(0, 1) }}</span>
            <span class="member-name">{{ m.player_name }}</span>
            <el-tag :type="m.role === 'kp' ? 'warning' : 'info'" size="small" effect="plain">
              {{ m.role === 'kp' ? 'KP' : '玩家' }}
            </el-tag>
          </div>
        </div>

        <div class="panel-card">
          <h3 class="panel-title">我的角色卡</h3>
          <template v-if="myCard">
            <p class="card-name">{{ myCard.name }}</p>
            <p class="card-meta">{{ myCard.occupation }} · {{ myCard.age }} 岁</p>
            <div class="stat-row" v-for="s in myStatBars" :key="s.label">
              <span class="stat-label">{{ s.label }}</span>
              <el-progress
                class="stat-bar"
                :percentage="s.max > 0 ? Math.round((s.cur / s.max) * 100) : 0"
                :stroke-width="10"
                :color="s.label === 'SAN' ? '#9B59B6' : s.label === 'HP' ? '#F56C6C' : '#409EFF'"
              />
              <span class="stat-num">{{ s.cur }}/{{ s.max }}</span>
            </div>
          </template>
          <p v-else class="no-card">尚未绑定角色卡（可从大厅加入时选择）</p>
        </div>

        <!-- 技能检定面板（3.2）：方案甲——AI 主持（auto/collab）下隐藏，检定由 AI 裁量
             发起（request_check 下放投掷），防玩家自掷刷优势；真人主持模式保留 -->
        <div v-if="room.agentMode === 'manual'" class="panel-card">
          <h3 class="panel-title">技能检定</h3>
          <SkillCheckPanel />
        </div>
        <div v-else class="panel-card">
          <h3 class="panel-title">技能检定</h3>
          <p class="dice-hint">
            {{ room.agentMode === 'auto' ? 'AI 主持模式下，检定由 AI 主持裁量发起——需要你投掷时会出现投掷按钮' : '协同模式下检定由 KP 裁定' }}
          </p>
        </div>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.room-page {
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

/* 场景标题栏 chip（3.3）：全员可见，悬停看场景描述 */
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

.room-body {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 16px;
  padding: 16px;
}

/* ---------- 右栏 ---------- */
.side-panel {
  display: flex;
  width: 280px;
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

.panel-title {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #e6a23c;
}

.member-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 0;
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #2c3e50;
  color: #e8eaed;
  font-size: 14px;
  flex-shrink: 0;
}

.member-name {
  flex: 1;
  font-size: 14px;
}

.card-name {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.card-meta {
  margin: 4px 0 12px;
  font-size: 12px;
  color: #909399;
}

.stat-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.stat-label {
  width: 34px;
  font-size: 12px;
  color: #909399;
}

.stat-bar {
  flex: 1;
}

.stat-num {
  width: 56px;
  text-align: right;
  font-size: 12px;
  color: #e8eaed;
}

.no-card {
  font-size: 13px;
  color: #909399;
}

.dice-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}
</style>
