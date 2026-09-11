<script setup lang="ts">
/**
 * 大厅首页 — 阶段 3.1。
 * 两个入口：KP 创建房间（拿 8 位短码）/ 玩家加入房间（输短码选卡进房）。
 * 下方展示等待中的房间列表，可直接点加入。
 */
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createRoom, joinRoom, listRooms } from '@/api/rooms'
import { listCards, type CardListItem } from '@/api/cards'
import LlmSettingsDialog from '@/components/LlmSettingsDialog.vue'
import LlmFirstRunGuide from '@/components/LlmFirstRunGuide.vue'
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

// ---------- 等待中的房间 ----------
const rooms = ref<RoomListItem[]>([])

async function refreshRooms() {
  try {
    rooms.value = await listRooms()
  } catch {
    /* 静默：列表加载失败不弹窗，点刷新再看 */
  }
}

onMounted(refreshRooms)
</script>

<template>
  <main class="home">
    <h1 class="home-title">雾都疑云 · CoC 跑团助手</h1>
    <p class="home-sub">创建房间开启调查，或输入房间号加入一场正在进行的故事</p>

    <!-- 首次配置引导（6.1）：未配 LLM 时提示可一键进演示模式，不挡开团 -->
    <LlmFirstRunGuide ref="guideRef" @configure="settingsVisible = true" />

    <!-- 全局 LLM / API 配置入口（2026-09-10 用户反馈 #1）：配置是全局的，
         所以把详细设置页放在大厅；房间与模组页只做只读回显 + 检测门禁 -->
    <div class="home-tools">
      <el-button size="small" plain @click="settingsVisible = true">API / 模型配置</el-button>
    </div>

    <div class="entries">
      <div class="entry-card entry-card--kp" @click="createVisible = true">
        <span class="entry-icon">🎭</span>
        <h2>创建房间</h2>
        <p>作为守秘人（KP）开团，获得房间短码分发给玩家</p>
      </div>
      <div class="entry-card entry-card--player" @click="openJoin()">
        <span class="entry-icon">🔍</span>
        <h2>加入房间</h2>
        <p>输入 8 位房间短码，带上你的调查员卡入场</p>
      </div>
    </div>

    <section class="lobby">
      <div class="lobby-head">
        <h3>等待中的房间</h3>
        <el-button text type="primary" @click="refreshRooms">刷新</el-button>
      </div>
      <el-empty v-if="rooms.length === 0" description="还没有等待中的房间" :image-size="72" />
      <div v-for="r in rooms" :key="r.room_id" class="room-row">
        <span class="lobby-code">{{ r.room_id }}</span>
        <span class="lobby-name">{{ r.name }}</span>
        <span class="lobby-kp">KP：{{ r.kp_name }}</span>
        <el-button size="small" type="primary" plain @click="openJoin(r.room_id)">加入</el-button>
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

    <!-- 全局 API / 模型配置（与 KP 台同一个组件：供应商/Key/模型/超时/轻任务模型/Token 总账） -->
    <LlmSettingsDialog v-model:visible="settingsVisible" />
  </main>
</template>

<style scoped>
.home {
  min-height: 100vh;
  padding: 48px 24px;
  background:
    radial-gradient(ellipse at 20% 0%, rgba(44, 62, 80, 0.55), transparent 55%),
    radial-gradient(ellipse at 85% 100%, rgba(155, 89, 182, 0.18), transparent 50%),
    #1b2431;
  color: #e8eaed;
  text-align: center;
}

.home-title {
  margin: 0;
  font-size: 30px;
  font-weight: 600;
  letter-spacing: 2px;
}

.home-tools {
  display: flex;
  justify-content: center;
  margin: -18px 0 26px;
}

.home-sub {
  margin: 10px 0 36px;
  color: #909399;
  font-size: 14px;
}

.entries {
  display: flex;
  justify-content: center;
  gap: 24px;
}

.entry-card {
  width: 260px;
  padding: 28px 20px;
  border-radius: 12px;
  border: 1px solid #2c3e50;
  background: #222d3d;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
}

.entry-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

.entry-card--kp:hover {
  border-color: #e6a23c;
}

.entry-card--player:hover {
  border-color: #9b59b6;
}

.entry-icon {
  font-size: 34px;
}

.entry-card h2 {
  margin: 12px 0 8px;
  font-size: 18px;
  font-weight: 600;
}

.entry-card p {
  margin: 0;
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}

.lobby {
  max-width: 640px;
  margin: 44px auto 0;
  text-align: left;
}

.lobby-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.lobby-head h3 {
  margin: 0;
  font-size: 16px;
  color: #e6a23c;
}

.room-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 16px;
  margin-top: 10px;
  background: #222d3d;
  border: 1px solid #2c3e50;
  border-radius: 8px;
}

.lobby-code {
  font-weight: 600;
  letter-spacing: 3px;
  color: #e6a23c;
}

.lobby-name {
  flex: 1;
  font-size: 14px;
}

.lobby-kp {
  font-size: 13px;
  color: #909399;
}

/* 房间号输入自动大写 */
.code-input :deep(input) {
  text-transform: uppercase;
  letter-spacing: 3px;
}
</style>
