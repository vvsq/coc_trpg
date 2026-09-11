<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getCard, listStandardWeapons, updateCard, type StandardWeapon } from '@/api/cards'
import { eraLabel, type Background, type Era, type Investigator, type Skill, type Weapon } from '@/types/investigator'

const route = useRoute()
const router = useRouter()

const card = ref<Investigator | null>(null)
const loading = ref(true)

const attrLabels: Record<string, string> = {
  STR: '力量', CON: '体质', SIZ: '体型', DEX: '敏捷', APP: '外貌',
  INT: '智力', POW: '意志', EDU: '教育', LUK: '幸运',
}

function skillLabel(s: Skill): string {
  return s.detail ? `${s.name}（${s.detail}）` : s.name
}

// ---------- 背景八要素（2.5③：此前整卡不渲染背景，编辑与展示一并补齐） ----------
const backgroundFields: { key: keyof Background; label: string }[] = [
  { key: 'personal_description', label: '个人描述' },
  { key: 'ideology_beliefs', label: '思想信念' },
  { key: 'significant_people', label: '重要之人' },
  { key: 'meaningful_location', label: '意义非凡之地' },
  { key: 'treasured_possession', label: '宝贵之物' },
  { key: 'traits', label: '特质' },
  { key: 'scars_injuries', label: '伤疤与恐惧' },
  { key: 'cash_assets', label: '资产' },
]

onMounted(async () => {
  try {
    card.value = await getCard(route.params.id as string)
  } finally {
    loading.value = false
  }
})

// ---------- 卡面编辑对话框（PATCH /cards/{id}） ----------
const editVisible = ref(false)
const saving = ref(false)

const editForm = reactive({
  background: {} as Background,
  possessions: '',
  weapons: [] as Weapon[],
})

async function openEdit(): Promise<void> {
  if (!card.value) return
  editForm.background = { ...card.value.background }
  editForm.possessions = card.value.possessions ?? ''
  editForm.weapons = card.value.weapons.map((w) => ({ ...w }))
  editVisible.value = true
  if (standardWeapons.value.length === 0) {
    standardWeapons.value = await listStandardWeapons()
  }
}

async function saveEdit(): Promise<void> {
  if (!card.value?.id) return
  saving.value = true
  try {
    card.value = await updateCard(card.value.id, {
      background: { ...editForm.background },
      possessions: editForm.possessions,
      weapons: [...editForm.weapons],
    })
    ElMessage.success('卡面已保存')
    editVisible.value = false
  } finally {
    saving.value = false
  }
}

// ---------- 编辑：武器管理（标准表选 + 自定义） ----------
const standardWeapons = ref<StandardWeapon[]>([])
const showAllWeapons = ref(false)
const pickedWeaponId = ref<number | null>(null)

/** 标准表的常见时代列与卡面时代匹配（"1920s、现代"两边都算；"罕见"仅在显示全部时出现） */
function eraMatches(weaponEra: string, era: Era): boolean {
  return era === 'classical' ? weaponEra.includes('1920s') : weaponEra.includes('现代')
}

const eraFilteredWeapons = computed<StandardWeapon[]>(() => {
  const era = card.value?.era
  if (!era || showAllWeapons.value) return standardWeapons.value
  return standardWeapons.value.filter((w) => eraMatches(w.era, era))
})

/** 标准表行 → 卡面武器：故障值"——"默认 100，装弹量非数字串原样保留 */
function fromStandard(w: StandardWeapon): Weapon {
  const rawAmmo = String(w.ammo)
  return {
    name: w.name,
    skill_name: w.skill_name,
    damage: w.damage,
    rng: w.rng,
    attacks: w.attacks || '1',
    ammo: /^\d+$/.test(rawAmmo) ? Number(rawAmmo) : rawAmmo === '——' || rawAmmo === 'N/A' ? 0 : rawAmmo,
    malfunction: w.malfunction ?? 100,
  }
}

function addStandardWeapon(): void {
  const w = eraFilteredWeapons.value.find((x) => x.id === pickedWeaponId.value)
  if (!w) {
    ElMessage.warning('请先选择一件武器')
    return
  }
  editForm.weapons.push(fromStandard(w))
  pickedWeaponId.value = null
}

// 自定义武器小表单
const customForm = reactive({
  name: '', skill_name: '斗殴', damage: '1D4', rng: '接触', attacks: '1', ammo: 0, malfunction: 100,
})

function addCustomWeapon(): void {
  if (!customForm.name.trim()) {
    ElMessage.warning('请填写武器名称')
    return
  }
  editForm.weapons.push({
    name: customForm.name.trim(),
    skill_name: customForm.skill_name,
    damage: customForm.damage,
    rng: customForm.rng,
    attacks: customForm.attacks,
    ammo: customForm.ammo,
    malfunction: customForm.malfunction,
  })
  customForm.name = ''
}

function removeWeapon(index: number): void {
  editForm.weapons.splice(index, 1)
}
</script>

<template>
  <div class="card-detail" v-loading="loading">
    <el-card v-if="card">
      <template #header>
        <div class="header">
          <h2>{{ card.name }} <span class="sub">({{ card.occupation }})</span></h2>
          <div>
            <el-button type="primary" @click="openEdit">编辑卡面</el-button>
            <el-button @click="router.push('/cards')">返回列表</el-button>
          </div>
        </div>
      </template>

      <!-- 基本信息 -->
      <el-descriptions title="基本信息" :column="4" border>
        <el-descriptions-item label="性别">{{ card.gender || '—' }}</el-descriptions-item>
        <el-descriptions-item label="年龄">{{ card.age }}</el-descriptions-item>
        <el-descriptions-item label="时代">{{ eraLabel(card.era) }}</el-descriptions-item>
        <el-descriptions-item label="职业">{{ card.occupation }}</el-descriptions-item>
        <el-descriptions-item label="信用评级">{{ card.credit }}</el-descriptions-item>
      </el-descriptions>

      <!-- 属性 -->
      <el-descriptions title="属性" :column="5" border class="section">
        <el-descriptions-item v-for="(label, k) in attrLabels" :key="k" :label="label">
          {{ card.attributes[k as keyof typeof card.attributes] }}
        </el-descriptions-item>
      </el-descriptions>

      <!-- 衍生值 -->
      <el-descriptions title="衍生值" :column="4" border class="section">
        <el-descriptions-item label="HP">{{ card.derived.HP }}</el-descriptions-item>
        <el-descriptions-item label="MP">{{ card.derived.MP }}</el-descriptions-item>
        <el-descriptions-item label="SAN">{{ card.derived.SAN }}</el-descriptions-item>
        <el-descriptions-item label="伤害加值">{{ card.derived.DB }}</el-descriptions-item>
        <el-descriptions-item label="体格">{{ card.derived.build }}</el-descriptions-item>
        <el-descriptions-item label="移动力">{{ card.derived.MOV }}</el-descriptions-item>
      </el-descriptions>

      <!-- 技能 -->
      <el-table :data="card.skills" border class="section" v-if="card.skills.length">
        <template #append> </template>
        <el-table-column label="技能名称" min-width="180">
          <template #default="{ row }">{{ skillLabel(row) }}</template>
        </el-table-column>
        <el-table-column prop="base" label="基础值" width="80" />
        <el-table-column label="成长值" width="80">
          <template #default="{ row }">{{ row.increment }}</template>
        </el-table-column>
        <el-table-column label="当前值" width="80">
          <template #default="{ row }">{{ row.base + row.increment }}</template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无技能" />

      <!-- 背景八要素（2.5③） -->
      <el-descriptions title="背景八要素" :column="2" border class="section">
        <el-descriptions-item v-for="f in backgroundFields" :key="f.key" :label="f.label">
          <span class="pre-wrap">{{ card.background[f.key] || '—' }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 随身物品（2.5③） -->
      <div class="section">
        <h3>随身物品</h3>
        <div class="possessions pre-wrap">{{ card.possessions || '—' }}</div>
      </div>

      <!-- 武器（2.5③） -->
      <div class="section">
        <h3>武器</h3>
        <el-table v-if="card.weapons.length" :data="card.weapons" border>
          <el-table-column prop="name" label="武器名称" min-width="150" />
          <el-table-column prop="skill_name" label="关联技能" width="110" />
          <el-table-column prop="damage" label="伤害" min-width="100" />
          <el-table-column prop="rng" label="射程" width="90" />
          <el-table-column prop="attacks" label="每轮" width="90" />
          <el-table-column prop="ammo" label="装弹量" width="90" />
          <el-table-column prop="malfunction" label="故障值" width="80" />
        </el-table>
        <el-empty v-else description="暂无武器" :image-size="60" />
      </div>
    </el-card>

    <el-empty v-else-if="!loading" description="角色卡不存在或已被删除">
      <el-button @click="router.push('/cards')">返回列表</el-button>
    </el-empty>

    <!-- 编辑对话框：背景 / 随身物品 / 武器 -->
    <el-dialog v-model="editVisible" title="编辑卡面" width="760px" top="6vh">
      <el-tabs>
        <el-tab-pane label="背景八要素">
          <el-form label-width="110px">
            <el-form-item v-for="f in backgroundFields" :key="f.key" :label="f.label">
              <el-input
                v-model="editForm.background[f.key]"
                type="textarea"
                :rows="2"
                :placeholder="f.label"
              />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="随身物品">
          <el-input
            v-model="editForm.possessions"
            type="textarea"
            :rows="8"
            placeholder="一行一件随身物品，游玩时可交由 KP 或 AI 审核"
          />
        </el-tab-pane>

        <el-tab-pane label="武器">
          <el-table :data="editForm.weapons" border size="small" empty-text="还没有武器">
            <el-table-column prop="name" label="武器名称" min-width="140" />
            <el-table-column prop="skill_name" label="技能" width="90" />
            <el-table-column prop="damage" label="伤害" min-width="90" />
            <el-table-column prop="rng" label="射程" width="80" />
            <el-table-column prop="ammo" label="装弹" width="80" />
            <el-table-column prop="malfunction" label="故障" width="60" />
            <el-table-column label="操作" width="70">
              <template #default="{ $index }">
                <el-button link type="danger" size="small" @click="removeWeapon($index)">
                  删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>

          <div class="weapon-add">
            <div class="weapon-add-row">
              <el-select
                v-model="pickedWeaponId"
                filterable
                placeholder="从标准武器表选择"
                class="weapon-select"
              >
                <el-option
                  v-for="w in eraFilteredWeapons"
                  :key="w.id"
                  :label="`${w.name}（${w.damage}）`"
                  :value="w.id"
                />
              </el-select>
              <el-checkbox v-model="showAllWeapons">显示全部（含不合时代/罕见）</el-checkbox>
              <el-button type="primary" plain @click="addStandardWeapon">添加标准武器</el-button>
            </div>
            <div class="weapon-add-row">
              <el-input v-model="customForm.name" placeholder="自定义武器名" class="weapon-name" />
              <el-input v-model="customForm.skill_name" placeholder="技能" class="weapon-mini" />
              <el-input v-model="customForm.damage" placeholder="伤害" class="weapon-mini" />
              <el-input v-model="customForm.rng" placeholder="射程" class="weapon-mini" />
              <el-button @click="addCustomWeapon">添加自定义武器</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.card-detail {
  max-width: 960px;
  margin: 20px auto;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.header h2 {
  margin: 0;
}
.header .sub {
  font-size: 14px;
  font-weight: normal;
  color: var(--coc-text-muted);
}
.section {
  margin-top: 24px;
}
.section h3 {
  margin: 0 0 10px;
  font-size: 15px;
  color: var(--coc-text-strong);
}
.pre-wrap {
  white-space: pre-wrap;
  word-break: break-word;
}
.possessions {
  padding: 10px 14px;
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-sm);
  background: var(--coc-card-2);
  color: var(--coc-text);
  font-size: 14px;
  line-height: 1.7;
}
.weapon-add {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.weapon-add-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.weapon-select {
  width: 320px;
}
.weapon-name {
  width: 200px;
}
.weapon-mini {
  width: 90px;
}
</style>
