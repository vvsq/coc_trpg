<script setup lang="ts">
/**
 * 聊天流（剧情 / OOC 双 tab + 底部输入框）— 3.3 从 RoomView 左栏抽出复用。
 *
 * 智能组件：直接读写 room store（RoomView 与 KP 控制台共享同一会话状态），
 * 信封分派仍在 store，这里只管渲染与输入。
 * 渲染分支：status 状态行（3.3，灰字含 reason）→ system 系统行 → roll 骰子徽章 → 普通气泡。
 */
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoomStore } from '@/stores/room'
import { rollCheckRequest } from '@/api/rooms'
import type { ChatItem, CheckRequestPayload, RollLevel, RollResultPayload } from '@/types/ws'
import { ROLL_BADGE_STYLES } from '@/types/ws'

const room = useRoomStore()
const rollingRequest = ref('')

const activeTab = ref<'narrative' | 'ooc'>('narrative')
const draftText = ref('')
const streamEl = ref<HTMLElement | null>(null)

const currentMsgs = computed<ChatItem[]>(() =>
  activeTab.value === 'narrative' ? room.narrativeMsgs : room.oocMsgs,
)

// ---------- 骰子徽章渲染 ----------
const DIFF_LABELS = { standard: '常规', hard: '困难', extreme: '极难' } as const

function rollBadgeStyle(level: RollLevel): Record<string, string> {
  const s = ROLL_BADGE_STYLES[level]
  return { borderColor: s.border, background: s.bg }
}

/** 徽章 class：等级类始终有；入场/光晕动画类仅实时消息有（历史回放不重播，2.5②） */
function rollBadgeClass(level: RollLevel, isHistory?: boolean): string[] {
  const cls = [`roll-badge--${level}`]
  if (!isHistory) cls.push('roll-badge--pop')
  return cls
}

function rollTextColor(level: RollLevel): string {
  return ROLL_BADGE_STYLES[level].text
}

function skillFullName(r: RollResultPayload): string {
  return r.detail ? `${r.skill_name}（${r.detail}）` : r.skill_name
}

function fmtTs(ts: string): string {
  // 信封 ts 是 ISO 字符串，聊天流只展示时分秒
  return ts.slice(11, 19) || ts
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

// ---------- 检定下放（4.3+）：AI 定技能/难度/后果，被点名的玩家本人投掷 ----------

function crState(cr: CheckRequestPayload): 'mine' | 'fulfilled' | 'waiting' {
  if (room.fulfilledRequests.has(cr.request_id) || cr.fulfilled) return 'fulfilled'
  return cr.target === room.playerName ? 'mine' : 'waiting'
}

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
  <section class="chat-panel">
    <el-tabs v-model="activeTab" class="chat-tabs">
      <el-tab-pane label="剧情" name="narrative" />
      <el-tab-pane label="OOC 闲聊" name="ooc" />
    </el-tabs>

    <div ref="streamEl" class="chat-stream">
      <div
        v-for="(m, i) in currentMsgs"
        :key="i"
        class="msg"
        :class="[
          `msg--${m.channel}`,
          m.role === 'kp' ? 'msg--kp' : 'msg--player',
          m.sender === room.playerName ? 'msg--mine' : '',
        ]"
      >
        <!-- 状态变更行（3.3）：灰色小字含 reason，与骰子徽章区分 -->
        <div v-if="m.status" class="status-line">
          <span class="status-op">{{ m.sender }}</span> {{ m.text }}
        </div>
        <template v-else-if="m.channel === 'system'">
          <div class="sys-line">— {{ m.text }} —</div>
        </template>
        <template v-else>
          <div class="msg-head">
            <span class="msg-sender">{{ m.sender }}</span>
            <span v-if="m.ai" class="ai-chip">AI 主持</span>
            <span v-if="m.role === 'kp' && !m.ai && !m.keeper" class="kp-chip">KP</span>
            <span v-if="m.keeper" class="keeper-chip">仅 KP</span>
            <span class="msg-time">{{ fmtTs(m.ts) }}</span>
          </div>
          <!-- 4.2：AI 的 keeper 笔记（仅 KP 端可见，深色专享样式） -->
          <div v-if="m.keeper" class="keeper-bubble">{{ m.text }}</div>
          <!-- 骰子消息：按成功等级着色的结果徽章（3.2），入场/光晕动画（2.5②） -->
          <div
            v-else-if="m.roll"
            :class="['roll-badge', rollBadgeClass(m.roll.level, m.history)]"
            :style="rollBadgeStyle(m.roll.level)"
          >
            <div class="roll-top">
              <span class="roll-skill">
                {{ skillFullName(m.roll) }} {{ m.roll.value }}
              </span>
              <span v-if="m.roll.difficulty !== 'standard'" class="roll-diff">
                {{ DIFF_LABELS[m.roll.difficulty] }}
              </span>
              <span v-if="m.roll.secret" class="roll-secret">暗骰</span>
              <span class="roll-level" :style="{ color: rollTextColor(m.roll.level) }">
                {{ m.roll.level_label }}
              </span>
            </div>
            <div class="roll-detail">
              掷出 <b>{{ m.roll.roll.value }}</b>
              <span v-if="m.roll.roll.tens.length > 1">
                （十位 {{ m.roll.roll.tens.join(' / ') }}）
              </span>
              · 目标 {{ m.roll.target }}
            </div>
          </div>
          <!-- 4.3+：检定下放请求卡——AI 定技能/难度/后果，被点名玩家点「投掷」 -->
          <div
            v-else-if="m.checkRequest"
            class="check-request"
            :class="{ 'cr--mine': crState(m.checkRequest) === 'mine' }"
          >
            <div class="cr-head">
              🎲 检定请求 · {{ m.checkRequest.skill_name }}
              <span v-if="m.checkRequest.difficulty !== 'standard'" class="cr-diff">
                {{ DIFF_LABELS[m.checkRequest.difficulty] }}
              </span>
              <span class="cr-target">@{{ m.checkRequest.target }}</span>
            </div>
            <div class="cr-reason">{{ m.checkRequest.reason }}</div>
            <div class="cr-action">
              <el-button
                v-if="crState(m.checkRequest) === 'mine'"
                type="primary"
                size="small"
                :loading="rollingRequest === m.checkRequest.request_id"
                @click="doRoll(m.checkRequest)"
              >
                投掷
              </el-button>
              <span v-else-if="crState(m.checkRequest) === 'fulfilled'" class="cr-done">已投掷</span>
              <span v-else class="cr-wait">等待 {{ m.checkRequest.target }} 投掷…</span>
            </div>
          </div>
          <!-- 4.2：AI 主持叙事（当前状况+已知变化）+ 行动切口选项 + 自由行动提示 -->
          <template v-else-if="m.ai">
            <div class="msg-bubble msg-bubble--ai">{{ m.text }}</div>
            <div v-if="m.options?.length" class="ai-options">
              <p class="ai-options-title">行动切口（点击发送，或直接自由输入）</p>
              <button
                v-for="(opt, oi) in m.options"
                :key="oi"
                type="button"
                class="ai-option"
                @click="pickOption(opt)"
              >
                {{ oi + 1 }}. {{ opt }}
              </button>
            </div>
            <p class="ai-free-hint">你也可以直接在下方输入框自由描述任何行动。</p>
          </template>
          <div v-else class="msg-bubble">{{ m.text }}</div>
        </template>
      </div>
      <div v-if="currentMsgs.length === 0" class="empty-hint">
        {{ activeTab === 'narrative' ? '剧情尚未开始，等待 KP 揭示…' : '还没有人闲聊，说点什么吧' }}
      </div>
    </div>

    <div class="chat-input">
      <el-input
        v-model="draftText"
        :placeholder="activeTab === 'narrative' ? '描述你的行动…' : '和桌边的伙伴聊聊…'"
        size="large"
        @keyup.enter="send"
      />
      <el-button type="primary" size="large" :disabled="!room.connected" @click="send">
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
  background: #f5f7fa;
  border-radius: 10px;
  overflow: hidden;
}

.chat-tabs {
  padding: 0 16px;
  background: #fff;
  flex-shrink: 0;
}

.chat-stream {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.msg--system {
  text-align: center;
}

.sys-line {
  font-size: 12px;
  font-style: italic;
  color: #909399;
}

/* 状态变更行（3.3）：灰色小字，含操作者与 reason，与骰子徽章/气泡区分 */
.status-line {
  text-align: center;
  font-size: 12px;
  color: #909399;
}

.status-op {
  font-weight: 600;
  color: #b0b6bf;
}

.msg-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 2px;
}

.msg-sender {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.kp-chip {
  padding: 0 6px;
  border-radius: 4px;
  background: #e6a23c;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
}

/* ---------- 4.2：AI 主持标识与四段渲染 ---------- */

.ai-chip {
  padding: 0 6px;
  border-radius: 4px;
  background: #409eff;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
}

.keeper-chip {
  padding: 0 6px;
  border-radius: 4px;
  background: #7a5cd6;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
}

.keeper-bubble {
  display: inline-block;
  max-width: 86%;
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(122, 92, 214, 0.12);
  border: 1px solid rgba(122, 92, 214, 0.4);
  color: #4a3a80;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.msg--mine .keeper-bubble {
  text-align: left;
}

.msg-bubble--ai {
  background: #f4f8ff;
  border-color: #c6e2ff;
}

.ai-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 78%;
  margin-top: 6px;
}

.ai-options-title {
  margin: 0;
  font-size: 11px;
  color: #909399;
}

.ai-option {
  padding: 7px 12px;
  border: 1px solid #c6e2ff;
  border-radius: 8px;
  background: #fff;
  color: #2f5aa8;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.ai-option:hover {
  background: #ecf5ff;
  border-color: #409eff;
}

.ai-free-hint {
  margin: 6px 0 0;
  font-size: 11px;
  color: #b0b6bf;
  max-width: 78%;
}

.msg-time {
  font-size: 11px;
  color: #c0c4cc;
}

.msg-bubble {
  display: inline-block;
  max-width: 78%;
  padding: 8px 12px;
  border-radius: 8px;
  background: #fff;
  border: 1px solid #e4e7ed;
  color: #303133;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
  white-space: pre-wrap;
}

/* 剧情流里区分身份：KP 剧情 = 橙色边框，玩家行动描述 = 灰色边框 */
.msg--narrative.msg--kp .msg-bubble {
  border-left: 3px solid #e6a23c;
}

.msg--narrative.msg--player .msg-bubble {
  border-left: 3px solid #9aa4b2;
}

/* AI 主持叙事：蓝色左边框与 ai-chip 呼应 */
.msg--narrative.msg--kp .msg-bubble--ai {
  border-left-color: #409eff;
}

/* OOC：浅蓝气泡 */
.msg--ooc .msg-bubble {
  background: #ecf5ff;
  border-color: #d9ecff;
}

/* 自己的消息靠右 */
.msg--mine {
  align-items: flex-end;
  text-align: right;
}

/* 自己消息的名字/时间也靠右，与气泡对齐（否则头部整行靠左，视觉割裂） */
.msg--mine .msg-head {
  justify-content: flex-end;
}

.msg--mine .msg-bubble {
  text-align: left;
  background: #f0f9eb;
  border-color: #e1f3d8;
}

/* ---------- 检定下放请求卡（4.3+） ---------- */
.check-request {
  max-width: 86%;
  padding: 10px 12px;
  border: 1px solid rgba(230, 162, 60, 0.4);
  border-left: 4px solid #e6a23c;
  border-radius: 8px;
  background: rgba(230, 162, 60, 0.08);
  font-size: 13px;
  text-align: left;
}

.cr--mine {
  border-color: rgba(103, 194, 58, 0.5);
  border-left-color: #67c23a;
  background: rgba(103, 194, 58, 0.08);
}

.cr-head {
  font-weight: 600;
  color: #e6a23c;
  margin-bottom: 4px;
}

.cr--mine .cr-head {
  color: #67c23a;
}

.cr-diff {
  margin-left: 6px;
  font-size: 11px;
  color: #909399;
}

.cr-target {
  margin-left: 6px;
  font-size: 12px;
  color: #c0c4cc;
}

.cr-reason {
  color: #cdd0d6;
  line-height: 1.5;
  margin-bottom: 8px;
}

.cr-done,
.cr-wait {
  font-size: 12px;
  color: #909399;
}

/* ---------- 骰子结果徽章（3.2，颜色由内联 style 按等级注入） ---------- */
.roll-badge {
  display: inline-block;
  max-width: 86%;
  padding: 8px 12px;
  border: 1px solid #dcdfe6;
  border-left-width: 4px;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
  text-align: left;
  word-break: break-word;
}

/* ---------- 骰子徽章动画（2.5②）：入场 pop + 大成功/大失败呼吸光晕 ----------
   光晕色走 CSS 变量：critical 金（配色同 ROLL_BADGE_STYLES.critical.border #d4a017）、
   fumble 红（同 fumble.border #f56c6c）。历史回放的徽章没有 --pop 类，不播动画。 */
.roll-badge--pop {
  animation: roll-pop 0.2s ease-out;
}

.roll-badge--critical.roll-badge--pop,
.roll-badge--fumble.roll-badge--pop {
  animation: roll-pop 0.2s ease-out, roll-pulse 1.2s ease-in-out 2;
}

.roll-badge--critical {
  --roll-pulse-color: 212, 160, 23;
}

.roll-badge--fumble {
  --roll-pulse-color: 245, 108, 108;
}

@keyframes roll-pop {
  from {
    transform: scale(0.85);
    opacity: 0;
  }

  to {
    transform: scale(1);
    opacity: 1;
  }
}

@keyframes roll-pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 rgba(var(--roll-pulse-color), 0);
  }

  50% {
    box-shadow: 0 0 14px 3px rgba(var(--roll-pulse-color), 0.55);
  }
}

.roll-top {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.roll-skill {
  font-weight: 600;
  color: #303133;
}

.roll-diff {
  font-size: 11px;
  color: #909399;
}

.roll-secret {
  padding: 0 6px;
  border-radius: 4px;
  background: #909399;
  color: #fff;
  font-size: 11px;
  line-height: 18px;
}

.roll-level {
  margin-left: auto;
  font-weight: 600;
  white-space: nowrap;
}

.roll-detail {
  margin-top: 2px;
  font-size: 12px;
  color: #606266;
}

.empty-hint {
  margin: auto;
  font-size: 13px;
  color: #909399;
}

.chat-input {
  display: flex;
  gap: 10px;
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #e4e7ed;
  flex-shrink: 0;
}
</style>
