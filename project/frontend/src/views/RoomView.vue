<script setup lang="ts">
/**
 * 房间页（玩家双栏）— 阶段 3.1，3.3 复用组件化；6.2⑦ 按样例图重排。
 *
 * 布局：左「剧情流为主」（模组/场景横幅 + ChatStream），右「工具侧栏」卡片化
 * （调查团 / 我的角色卡 / 技能检定）。
 *
 * 逻辑与协议零改动：
 *   - HP/SAN 条优先读 store 的 cardStates 快照（status_changed 广播驱动，不自改本地卡），
 *     无快照回退 REST 拉到的卡面值；
 *   - 身份来源：路由 query（建房/加入页跳转携带）→ localStorage（刷新恢复）→ 回首页；
 *   - 离开房间仍在 onUnmounted 收尾（房间系路由互跳不拆连接）。
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
import CocIcon from '@/components/common/CocIcon.vue'
import StatBar from '@/components/common/StatBar.vue'
import StateView from '@/components/common/StateView.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import type { Investigator } from '@/types/investigator'

const route = useRoute()
const router = useRouter()
const room = useRoomStore()
const { quitRoom } = useQuitRoom()

const myCard = ref<Investigator | null>(null)
/** 卡面拉取中（骨架屏用）：无卡（未绑定）时立即结束，不进 loading 态 */
const cardLoading = ref(false)

// ---------- 移动端工具抽屉（6.2⑩） ----------
/**
 * 手机端（≤820px）：调查团 / 我的角色卡 / 技能检定收进右滑抽屉，
 * 剧情流占满全屏——替代原先"单列堆叠（聊天 62vh + 侧栏折下方）"的 PC 缩放观感。
 */
const toolsOpen = ref(false)

/** 本视图是否真的建立过连接（守卫重定向路径未建连，卸载时不得拆连接） */
let didConnect = false

/** 我的卡状态展示值：status_changed 快照优先（广播驱动），否则回退卡面值 */
const myStatBars = computed(() => {
  if (!myCard.value) return []
  const snap = room.cardStates[room.playerName]
  return [
    { label: 'HP', cur: snap?.hp ?? myCard.value.state.current_hp, max: snap?.hp_max ?? myCard.value.derived.HP, tone: 'hp' as const },
    { label: 'MP', cur: myCard.value.state.current_mp, max: myCard.value.derived.MP, tone: 'mp' as const },
    { label: 'SAN', cur: snap?.sanity ?? myCard.value.state.current_sanity, max: snap?.sanity_max ?? myCard.value.derived.SAN, tone: 'san' as const },
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
    cardLoading.value = true
    try {
      myCard.value = await getCard(room.cardId)
    } catch {
      ElMessage.error('角色卡加载失败')
    } finally {
      cardLoading.value = false
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
    <div class="room-body">
      <!-- 左：剧情流为主（模组/场景横幅 + 聊天流） -->
      <section class="stream-col">
        <header class="banner coc-panel">
          <span class="banner-mark">
            <CocIcon name="book" :size="18" />
          </span>
          <div class="banner-text">
            <p class="banner-title">{{ room.roomModule?.module_name || '默认剧情骨架' }}</p>
            <p class="banner-sub">
              <template v-if="room.scene?.scene_title">
                <span class="banner-scene">📍 {{ room.scene.scene_title }}</span>
                <span v-if="room.scene.scene_desc" class="banner-desc">{{ room.scene.scene_desc }}</span>
              </template>
              <template v-else>场景尚未揭幕，等待守秘人开场</template>
            </p>
          </div>
          <div class="banner-right">
            <span class="coc-chip coc-mono">{{ room.roomId }}</span>
            <span class="coc-chip" :class="room.connected ? 'coc-chip--accent' : 'coc-chip--danger'">
              <i class="coc-dot" :class="{ 'coc-dot--online': room.connected }" />
              {{ room.connected ? '已连接' : '重连中…' }}
            </span>
            <!-- 移动端专用：打开工具抽屉（桌面端隐藏，侧栏常驻） -->
            <button type="button" class="tools-btn" @click="toolsOpen = true">
              <CocIcon name="users" :size="13" />
              工具
            </button>
            <button type="button" class="quit-btn" @click="quitRoom">
              <CocIcon name="close" :size="13" />
              退出房间
            </button>
          </div>
        </header>

        <ChatStream />
      </section>

      <!-- 移动端抽屉遮罩（桌面端与关闭态皆不渲染） -->
      <div v-if="toolsOpen" class="tools-mask" @click="toolsOpen = false" />

      <!-- 右：工具侧栏（卡片化）；移动端变为右滑抽屉（.side-panel--open） -->
      <aside class="side-panel coc-scroll" :class="{ 'side-panel--open': toolsOpen }">
        <section class="coc-panel">
          <header class="coc-panel-head">
            <h3 class="coc-panel-title">
              <CocIcon name="users" :size="15" />
              调查团
            </h3>
            <span class="coc-chip">{{ room.members.length }} 人</span>
          </header>
          <div class="coc-panel-body member-list">
            <div v-for="m in room.members" :key="m.player_name" class="member-row">
              <span class="member-avatar" :class="m.role === 'kp' && 'member-avatar--kp'">
                {{ m.player_name.slice(0, 1) }}
              </span>
              <span class="member-name">{{ m.player_name }}</span>
              <span class="role-tag" :class="m.role === 'kp' && 'role-tag--kp'">
                {{ m.role === 'kp' ? 'KP' : '玩家' }}
              </span>
            </div>
          </div>
        </section>

        <section class="coc-panel">
          <header class="coc-panel-head">
            <h3 class="coc-panel-title">
              <CocIcon name="card" :size="15" />
              我的角色卡
            </h3>
            <span v-if="myCard" class="coc-chip coc-chip--brand">{{ myCard.occupation }}</span>
          </header>
          <div class="coc-panel-body">
            <SkeletonBlock v-if="cardLoading" variant="text" :count="1" :rows="3" />
            <template v-else-if="myCard">
              <p class="card-name">{{ myCard.name }}</p>
              <p class="card-meta">{{ myCard.occupation }} · {{ myCard.age }} 岁 · {{ myCard.gender }}</p>
              <div class="stats">
                <StatBar
                  v-for="s in myStatBars"
                  :key="s.label"
                  :label="s.label"
                  :value="s.cur"
                  :max="s.max"
                  :tone="s.tone"
                />
              </div>
            </template>
            <StateView
              v-else
              compact
              state="empty"
              title="未绑定角色卡"
              description="从大厅加入房间时可以选择一张调查员卡"
            />
          </div>
        </section>

        <!-- 技能检定（3.2）：方案甲——AI 主持（auto/collab）下隐藏，检定由 AI 裁量
             发起（request_check 下放投掷），防玩家自掷刷优势；真人主持模式保留 -->
        <section class="coc-panel">
          <header class="coc-panel-head">
            <h3 class="coc-panel-title">
              <CocIcon name="dice" :size="15" />
              技能检定
            </h3>
            <span v-if="room.agentMode !== 'manual'" class="coc-chip">
              {{ room.agentMode === 'auto' ? 'AI 裁量' : 'KP 裁定' }}
            </span>
          </header>
          <div class="coc-panel-body">
            <SkillCheckPanel v-if="room.agentMode === 'manual'" />
            <p v-else class="coc-hint">
              {{
                room.agentMode === 'auto'
                  ? 'AI 主持模式下，检定由 AI 主持裁量发起——需要你投掷时会在剧情流出现投掷按钮。'
                  : '协同模式下，检定由守秘人裁定后下放——需要你投掷时会在剧情流出现投掷按钮。'
              }}
            </p>
          </div>
        </section>
      </aside>
    </div>
  </main>
</template>

<style scoped>
.room-page {
  display: flex;
  flex-direction: column;
  /* 阶段 6.2②：高度由外壳主内容区给出，视图不再自己减顶栏高度 */
  height: 100%;
  color: var(--coc-text);
}

.room-body {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: var(--coc-sp-4);
  padding: var(--coc-sp-4);
}

.stream-col {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--coc-sp-4);
}

/* ---------- 模组 / 场景横幅 ---------- */
.banner {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  flex-shrink: 0;
  padding: var(--coc-sp-3) var(--coc-sp-4);
  background:
    radial-gradient(120% 160% at 0% 0%, rgba(34, 211, 238, 0.12), transparent 58%),
    var(--coc-card);
}

.banner-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border: 1px solid var(--coc-border-glow);
  border-radius: var(--coc-radius);
  background: rgba(11, 18, 32, 0.6);
  color: var(--coc-accent);
}

.banner-text {
  min-width: 0;
}

.banner-title {
  font-size: var(--coc-fs-md);
  font-weight: 600;
  color: var(--coc-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.banner-sub {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin-top: 2px;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
  overflow: hidden;
}

.banner-scene {
  flex-shrink: 0;
  color: var(--coc-brand);
}

.banner-desc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.banner-right {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin-left: auto;
  flex-shrink: 0;
}

.quit-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-sm);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-xs);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease), border-color var(--coc-dur-fast) var(--coc-ease),
    background var(--coc-dur-fast) var(--coc-ease);
}

.quit-btn:hover {
  border-color: rgba(239, 68, 68, 0.55);
  background: var(--coc-danger-soft);
  color: #fca5a5;
}

/* ---------- 移动端工具抽屉（6.2⑩）：宽屏一律隐藏 ---------- */
.tools-btn {
  display: none;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-sm);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-xs);
  cursor: pointer;
}

.tools-btn:hover {
  border-color: var(--coc-border-glow);
  color: var(--coc-accent);
}

.tools-mask {
  display: none;
}

/* ---------- 右栏 ---------- */
.side-panel {
  display: flex;
  width: var(--coc-rightpanel-w);
  flex-shrink: 0;
  flex-direction: column;
  gap: var(--coc-sp-4);
  overflow-y: auto;
}

.member-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.member-row {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  padding: 6px;
  border-radius: var(--coc-radius-sm);
  transition: background var(--coc-dur-fast) var(--coc-ease);
}

.member-row:hover {
  background: var(--coc-card-2);
}

.member-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-full);
  background: var(--coc-card-3);
  color: var(--coc-text);
  font-size: var(--coc-fs-sm);
  font-weight: 600;
}

.member-avatar--kp {
  border-color: rgba(230, 162, 60, 0.5);
  background: var(--coc-brand-soft);
  color: var(--coc-brand);
}

.member-name {
  flex: 1;
  min-width: 0;
  font-size: var(--coc-fs-base);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-tag {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-sm);
  color: var(--coc-text-muted);
  font-size: var(--coc-fs-xs);
  line-height: 1.7;
}

.role-tag--kp {
  border-color: rgba(230, 162, 60, 0.5);
  background: var(--coc-brand-soft);
  color: var(--coc-brand);
}

.card-name {
  font-size: var(--coc-fs-lg);
  font-weight: 600;
  color: var(--coc-text-strong);
}

.card-meta {
  margin: 2px 0 var(--coc-sp-3);
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.stats {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-2);
}

/* 窄屏（阶段 6.2⑩ 之前先保证不撑破）：侧栏收窄、横幅右侧折行 */
@media (max-width: 1180px) {
  .side-panel {
    width: 264px;
  }

  .banner-desc,
  .banner-right .coc-chip:first-child {
    display: none;
  }
}

/* 阶段 6.2⑩：窄屏（手机/平板竖屏）——剧情流占满全屏，工具侧栏改为右滑抽屉。
   不再走"单列堆叠（聊天 62vh + 侧栏折下方）"：那正是"PC 缩放版"的观感来源。 */
@media (max-width: 820px) {
  .room-body {
    flex-direction: column;
    overflow: hidden;
    gap: var(--coc-sp-2);
    padding: var(--coc-sp-2);
  }

  /* 剧情流（横幅 + 聊天）占满剩余高度，聊天内部滚动 */
  .stream-col {
    flex: 1;
    min-height: 0;
    gap: var(--coc-sp-2);
  }

  .banner {
    flex-wrap: wrap;
    gap: var(--coc-sp-2);
    padding: var(--coc-sp-2) var(--coc-sp-3);
  }

  .banner-right {
    margin-left: 0;
    width: 100%;
    justify-content: flex-end;
  }

  .tools-btn {
    display: inline-flex;
    min-height: var(--coc-touch-min);
    padding: 0 var(--coc-sp-3);
  }

  /* 触控目标不低于 --coc-touch-min */
  .quit-btn {
    min-height: var(--coc-touch-min);
    padding: 0 var(--coc-sp-3);
  }

  /* 抽屉遮罩：压住内容层，点击关闭 */
  .tools-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: calc(var(--coc-z-drawer) - 1);
    background: var(--coc-scrim);
    backdrop-filter: blur(2px);
  }

  /* 工具侧栏 → 右滑抽屉（fixed 实底，默认移出屏外） */
  .side-panel {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: var(--coc-z-drawer);
    width: min(320px, 86vw);
    padding: var(--coc-sp-4);
    padding-bottom: calc(var(--coc-sp-4) + env(safe-area-inset-bottom, 0px));
    background: var(--coc-bg-deep);
    border-left: 1px solid var(--coc-border);
    box-shadow: var(--coc-shadow-lg);
    overflow-y: auto;
    transform: translateX(100%);
    transition: transform var(--coc-dur) var(--coc-ease);
  }

  .side-panel--open {
    transform: translateX(0);
  }
}
</style>
