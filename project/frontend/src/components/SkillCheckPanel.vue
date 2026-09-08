<script setup lang="ts">
/**
 * 技能检定面板（3.2）— 3.3 从 RoomView 抽出，RoomView 与 KP 控制台共用。
 *
 * 技能源（3.3 返工：全技能可投）：
 *   - 绑卡：卡面技能按卡面值（基础+成长）；未上卡的标准技能按规则书基础值
 *     也可尝试（守秘人规则书 p.86：未受训 = 基础值，只是成功率低）
 *   - 无卡（KP 掷 NPC）：技能名 + 数值手输
 * 难度（常规/困难/极难）由守秘人按情境设定（规则书 p.71-72），因此仅 KP
 * 可见可选；玩家检定固定常规难度。只上报意图，结果由 roll_result 广播驱动（D5）。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { getCard, listSkills } from '@/api/cards'
import { diceCheck } from '@/api/dice'
import { useRoomStore } from '@/stores/room'
import type { Investigator, Skill } from '@/types/investigator'
import { skillValue } from '@/types/investigator'
import type { SkillRow } from '@/types/skill'

const props = defineProps<{
  /** KP 控制台传 true：暗骰默认勾选（勾选框本身仍仅 KP 可见） */
  defaultSecret?: boolean
}>()

const room = useRoomStore()

const myCard = ref<Investigator | null>(null)
const checkSkillIdx = ref<number | null>(null)
const checkDifficulty = ref<'standard' | 'hard' | 'extreme'>('standard')
const checkSecret = ref(props.defaultSecret ?? false)
const rolling = ref(false)
// 无卡模式（KP 暗骰 NPC 检定的入口）：技能名可选标准技能或自由输入，数值手输
const manualSkill = ref('')
const manualValue = ref<number | null>(null)
const allSkills = ref<SkillRow[]>([]) // 标准技能清单（全技能底表）

/** 可投选项的统一形态：渲染 label 与检定参数共用 */
interface RollOption {
  label: string
  name: string
  detail: string
  value: number
}

/** 卡面技能：按卡面值（基础+成长） */
const cardOpts = computed<RollOption[]>(() => {
  if (!myCard.value) return []
  return myCard.value.skills.map((s: Skill) => ({
    label: `${s.name}${s.detail ? `（${s.detail}）` : ''} ${skillValue(s)}`,
    name: s.name,
    detail: s.detail,
    value: skillValue(s),
  }))
})

/** 未上卡的标准技能：按规则书基础值可尝试（概率 > 0 的数值型基础值） */
const baseOpts = computed<RollOption[]>(() => {
  const known = new Set(cardOpts.value.map((o) => `${o.name}|${o.detail}`))
  return allSkills.value
    .filter((s) => (s.base ?? 0) > 0)
    .map((s) => ({
      label: `${s.name}${s.detail ? `（${s.detail}）` : ''} ${s.base}`,
      name: s.name,
      detail: s.detail,
      value: s.base as number,
    }))
    .filter((o) => !known.has(`${o.name}|${o.detail}`))
})

/** rollCheck 取值用：两组拼接后的完整选项表 */
const rollOptions = computed<RollOption[]>(() => [...cardOpts.value, ...baseOpts.value])

/** 无卡模式的建议名清单（同名多实例去重，仍可自由键入） */
const allSkillNames = computed<string[]>(() =>
  [...new Set(allSkills.value.map((s) => s.name))],
)

const canRoll = computed(() => {
  if (!room.connected) return false
  if (myCard.value) return checkSkillIdx.value !== null
  return manualSkill.value.trim() !== '' && manualValue.value !== null
})

/** 检定入口：只调 API 上报意图；结果展示完全由 roll_result 广播驱动（D5），不手动插入 */
async function rollCheck(): Promise<void> {
  if (!canRoll.value) return
  let skillName: string
  let detail = ''
  let value: number
  if (myCard.value && checkSkillIdx.value !== null) {
    const opt = rollOptions.value[checkSkillIdx.value]
    if (!opt) return
    skillName = opt.name
    detail = opt.detail
    value = opt.value
  } else {
    skillName = manualSkill.value.trim()
    value = manualValue.value as number
  }
  rolling.value = true
  try {
    await diceCheck({
      room_id: room.roomId,
      sender: room.playerName,
      skill_name: skillName,
      detail,
      difficulty: checkDifficulty.value,
      bonus: 0,
      penalty: 0,
      value,
      secret: checkSecret.value,
    })
  } catch {
    // 错误提示由 axios 拦截器统一弹出
  } finally {
    rolling.value = false
  }
}

onMounted(async () => {
  // 标准技能清单：全技能可投的底表 + 无卡模式（KP）下拉建议项
  try {
    allSkills.value = await listSkills()
  } catch {
    // 拉取失败不阻塞进房，绑卡仍有卡面技能，无卡模式输入框仍可自由键入
  }
})

// 卡随 room.cardId 异步就绪（子组件先于使用方的 enterRoom 挂载，不能只在
// onMounted 读一次），绑卡后切"下拉取卡面值"模式；卡就绪后默认选中第一个
// 卡面技能——避免"按钮禁用但不知道要先选技能"的困惑（4.1 验收反馈）
watch(
  () => room.cardId,
  async (cid) => {
    if (!cid || myCard.value) return
    try {
      myCard.value = await getCard(cid)
      if (myCard.value && myCard.value.skills.length > 0 && checkSkillIdx.value === null) {
        checkSkillIdx.value = 0
      }
    } catch {
      // 卡加载失败不阻塞面板（仍可手输技能），错误提示由拦截器统一弹
    }
  },
  { immediate: true },
)
</script>

<template>
  <!-- 技能来源：绑卡走分组下拉（卡面值 / 未上卡标准技能基础值）；无卡（KP）手输 -->
  <template v-if="myCard">
    <el-select
      v-model="checkSkillIdx"
      class="check-row"
      placeholder="选择技能"
      size="small"
      filterable
    >
      <el-option-group label="卡面技能">
        <el-option
          v-for="(o, i) in cardOpts"
          :key="`c${i}`"
          :label="o.label"
          :value="i"
        />
      </el-option-group>
      <el-option-group label="其他技能（基础值）">
        <el-option
          v-for="(o, i) in baseOpts"
          :key="`s${i}`"
          :label="o.label"
          :value="cardOpts.length + i"
        />
      </el-option-group>
    </el-select>
  </template>
  <template v-else>
    <el-select
      v-model="manualSkill"
      class="check-row"
      placeholder="选择或输入技能名"
      size="small"
      filterable
      allow-create
      default-first-option
    >
      <el-option v-for="n in allSkillNames" :key="n" :label="n" :value="n" />
    </el-select>
    <el-input-number
      v-model="manualValue"
      class="check-row manual-value"
      :min="1"
      :max="99"
      controls-position="right"
      placeholder="技能值"
      size="small"
    />
  </template>
  <!-- 难度与暗骰均为 KP 职权（难度由守秘人设定，规则书 p.71-72），玩家不显示 -->
  <div v-if="room.myRole === 'kp'" class="check-row check-inline">
    <el-select v-model="checkDifficulty" size="small" class="diff-select">
      <el-option label="常规" value="standard" />
      <el-option label="困难" value="hard" />
      <el-option label="极难" value="extreme" />
    </el-select>
    <el-checkbox
      v-model="checkSecret"
      size="small"
    >
      暗骰
    </el-checkbox>
  </div>
  <el-button
    type="primary"
    class="check-btn"
    :loading="rolling"
    :disabled="!canRoll"
    @click="rollCheck"
  >
    掷骰
  </el-button>
  <!-- 禁用原因提示：绑卡但未选技能 / 卡面无技能数据 -->
  <p v-if="myCard && myCard.skills.length === 0" class="check-hint">
    该卡没有技能数据，请联系 KP 换卡
  </p>
  <p v-else-if="myCard && checkSkillIdx === null" class="check-hint">先选择技能，再掷骰</p>
</template>

<style scoped>
.check-row {
  width: 100%;
  margin-bottom: 10px;
}

.check-inline {
  display: flex;
  align-items: center;
  gap: 8px;
}

.diff-select {
  flex: 1;
}

.manual-value {
  width: 100%;
}

.check-btn {
  width: 100%;
}

.check-hint {
  margin: 6px 0 0;
  font-size: 11px;
  color: #909399;
}
</style>
