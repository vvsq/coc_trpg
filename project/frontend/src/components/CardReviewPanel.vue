<script setup lang="ts">
/**
 * 检卡面板 — KP 台（用户反馈 #5，2026-09-10）。
 *
 * KP 挂好模组后点「检查调查员卡」，AI 逐卡检查：
 * 技能是否配得上背景、随身物品是否与模组时代/设定冲突、数值是否越界、要素是否缺失。
 * **仅建议，不拦截开团**（用户决策）——结果只是 KP 侧的参考清单。
 *
 * 服务端同步调用一次轻任务模型（约 10~40s），故按钮给 loading 与耗时提示。
 */
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { reviewRoomCards, type CardReviewResult } from '@/api/agent'
import { useRoomStore } from '@/stores/room'

const room = useRoomStore()

const running = ref(false)
const result = ref<CardReviewResult | null>(null)
const elapsed = ref(0)
let tickTimer: number | undefined

const OVERALL_TAG: Record<string, 'success' | 'warning' | 'danger'> = {
  ok: 'success',
  suggestion: 'warning',
  major: 'danger',
}
const OVERALL_LABEL: Record<string, string> = {
  ok: '未发现问题',
  suggestion: '有建议',
  major: '明显不合理',
}

/** 有问题的卡排前面，方便 KP 先看要紧的 */
const ordered = computed(() => {
  const rows = result.value?.players ?? []
  const weight: Record<string, number> = { major: 0, suggestion: 1, ok: 2 }
  return [...rows].sort((a, b) => (weight[a.overall] ?? 3) - (weight[b.overall] ?? 3))
})

const troubleCount = computed(
  () => (result.value?.players ?? []).filter((p) => p.overall !== 'ok').length,
)

async function run(): Promise<void> {
  running.value = true
  result.value = null
  elapsed.value = 0
  const startedAt = Date.now()
  tickTimer = window.setInterval(() => {
    elapsed.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)
  try {
    result.value = await reviewRoomCards(room.roomId, room.playerName)
    if (result.value.note) ElMessage.info(result.value.note)
    else if (troubleCount.value === 0) ElMessage.success('所有调查员卡都没发现问题')
    else ElMessage.warning(`${troubleCount.value} 张卡有需要注意的地方`)
  } catch {
    // 503（模型不可用）/ 403 / 400 等由拦截器统一提示
  } finally {
    if (tickTimer !== undefined) window.clearInterval(tickTimer)
    tickTimer = undefined
    running.value = false
  }
}
</script>

<template>
  <div class="review-panel">
    <div class="acts">
      <el-button size="small" type="primary" :loading="running" @click="run">
        {{ result ? '重新检查' : '检查调查员卡' }}
      </el-button>
      <span v-if="running" class="elapsed">检查中… 已耗时 {{ elapsed }}s</span>
      <span v-else-if="result" class="done">
        用 {{ result.model }} 检查了 {{ result.players.length }} 张卡
      </span>
    </div>

    <p class="hint">
      逐卡检查技能与背景是否自洽、随身物品是否与模组时代冲突、数值是否越界；
      <strong>只给建议，不影响开团</strong>。
      <template v-if="result && !result.module_mounted">
        <br />当前未挂载模组，只做了卡内自洽与数值合规检查。
      </template>
    </p>

    <p v-if="result?.note" class="note">{{ result.note }}</p>

    <div v-for="p in ordered" :key="p.player_name" class="player">
      <div class="player-head">
        <span class="name">{{ p.player_name }}</span>
        <el-tag size="small" :type="OVERALL_TAG[p.overall]" effect="dark">
          {{ OVERALL_LABEL[p.overall] }}
        </el-tag>
      </div>

      <div v-for="(issue, i) in p.issues" :key="i" class="issue">
        <div class="issue-head">
          <el-tag size="small" :type="issue.severity === 'major' ? 'danger' : 'warning'" effect="plain">
            {{ issue.severity === 'major' ? '明显不合理' : '建议' }}
          </el-tag>
          <span class="issue-title">{{ issue.title }}</span>
        </div>
        <p v-if="issue.detail" class="issue-detail">{{ issue.detail }}</p>
        <p v-if="issue.advice" class="issue-advice">改法：{{ issue.advice }}</p>
      </div>

      <p v-if="!p.issues.length" class="ok-line">未发现问题。</p>
    </div>
  </div>
</template>

<style scoped>
.review-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 60px;
}

.acts {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.elapsed {
  font-size: 12px;
  color: #e6a23c;
}

.done {
  font-size: 12px;
  color: #909399;
}

.hint,
.note {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: #8da2c0;
}

.note {
  color: #e6a23c;
}

.player {
  padding: 8px 0 4px;
  border-top: 1px solid #2c3e50;
}

.player-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.player-head .name {
  font-size: 13px;
  font-weight: 600;
  color: #e8eaed;
}

.issue {
  margin: 0 0 8px;
  padding-left: 8px;
  border-left: 2px solid #2c3e50;
}

.issue-head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.issue-title {
  font-size: 12.5px;
  color: #e8eaed;
}

.issue-detail,
.issue-advice,
.ok-line {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: #909399;
}

.issue-advice {
  color: #67c23a;
}
</style>
