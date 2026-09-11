<script setup lang="ts">
/**
 * 单条消息行 — 阶段 6.2⑤（从 ChatStream 抽出；ChatStream 只保留 tab / 滚动 / 输入）。
 *
 * 渲染分支顺序与抽取前**完全一致**（顺序不可调换）：
 *   status 状态变更行 → system 系统行 → keeper 紫行 → 骰子徽章 → 检定下放请求卡
 *   → AI 四段叙事（含行动切口）→ 普通气泡
 *
 * 视觉基线：ui-example/前端样例demo.html 的「头像 + 昵称 + 时间」消息行结构 + 暗色令牌。
 * 骰子徽章不再用 ws.ts 的浅色配色表直接铺底（白底在暗色流里像一块补丁），改用
 * tokens.css 的 `--coc-roll-*` 派生色（语义与 ROLL_BADGE_STYLES 一一对应，协议层表未动）。
 *
 * 纯展示组件：不读 store（fulfilled / rolling 由 ChatStream 传入）、不发请求，事件上抛。
 */
import { computed } from 'vue'
import ChatAvatar from './ChatAvatar.vue'
import ChatNoticeCard from './ChatNoticeCard.vue'
import type { ChatItem, CheckRequestPayload, RollLevel } from '@/types/ws'

const props = defineProps<{
  msg: ChatItem
  /** 自己的昵称（决定左右对齐与「我的消息」配色） */
  myName: string
  /** 该消息的检定下放请求是否已结算（store.fulfilledRequests ∩ payload.fulfilled） */
  fulfilled: boolean
  /** 是否正在投掷该请求（按钮 loading） */
  rolling: boolean
}>()

const emit = defineEmits<{
  pickOption: [text: string]
  roll: [cr: CheckRequestPayload]
}>()

const DIFF_LABELS = { standard: '常规', hard: '困难', extreme: '极难' } as const

/** 等级 → 令牌变量名（语义同 types/ws.ts ROLL_BADGE_STYLES） */
const ROLL_LEVEL_VARS: Record<RollLevel, string> = {
  critical: 'var(--coc-roll-critical)',
  extreme: 'var(--coc-roll-extreme)',
  hard: 'var(--coc-roll-hard)',
  regular: 'var(--coc-roll-regular)',
  fail: 'var(--coc-roll-fail)',
  fumble: 'var(--coc-roll-fumble)',
}

/** 大成功/大失败才有呼吸光晕（rgb 三元组，供 animations.css 的 coc-roll-pulse 使用） */
const PULSE_RGB: Partial<Record<RollLevel, string>> = {
  critical: '212, 160, 23',
  fumble: '245, 108, 108',
}

const mine = computed(() => props.msg.sender === props.myName)
/** KP 侧（人类 KP / AI 主持 / AI 的 keeper 笔记）在叙事流里用强调色昵称 */
const fromKeeper = computed(() => props.msg.role === 'kp' || !!props.msg.ai || !!props.msg.keeper)

const crState = computed<'mine' | 'fulfilled' | 'waiting' | null>(() => {
  const cr = props.msg.checkRequest
  if (!cr) return null
  if (props.fulfilled) return 'fulfilled'
  return cr.target === props.myName ? 'mine' : 'waiting'
})

function rollStyle(level: RollLevel): Record<string, string> {
  const color = ROLL_LEVEL_VARS[level]
  const style: Record<string, string> = { borderColor: color, '--coc-roll-accent': color }
  const rgb = PULSE_RGB[level]
  if (rgb) style['--coc-pulse-rgb'] = rgb
  return style
}

/** 徽章动画类：入场/光晕仅实时消息有（历史回放不重播，2.5②） */
function rollClass(level: RollLevel, isHistory?: boolean): string[] {
  const cls = [`roll-badge--${level}`]
  if (!isHistory) {
    cls.push('coc-roll-in')
    if (PULSE_RGB[level]) cls.push('coc-roll-in--epic')
  }
  return cls
}

function skillFullName(skillName: string, detail: string): string {
  return detail ? `${skillName}（${detail}）` : skillName
}

function fmtTs(ts: string): string {
  // 信封 ts 是 ISO 字符串，聊天流只展示时分秒
  return ts.slice(11, 19) || ts
}
</script>

<template>
  <!-- ① 状态变更行（3.3）：琥珀色「重要信息」卡，含 reason（D9） -->
  <ChatNoticeCard v-if="msg.status" :sender="msg.sender" :text="msg.text" title="状态变更" />

  <!-- ② 系统行（场景变更 / 进出房 / 读档）：居中细线 + 斜体灰字 -->
  <div v-else-if="msg.channel === 'system'" class="sys-line">
    <span class="sys-rule" />
    <span class="sys-text">{{ msg.text }}</span>
    <span class="sys-rule" />
  </div>

  <!-- ③ 正常消息：头像 + 昵称/时间 + 正文（自己的消息右对齐，对齐移动端样例气泡） -->
  <div
    v-else
    class="msg"
    :class="[
      `msg--${msg.channel}`,
      fromKeeper ? 'msg--kp' : 'msg--player',
      mine && 'msg--mine',
      !msg.history && 'coc-msg-in',
    ]"
  >
    <ChatAvatar
      v-if="!mine"
      :name="msg.sender"
      :role="fromKeeper ? 'kp' : 'player'"
      :ai="!!msg.ai"
      :keeper="!!msg.keeper"
      :icon="msg.roll ? 'dice' : undefined"
    />

    <div class="msg-body">
      <div class="msg-head">
        <span class="msg-sender" :class="{ 'msg-sender--kp': fromKeeper }">{{ msg.sender }}</span>
        <span v-if="msg.ai" class="chip chip--ai">AI 主持</span>
        <span v-if="msg.role === 'kp' && !msg.ai && !msg.keeper" class="chip chip--kp">KP</span>
        <span v-if="msg.keeper" class="chip chip--keeper">仅 KP</span>
        <span class="msg-time">{{ fmtTs(msg.ts) }}</span>
      </div>

      <!-- keeper 笔记 / 暗骰详情（4.2）：紫行，仅 KP 端可见 -->
      <div v-if="msg.keeper" class="keeper-bubble">{{ msg.text }}</div>

      <!-- 骰子结果徽章（3.2）：等级色由 --coc-roll-* 注入 -->
      <div v-else-if="msg.roll" class="roll-badge" :class="rollClass(msg.roll.level, msg.history)" :style="rollStyle(msg.roll.level)">
        <div class="roll-top">
          <span class="roll-skill">{{ skillFullName(msg.roll.skill_name, msg.roll.detail) }} {{ msg.roll.value }}</span>
          <span v-if="msg.roll.difficulty !== 'standard'" class="roll-diff">
            {{ DIFF_LABELS[msg.roll.difficulty] }}
          </span>
          <span v-if="msg.roll.secret" class="roll-secret">暗骰</span>
          <span class="roll-level">{{ msg.roll.level_label }}</span>
        </div>
        <div class="roll-detail">
          掷出 <b>{{ msg.roll.roll.value }}</b>
          <span v-if="msg.roll.roll.tens.length > 1">（十位 {{ msg.roll.roll.tens.join(' / ') }}）</span>
          · 目标 {{ msg.roll.target }}
        </div>
      </div>

      <!-- 检定下放请求卡（4.3+）：AI 定技能/难度/后果，被点名玩家点「投掷」 -->
      <div
        v-else-if="msg.checkRequest"
        class="check-request"
        :class="{ 'cr--mine': crState === 'mine' }"
      >
        <div class="cr-head">
          检定请求 · {{ msg.checkRequest.skill_name }}
          <span v-if="msg.checkRequest.difficulty !== 'standard'" class="cr-diff">
            {{ DIFF_LABELS[msg.checkRequest.difficulty] }}
          </span>
          <span class="cr-target">@{{ msg.checkRequest.target }}</span>
        </div>
        <div class="cr-reason">{{ msg.checkRequest.reason }}</div>
        <div class="cr-action">
          <el-button
            v-if="crState === 'mine'"
            type="primary"
            size="small"
            :loading="rolling"
            @click="emit('roll', msg.checkRequest)"
          >
            投掷
          </el-button>
          <span v-else-if="crState === 'fulfilled'" class="cr-done">已投掷</span>
          <span v-else class="cr-wait">等待 {{ msg.checkRequest.target }} 投掷…</span>
        </div>
      </div>

      <!-- AI 四段叙事（4.2）：公开叙事 + 行动切口 + 自由行动提示 -->
      <template v-else-if="msg.ai">
        <div class="msg-bubble msg-bubble--ai">{{ msg.text }}</div>
        <div v-if="msg.options?.length" class="ai-options">
          <p class="ai-options-title">行动切口（点击发送，或直接自由输入）</p>
          <button
            v-for="(opt, oi) in msg.options"
            :key="oi"
            type="button"
            class="ai-option"
            @click="emit('pickOption', opt)"
          >
            <span class="ai-option-no">{{ oi + 1 }}</span>
            <span class="ai-option-text">{{ opt }}</span>
          </button>
        </div>
        <p class="ai-free-hint">你也可以直接在下方输入框自由描述任何行动。</p>
      </template>

      <!-- 普通气泡（KP 剧情 / 玩家行动 / OOC 闲聊） -->
      <div v-else class="msg-bubble">{{ msg.text }}</div>
    </div>
  </div>
</template>

<style scoped>
/* ==================== 系统行 ==================== */
.sys-line {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  padding: 0 var(--coc-sp-2);
}

.sys-rule {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--coc-border-soft), transparent);
}

.sys-text {
  font-size: var(--coc-fs-xs);
  font-style: italic;
  color: var(--coc-text-muted);
  text-align: center;
}

/* ==================== 消息行骨架 ==================== */
.msg {
  display: flex;
  align-items: flex-start;
  gap: var(--coc-sp-3);
}

.msg--mine {
  flex-direction: row-reverse;
}

.msg-body {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
}

.msg--mine .msg-body {
  align-items: flex-end;
}

.msg-head {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin-bottom: 4px;
}

/* 自己的消息：头部整体靠右，但保持「昵称 → 徽章 → 时间」的阅读顺序 */
.msg--mine .msg-head {
  justify-content: flex-end;
}

.msg-sender {
  font-size: var(--coc-fs-sm);
  font-weight: 600;
  color: var(--coc-text-strong);
}

/* KP 与 AI 的昵称走强调色（对齐样例：AI 守秘人 = 青色） */
.msg-sender--kp {
  color: var(--coc-accent);
}

.msg-time {
  font-family: var(--coc-font-mono);
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-dim);
}

/* ==================== 身份小徽章 ==================== */
.chip {
  padding: 0 6px;
  border: 1px solid transparent;
  border-radius: var(--coc-radius-sm);
  font-size: var(--coc-fs-xs);
  line-height: 1.65;
  white-space: nowrap;
}

.chip--kp {
  border-color: rgba(230, 162, 60, 0.45);
  background: var(--coc-brand-soft);
  color: var(--coc-brand);
}

.chip--ai {
  border-color: var(--coc-border-glow);
  background: var(--coc-primary-soft);
  color: var(--coc-accent);
}

.chip--keeper {
  border-color: rgba(122, 92, 214, 0.5);
  background: var(--coc-keeper-soft);
  color: #b9a4f5;
}

/* ==================== 气泡 ==================== */
.msg-bubble {
  display: inline-block;
  max-width: min(100%, 68ch);
  padding: 8px 12px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: var(--coc-card-2);
  color: var(--coc-text);
  font-size: var(--coc-fs-base);
  line-height: var(--coc-lh);
  white-space: pre-wrap;
  word-break: break-word;
}

/* 剧情流里区分身份：KP 橙边（人类）/ AI 青边（机器）/ 玩家灰边 */
.msg--narrative.msg--kp .msg-bubble {
  border-left: 3px solid var(--coc-brand);
}

.msg--narrative.msg--player .msg-bubble {
  border-left: 3px solid var(--coc-border-strong);
}

.msg-bubble--ai {
  border-color: var(--coc-border-glow);
  border-left: 3px solid var(--coc-accent);
  background: linear-gradient(180deg, rgba(34, 211, 238, 0.1), rgba(14, 165, 233, 0.04));
}

/* OOC 闲聊：不强调身份，统一灰蓝气泡 */
.msg--ooc .msg-bubble {
  background: var(--coc-card-3);
}

/* 自己的消息：青色调 + 气泡尖角（对齐移动端样例） */
.msg--mine .msg-bubble {
  border-color: var(--coc-border-glow);
  border-top-right-radius: var(--coc-radius-sm);
  background: var(--coc-primary-soft);
}

.msg--mine .msg-bubble--ai {
  border-left-width: 1px;
}

/* ==================== 仅 KP 紫行 ==================== */
.keeper-bubble {
  display: inline-block;
  max-width: min(100%, 68ch);
  padding: 8px 12px;
  border: 1px dashed rgba(122, 92, 214, 0.6);
  border-radius: var(--coc-radius);
  background: var(--coc-keeper-soft);
  color: #cbbdf7;
  font-size: var(--coc-fs-sm);
  line-height: var(--coc-lh);
  white-space: pre-wrap;
  word-break: break-word;
}

/* ==================== 骰子徽章 ==================== */
.roll-badge {
  display: inline-block;
  max-width: min(100%, 68ch);
  padding: 8px 12px;
  border: 1px solid var(--coc-border);
  border-left-width: 4px;
  border-radius: var(--coc-radius);
  background: var(--coc-card-2);
  box-shadow: var(--coc-shadow-sm);
  font-size: var(--coc-fs-base);
  line-height: var(--coc-lh);
  word-break: break-word;
}

.roll-top {
  display: flex;
  align-items: baseline;
  gap: var(--coc-sp-2);
}

.roll-skill {
  font-weight: 600;
  color: var(--coc-text-strong);
}

.roll-diff {
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.roll-secret {
  padding: 0 6px;
  border-radius: var(--coc-radius-sm);
  background: var(--coc-keeper);
  color: #fff;
  font-size: var(--coc-fs-xs);
  line-height: 1.65;
}

.roll-level {
  margin-left: auto;
  font-weight: 600;
  color: var(--coc-roll-accent, var(--coc-text));
  white-space: nowrap;
}

.roll-detail {
  margin-top: 2px;
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-muted);
}

.roll-detail b {
  color: var(--coc-roll-accent, var(--coc-text-strong));
}

/* ==================== 检定下放请求卡（4.3+） ==================== */
.check-request {
  max-width: min(100%, 68ch);
  padding: 10px 12px;
  border: 1px solid rgba(230, 162, 60, 0.4);
  border-left: 4px solid var(--coc-brand);
  border-radius: var(--coc-radius);
  background: var(--coc-brand-soft);
  font-size: var(--coc-fs-sm);
}

.cr--mine {
  border-color: rgba(16, 185, 129, 0.5);
  border-left-color: var(--coc-success);
  background: var(--coc-success-soft);
}

.cr-head {
  margin-bottom: 4px;
  font-weight: 600;
  color: var(--coc-brand);
}

.cr--mine .cr-head {
  color: var(--coc-success);
}

.cr-diff {
  margin-left: 6px;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.cr-target {
  margin-left: 6px;
  font-family: var(--coc-font-mono);
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-dim);
}

.cr-reason {
  margin-bottom: var(--coc-sp-2);
  line-height: 1.6;
  color: var(--coc-text);
}

.cr-done,
.cr-wait {
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

/* ==================== 行动切口（4.2 四段叙事第 3 段） ==================== */
.ai-options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(100%, 68ch);
  margin-top: var(--coc-sp-2);
}

.ai-options-title {
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.ai-option {
  display: flex;
  align-items: flex-start;
  gap: var(--coc-sp-2);
  padding: 8px 12px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: var(--coc-card-2);
  color: var(--coc-text);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  line-height: 1.55;
  text-align: left;
  cursor: pointer;
  transition: border-color var(--coc-dur-fast) var(--coc-ease),
    color var(--coc-dur-fast) var(--coc-ease), box-shadow var(--coc-dur-fast) var(--coc-ease),
    transform var(--coc-dur-fast) var(--coc-ease);
}

.ai-option:hover {
  border-color: var(--coc-border-glow);
  color: var(--coc-accent);
  box-shadow: var(--coc-glow);
  transform: translateX(2px);
}

.ai-option-no {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  border: 1px solid var(--coc-border-glow);
  border-radius: var(--coc-radius-full);
  background: var(--coc-primary-soft);
  color: var(--coc-accent);
  font-size: var(--coc-fs-xs);
  line-height: 1;
}

.ai-option-text {
  min-width: 0;
}

.ai-free-hint {
  margin-top: 6px;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-dim);
}
</style>
