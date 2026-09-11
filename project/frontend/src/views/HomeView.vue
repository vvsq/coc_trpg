<script setup lang="ts">
/**
 * 大厅首页 — 阶段 3.1；6.2⑧ 按样例图重排信息层级。
 *
 * 首屏只留两个主操作（创建房间 / 加入房间），次级入口（角色管理 / 模组库 /
 * API 与模型配置）收成一行快捷链接；等待中的房间列表补齐三态
 * （骨架屏 / 空态 / 错误态 + 重试），不再"加载失败就一片空白"。
 *
 * 业务逻辑零改动：建房 / 加入 / 列表 / 首次配置引导与弹窗行为与重排前一致。
 */
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createRoom, joinRoom, listRooms } from '@/api/rooms'
import { listCards, type CardListItem } from '@/api/cards'
import LlmSettingsDialog from '@/components/LlmSettingsDialog.vue'
import LlmFirstRunGuide from '@/components/LlmFirstRunGuide.vue'
import CocIcon from '@/components/common/CocIcon.vue'
import StateView from '@/components/common/StateView.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
import type { RoomListItem, WsMember } from '@/types/ws'

const router = useRouter()
/** 全局 API / 模型配置弹窗（详细设置页；房间与模组页只做只读回显） */
const settingsVisible = ref(false)
/** 首次配置引导条（6.1）：设置弹窗关掉后重新检测配置状态 */
const guideRef = ref<{ refresh: () => void } | null>(null)
watch(settingsVisible, (open) => {
  if (!open) guideRef.value?.refresh()
})

// ---------- 建房 ----------
const createVisible = ref(false)
const createForm = ref({ name: '', kp_name: '' })

async function doCreate() {
  if (!createForm.value.name.trim() || !createForm.value.kp_name.trim()) {
    ElMessage.warning('房间名和 KP 昵称都要填')
    return
  }
  const res = await createRoom(createForm.value.name.trim(), createForm.value.kp_name.trim())
  ElMessage.success(`房间创建成功，房间号 ${res.room_id}，快分享给伙伴吧`)
  createVisible.value = false
  // KP 进房直跳三栏控制台（3.3）
  router.push({
    name: 'kp-console',
    params: { id: res.room_id },
    query: { name: createForm.value.kp_name.trim() },
  })
}

// ---------- 加入 ----------
const joinVisible = ref(false)
const cards = ref<CardListItem[]>([])
const joinForm = ref({ room_id: '', player_name: '', card_id: null as string | null })

async function openJoin(roomId = '') {
  joinForm.value.room_id = roomId.toUpperCase()
  joinVisible.value = true
  if (cards.value.length === 0) {
    try {
      cards.value = await listCards()
    } catch {
      ElMessage.error('角色卡列表加载失败')
    }
  }
}

async function doJoin() {
  const f = joinForm.value
  const roomId = f.room_id.trim().toUpperCase()
  const name = f.player_name.trim()
  if (!roomId || !name) {
    ElMessage.warning('房间号和你的名字都要填')
    return
  }
  let members: WsMember[]
  try {
    members = await joinRoom(roomId, name, f.card_id)
  } catch {
    return // 错误提示已由 axios 拦截器统一弹出
  }
  joinVisible.value = false
  // KP（等待中/开团中）进房都直跳三栏控制台（3.3）
  const isKp = members.some((m) => m.player_name === name && m.role === 'kp')
  router.push({
    name: isKp ? 'kp-console' : 'room',
    params: { id: roomId },
    query: { name, ...(f.card_id ? { card_id: f.card_id } : {}) },
  })
}

// ---------- 等待中的房间（三态：骨架 / 空 / 错误+重试） ----------
const rooms = ref<RoomListItem[]>([])
const roomsLoading = ref(true)
const roomsError = ref('')

async function refreshRooms() {
  roomsLoading.value = true
  roomsError.value = ''
  try {
    rooms.value = await listRooms()
  } catch {
    // 列表加载失败不弹窗（拦截器已提示一次），页面上给可重试的错误态
    roomsError.value = '房间列表加载失败，请确认后端服务仍在运行'
  } finally {
    roomsLoading.value = false
  }
}

onMounted(refreshRooms)
</script>

<template>
  <main class="home coc-page">
    <section class="hero">
      <h1 class="hero-title">COC 跑团助手</h1>
      <p class="hero-sub">创建房间开启调查，或输入房间号加入一场正在进行的故事</p>

      <!-- 首次配置引导（6.1）：未配 LLM 时提示可一键进演示模式，不挡开团 -->
      <LlmFirstRunGuide ref="guideRef" @configure="settingsVisible = true" />

      <div class="entries">
        <button type="button" class="entry entry--kp coc-glow-hover" @click="createVisible = true">
          <span class="entry-icon">
            <CocIcon name="shield" :size="24" />
          </span>
          <span class="entry-body">
            <span class="entry-title">创建房间</span>
            <span class="entry-desc">作为守秘人（KP）开团，拿到房间短码分发给玩家</span>
          </span>
          <CocIcon name="chevronRight" :size="16" />
        </button>

        <button type="button" class="entry entry--player coc-glow-hover" @click="openJoin()">
          <span class="entry-icon">
            <CocIcon name="dice" :size="24" />
          </span>
          <span class="entry-body">
            <span class="entry-title">加入房间</span>
            <span class="entry-desc">输入 8 位房间短码，带上你的调查员卡入场</span>
          </span>
          <CocIcon name="chevronRight" :size="16" />
        </button>
      </div>

      <!-- 次级入口：不抢首屏注意力，但一眼能找到 -->
      <nav class="quick-links">
        <RouterLink class="quick-link" :to="{ name: 'card-list' }">
          <CocIcon name="card" :size="13" />
          角色管理
        </RouterLink>
        <RouterLink class="quick-link" :to="{ name: 'module-list' }">
          <CocIcon name="book" :size="13" />
          模组库
        </RouterLink>
        <RouterLink class="quick-link" :to="{ name: 'settings' }">
          <CocIcon name="gear" :size="13" />
          系统设置
        </RouterLink>
        <button type="button" class="quick-link" @click="settingsVisible = true">
          <CocIcon name="sparkles" :size="13" />
          API / 模型配置
        </button>
      </nav>
    </section>

    <section class="lobby coc-panel">
      <header class="coc-panel-head">
        <h3 class="coc-panel-title">
          <CocIcon name="clock" :size="15" />
          等待中的房间
        </h3>
        <button type="button" class="refresh-btn" :disabled="roomsLoading" @click="refreshRooms">
          <CocIcon name="refresh" :size="13" :class="{ 'coc-spin': roomsLoading }" />
          刷新
        </button>
      </header>

      <div class="coc-panel-body">
        <SkeletonBlock v-if="roomsLoading" variant="row" :count="2" :rows="1" />

        <StateView
          v-else-if="roomsError"
          compact
          state="error"
          title="加载失败"
          :description="roomsError"
        >
          <el-button size="small" type="primary" plain @click="refreshRooms">重试</el-button>
        </StateView>

        <StateView
          v-else-if="rooms.length === 0"
          compact
          state="empty"
          title="还没有等待中的房间"
          description="创建一个房间，或者让 KP 把房间号发给你"
        />

        <div v-else class="room-list">
          <div v-for="r in rooms" :key="r.room_id" class="room-row">
            <span class="room-code coc-mono">{{ r.room_id }}</span>
            <span class="room-name">{{ r.name }}</span>
            <span class="room-kp">KP：{{ r.kp_name }}</span>
            <el-button size="small" type="primary" plain @click="openJoin(r.room_id)">加入</el-button>
          </div>
        </div>
      </div>
    </section>

    <!-- 建房弹窗 -->
    <el-dialog v-model="createVisible" title="创建房间" width="420px">
      <el-form label-width="80px">
        <el-form-item label="房间名">
          <el-input v-model="createForm.name" placeholder="如：雾都疑云" maxlength="50" />
        </el-form-item>
        <el-form-item label="KP 昵称">
          <el-input v-model="createForm.kp_name" placeholder="你的守秘人名字" maxlength="50" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="doCreate">创建并进入</el-button>
      </template>
    </el-dialog>

    <!-- 加入弹窗 -->
    <el-dialog v-model="joinVisible" title="加入房间" width="420px">
      <el-form label-width="80px">
        <el-form-item label="房间号">
          <el-input
            v-model="joinForm.room_id"
            placeholder="8 位短码"
            maxlength="8"
            class="code-input"
          />
        </el-form-item>
        <el-form-item label="你的名字">
          <el-input v-model="joinForm.player_name" placeholder="房间内显示的名字" maxlength="50" />
        </el-form-item>
        <el-form-item label="角色卡">
          <el-select v-model="joinForm.card_id" placeholder="选择调查员卡（可不选）" clearable style="width: 100%">
            <el-option
              v-for="c in cards"
              :key="c.id"
              :label="`${c.name} · ${c.occupation}`"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="joinVisible = false">取消</el-button>
        <el-button type="primary" @click="doJoin">加入</el-button>
      </template>
    </el-dialog>

    <!-- 全局 API / 模型配置（与设置页同一个组件：供应商/Key/模型/超时/轻任务模型/Token 总账） -->
    <LlmSettingsDialog v-model:visible="settingsVisible" />
  </main>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-6);
  max-width: 1040px;
  margin: 0 auto;
  padding: var(--coc-sp-8) var(--coc-sp-5) var(--coc-sp-10);
}

/* ---------- 首屏 ---------- */
.hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.hero-title {
  font-size: var(--coc-fs-2xl);
  letter-spacing: 2px;
  color: var(--coc-text-strong);
}

.hero-sub {
  margin-top: var(--coc-sp-2);
  font-size: var(--coc-fs-base);
  color: var(--coc-text-muted);
}

.entries {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--coc-sp-4);
  width: 100%;
  max-width: 720px;
  margin-top: var(--coc-sp-6);
}

.entry {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  padding: var(--coc-sp-4);
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-lg);
  background: rgba(22, 32, 50, 0.72);
  color: var(--coc-text);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
}

.entry--kp:hover {
  border-color: rgba(230, 162, 60, 0.5);
  box-shadow: var(--coc-glow-brand);
}

.entry--player:hover {
  border-color: var(--coc-border-glow);
  box-shadow: var(--coc-glow);
}

.entry-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 46px;
  height: 46px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: var(--coc-card-2);
  color: var(--coc-accent);
}

.entry--kp .entry-icon {
  border-color: rgba(230, 162, 60, 0.4);
  background: var(--coc-brand-soft);
  color: var(--coc-brand);
}

.entry-body {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.entry-title {
  font-size: var(--coc-fs-md);
  font-weight: 600;
  color: var(--coc-text-strong);
}

.entry-desc {
  font-size: var(--coc-fs-xs);
  line-height: 1.6;
  color: var(--coc-text-muted);
}

/* ---------- 次级入口 ---------- */
.quick-links {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--coc-sp-2);
  margin-top: var(--coc-sp-5);
}

.quick-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-full);
  background: rgba(22, 32, 50, 0.6);
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease), border-color var(--coc-dur-fast) var(--coc-ease);
}

.quick-link:hover {
  border-color: var(--coc-border-glow);
  color: var(--coc-accent);
}

/* ---------- 等待中的房间 ---------- */
.lobby {
  width: 100%;
}

.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-sm);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-xs);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease), border-color var(--coc-dur-fast) var(--coc-ease);
}

.refresh-btn:hover:not(:disabled) {
  border-color: var(--coc-border-glow);
  color: var(--coc-accent);
}

.refresh-btn:disabled {
  opacity: 0.6;
  cursor: default;
}

.room-list {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-2);
}

.room-row {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  padding: 10px var(--coc-sp-3);
  border: 1px solid var(--coc-border-soft);
  border-radius: var(--coc-radius);
  background: var(--coc-card-2);
  transition: border-color var(--coc-dur-fast) var(--coc-ease);
}

.room-row:hover {
  border-color: var(--coc-border-glow);
}

.room-code {
  font-weight: 600;
  letter-spacing: 2px;
  color: var(--coc-brand);
}

.room-name {
  flex: 1;
  min-width: 0;
  font-size: var(--coc-fs-base);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.room-kp {
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-muted);
}

/* 房间号输入自动大写 */
.code-input :deep(input) {
  text-transform: uppercase;
  letter-spacing: 3px;
}

@media (max-width: 720px) {
  .home {
    padding: var(--coc-sp-5) var(--coc-sp-3) var(--coc-sp-8);
  }

  .hero-title {
    font-size: var(--coc-fs-xl);
  }
}
</style>
