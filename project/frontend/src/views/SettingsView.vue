<script setup lang="ts">
/**
 * 系统设置页（/settings）— 阶段 6.2④（新增模块，原项目没有）。
 *
 * 三块内容（用户 2026-09-11 确认）：
 *   ① 外观：背景图（预设 + 自选上传）、氛围/动效/发光/字号 —— 本机生效，见 SettingsPanel；
 *   ② 音效：骰子与消息提示音总开关（WebAudio 合成，零音频文件）；
 *   ③ AI 配置：把原先只在大厅出现的 LLM 设置收编为正式入口（同一组件，行为不变）。
 *
 * 路由归属：「房间工作区」成员（router ROOM_SCOPE_ROUTE_NAMES 含 settings），
 * 从房间进来不断连接；离开设置页回大厅时才由 useRoomReturn 收尾。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoomReturn } from '@/composables/useRoomReturn'
import { useRoomStore } from '@/stores/room'
import { useSettingsStore } from '@/stores/settings'
import { getLlmStatus, type LlmStatus } from '@/api/agent'
import SettingsPanel from '@/components/SettingsPanel.vue'
import LlmSettingsDialog from '@/components/LlmSettingsDialog.vue'
import CocIcon from '@/components/common/CocIcon.vue'

const room = useRoomStore()
const { settings, patch } = useSettingsStore()
const { returnLabel, goBack } = useRoomReturn()

const llmVisible = ref(false)
const llm = ref<LlmStatus | null>(null)

async function loadLlm(): Promise<void> {
  try {
    llm.value = await getLlmStatus()
  } catch {
    // 拦截器已提示；卡片退化为"未知"
  }
}

onMounted(loadLlm)
// 关闭设置弹窗后刷新回显（供应商/模型可能已改）
watch(llmVisible, (open) => {
  if (!open) void loadLlm()
})

/** 当前模式说明（只读展示，切换入口在顶栏） */
const modeText = computed(() => {
  if (!room.roomId) return '未在房间中'
  return room.agentMode === 'auto' ? '全自动主持' : room.agentMode === 'collab' ? '协同建议' : '人工主持'
})
</script>

<template>
  <main class="settings-page coc-page">
    <header class="page-head">
      <div class="head-text">
        <h2 class="page-title">
          <CocIcon name="gear" :size="20" />
          系统设置
        </h2>
        <p class="page-sub">
          外观与音效保存在本机浏览器，不影响同房间其他玩家；AI 配置为全局共享。
        </p>
      </div>
      <div class="head-actions">
        <span v-if="room.roomId" class="coc-chip">房间 {{ room.roomId }} · {{ modeText }}</span>
        <button type="button" class="ghost-btn" @click="goBack">
          <CocIcon name="chevronRight" :size="14" />
          {{ returnLabel }}
        </button>
      </div>
    </header>

    <div class="content">
      <!-- ① 外观 -->
      <SettingsPanel />

      <!-- ② 音效 -->
      <section class="block">
        <header class="block-head">
          <h3 class="block-title">
            <CocIcon :name="settings.sound ? 'volume' : 'volume-off'" :size="16" />
            音效
          </h3>
          <span class="coc-chip">{{ settings.sound ? '已开启' : '已关闭' }}</span>
        </header>
        <div class="opt-row">
          <div class="opt-text">
            <p class="opt-name">骰子与消息提示音</p>
            <p class="opt-desc">
              骰子落地与收到新剧情时播放合成短音（浏览器实时合成，不加载音频文件）
            </p>
          </div>
          <el-switch
            :model-value="settings.sound"
            @update:model-value="patch({ sound: Boolean($event) })"
          />
        </div>
        <p class="coc-hint">浏览器要求先在页面上有一次点击/输入后才会出声，属正常限制。</p>
      </section>

      <!-- ③ AI 配置（并入原大厅入口） -->
      <section class="block">
        <header class="block-head">
          <h3 class="block-title">
            <CocIcon name="sparkles" :size="16" />
            AI 主持配置
          </h3>
          <el-tag size="small" :type="llm?.enabled ? 'success' : 'info'" effect="dark">
            {{ llm?.mock_mode ? '演示模式' : llm?.enabled ? '已配置' : '未配置' }}
          </el-tag>
        </header>

        <dl class="kv">
          <div class="kv-row">
            <dt>供应商</dt>
            <dd>{{ llm?.provider || '—' }}</dd>
          </div>
          <div class="kv-row">
            <dt>Base URL</dt>
            <dd class="mono">{{ llm?.base_url || '—' }}</dd>
          </div>
          <div class="kv-row">
            <dt>主模型</dt>
            <dd>{{ llm?.model || '—' }}</dd>
          </div>
          <div class="kv-row">
            <dt>轻任务模型</dt>
            <dd>{{ llm?.light_model || '（跟随主模型）' }}</dd>
          </div>
          <div class="kv-row">
            <dt>API Key</dt>
            <dd class="mono">{{ llm?.api_key_masked || '—' }}</dd>
          </div>
        </dl>

        <button type="button" class="primary-btn" @click="llmVisible = true">
          <CocIcon name="gear" :size="15" />
          打开详细设置（模型探测 / 连通测试 / Token 总账）
        </button>
      </section>
    </div>

    <LlmSettingsDialog
      v-model:visible="llmVisible"
      :room-id="room.roomId"
      :kp-name="room.playerName"
    />
  </main>
</template>

<style scoped>
.settings-page {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-5);
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--coc-sp-6) var(--coc-sp-5) var(--coc-sp-8);
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--coc-sp-4);
  padding-bottom: var(--coc-sp-4);
  border-bottom: 1px solid var(--coc-border);
}

.page-title {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin: 0;
  font-size: var(--coc-fs-xl);
  color: var(--coc-text-strong);
}

.page-title .coc-icon-svg {
  color: var(--coc-accent);
}

.page-sub {
  margin: 6px 0 0;
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-muted);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-3);
  flex-shrink: 0;
}

.content {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-5);
}

.block {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-3);
  padding: var(--coc-sp-4);
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-lg);
  background: rgba(22, 32, 50, 0.62);
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-2);
}

.block-title {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin: 0;
  font-size: var(--coc-fs-base);
  color: var(--coc-text-strong);
}

.block-title .coc-icon-svg {
  color: var(--coc-accent);
}

.opt-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-4);
}

.opt-name {
  margin: 0;
  font-size: var(--coc-fs-base);
  color: var(--coc-text);
}

.opt-desc {
  margin: 2px 0 0;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.kv {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--coc-sp-2) var(--coc-sp-4);
  margin: 0;
}

.kv-row {
  display: flex;
  align-items: baseline;
  gap: var(--coc-sp-2);
  min-width: 0;
}

.kv-row dt {
  flex-shrink: 0;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.kv-row dd {
  margin: 0;
  font-size: var(--coc-fs-sm);
  color: var(--coc-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: var(--coc-font-mono);
}

.primary-btn {
  align-self: flex-start;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  border: 1px solid var(--coc-border-glow);
  border-radius: var(--coc-radius);
  background: linear-gradient(180deg, rgba(34, 211, 238, 0.2), rgba(14, 165, 233, 0.12));
  color: var(--coc-accent);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  cursor: pointer;
  transition: box-shadow var(--coc-dur-fast) var(--coc-ease), transform var(--coc-dur-fast) var(--coc-ease);
}

.primary-btn:hover {
  box-shadow: var(--coc-glow);
  transform: translateY(-1px);
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 7px 14px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius);
  background: transparent;
  color: var(--coc-text-muted);
  font-family: inherit;
  font-size: var(--coc-fs-sm);
  cursor: pointer;
  transition: color var(--coc-dur-fast) var(--coc-ease), border-color var(--coc-dur-fast) var(--coc-ease);
}

.ghost-btn:hover {
  color: var(--coc-accent);
  border-color: var(--coc-border-glow);
}

@media (max-width: 720px) {
  .page-head {
    flex-direction: column;
  }
}
</style>
