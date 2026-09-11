<script setup lang="ts">
/**
 * 聊天流容器（剧情 / OOC 双 tab + 底部输入框）— 3.3 从 RoomView 抽出复用；6.2⑤ 拆分。
 *
 * 职责收敛为「容器」：tab 切换 / 滚动跟随 / 输入与发送 / 检定下放的投掷动作。
 * 单条消息的渲染（气泡 / 骰子徽章 / 检定请求卡 / 行动切口 / 状态变更卡 / 系统行）
 * 全部下沉到 `components/chat/ChatMessageItem.vue`，RoomView 与 KP 控制台共用同一套观感。
 * 智能组件：直接读写 room store（信封分派仍在 store），这里只管组织与输入。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoomStore } from '@/stores/room'
import { rollCheckRequest } from '@/api/rooms'
import ChatMessageItem from '@/components/chat/ChatMessageItem.vue'
import CocIcon from '@/components/common/CocIcon.vue'
import StateView from '@/components/common/StateView.vue'
import type { ChatItem, CheckRequestPayload } from '@/types/ws'

const room = useRoomStore()
const rollingRequest = ref('')

const activeTab = ref<'narrative' | 'ooc'>('narrative')
const draftText = ref('')
const streamEl = ref<HTMLElement | null>(null)

const currentMsgs = computed<ChatItem[]>(() =>
  activeTab.value === 'narrative' ? room.narrativeMsgs : room.oocMsgs,
)

/** 该消息的检定下放请求是否已结算（store 集合 ∪ payload 自带标记，与抽取前一致） */
function isFulfilled(m: ChatItem): boolean {
  const cr = m.checkRequest
  if (!cr) return false
  return room.fulfilledRequests.has(cr.request_id) || cr.fulfilled
}

function send(): void {
  const text = draftText.value.trim()
  if (!text) return
  if (!room.connected) {
    ElMessage.warning('连接已断开，正在重连…')
    return
  }
  room.sendChat(activeTab.value, text)
  draftText.value = ''
}

/** 4.2：点击「行动切口」选项 = 以该选项文本发起剧情行动（自由输入始终优先） */
function pickOption(option: string): void {
  if (!room.connected) {
    ElMessage.warning('连接已断开，正在重连…')
    return
  }
  room.sendChat('narrative', option)
}

/** 4.3+：检定下放——AI 定技能/难度/后果，被点名的玩家本人投掷（服务端按卡结算） */
async function doRoll(cr: CheckRequestPayload): Promise<void> {
  if (rollingRequest.value) return
  rollingRequest.value = cr.request_id
  try {
    await rollCheckRequest(room.roomId, cr.request_id, room.playerName)
    room.markFulfilled(cr.request_id) // 广播到达前先本地置位防双击
  } catch {
    // 拦截器已提示（409 重复投掷 / 403 非本人等）
  } finally {
    rollingRequest.value = ''
  }
}

// 新消息到达时滚到底部（剧情/OOC 都跟随）
watch(
  () => [room.narrativeMsgs.length, room.oocMsgs.length],
  async () => {
    await nextTick()
    streamEl.value?.scrollTo({ top: streamEl.value.scrollHeight })
  },
)
</script>

<template>
  <section class="chat-panel coc-panel">
    <el-tabs v-model="activeTab" class="chat-tabs">
      <el-tab-pane label="剧情" name="narrative" />
      <el-tab-pane label="OOC 闲聊" name="ooc" />
    </el-tabs>

    <div ref="streamEl" class="chat-stream coc-scroll">
      <ChatMessageItem
        v-for="(m, i) in currentMsgs"
        :key="i"
        :msg="m"
        :my-name="room.playerName"
        :fulfilled="isFulfilled(m)"
        :rolling="rollingRequest === m.checkRequest?.request_id"
        @pick-option="pickOption"
        @roll="doRoll"
      />

      <!-- 空态（6.2⑨）：统一三态组件 -->
      <StateView
        v-if="currentMsgs.length === 0"
        class="stream-empty"
        state="empty"
        icon="message"
        :title="activeTab === 'narrative' ? '剧情尚未开始' : '还没有人闲聊'"
        :description="
          activeTab === 'narrative' ? '等待守秘人揭示第一幕，或在下方描述你的行动' : '和桌边的伙伴聊点什么吧'
        "
      />
    </div>

    <div class="chat-input">
      <el-input
        v-model="draftText"
        :placeholder="activeTab === 'narrative' ? '描述你的行动…' : '和桌边的伙伴聊聊…'"
        size="large"
        @keyup.enter="send"
      />
      <el-button type="primary" size="large" :disabled="!room.connected" @click="send">
        <CocIcon name="chevronRight" :size="16" />
        发送
      </el-button>
    </div>
  </section>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}

.chat-tabs {
  flex-shrink: 0;
  padding: 0 var(--coc-sp-4);
  border-bottom: 1px solid var(--coc-border-soft);
  background: rgba(22, 32, 50, 0.55);
}

.chat-stream {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: var(--coc-sp-4);
  padding: var(--coc-sp-4);
}

/* ---------- 空态（垂直居中，撑满剩余高度） ---------- */
.stream-empty {
  margin: auto;
}

/* ---------- 输入区 ---------- */
.chat-input {
  display: flex;
  flex-shrink: 0;
  gap: var(--coc-sp-3);
  padding: var(--coc-sp-3) var(--coc-sp-4);
  border-top: 1px solid var(--coc-border-soft);
  background: rgba(22, 32, 50, 0.55);
}

.chat-input :deep(.el-button) {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
</style>
