<script setup lang="ts">
/**
 * 角色卡列表 — 阶段 2；6.2⑨ 补三态（骨架 / 空 / 错误+重试）并统一暗色观感。
 *
 * 逻辑零改动：列表 / 新建 / 查看 / 删除（confirm + 刷新）与原先一致。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCards, deleteCard } from '@/api/cards'
import { eraLabel } from '@/types/investigator'
import CocIcon from '@/components/common/CocIcon.vue'
import StateView from '@/components/common/StateView.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'

const router = useRouter()
const cards = ref<Awaited<ReturnType<typeof listCards>>>([])
const loading = ref(true)
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    cards.value = await listCards()
  } catch {
    // 拦截器已提示一次，页面上给可重试的错误态
    error.value = '角色卡列表加载失败，请确认后端服务仍在运行'
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function onDelete(row: { id: string; name: string }) {
  try {
    await ElMessageBox.confirm(
      `确定删除「${row.name}」的角色卡？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  await deleteCard(row.id)
  ElMessage.success('已删除')
  await load()
}
</script>

<template>
  <main class="card-list coc-page">
    <header class="page-head">
      <div>
        <h2 class="page-title">
          <CocIcon name="card" :size="20" />
          角色卡列表
        </h2>
        <p class="page-sub">按 CoC 七版规则建卡，房间内可直接检定与改状态</p>
      </div>
      <el-button type="primary" @click="router.push('/cards/new')">
        <CocIcon name="sparkles" :size="14" />
        新建角色卡
      </el-button>
    </header>

    <SkeletonBlock v-if="loading" variant="row" :count="3" :rows="1" />

    <StateView v-else-if="error" state="error" title="加载失败" :description="error">
      <el-button size="small" type="primary" plain @click="load">重试</el-button>
    </StateView>

    <StateView
      v-else-if="cards.length === 0"
      state="empty"
      title="还没有角色卡"
      description="点右上角「新建角色卡」走一遍三步建卡向导"
    >
      <el-button size="small" type="primary" @click="router.push('/cards/new')">开始建卡</el-button>
    </StateView>

    <el-table v-else :data="cards" border class="card-table">
      <el-table-column prop="name" label="姓名" />
      <el-table-column prop="occupation" label="职业" />
      <el-table-column prop="era" label="时代" width="140">
        <template #default="{ row }">{{ eraLabel(row.era) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="170">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/cards/${row.id}`)">查看</el-button>
          <el-button size="small" type="danger" @click="onDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </main>
</template>

<style scoped>
.card-list {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-4);
  max-width: 1040px;
  margin: 0 auto;
  padding: var(--coc-sp-6) var(--coc-sp-5) var(--coc-sp-8);
}

.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--coc-sp-4);
  padding-bottom: var(--coc-sp-3);
  border-bottom: 1px solid var(--coc-border);
}

.page-title {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  color: var(--coc-text-strong);
}

.page-title .coc-icon-svg {
  color: var(--coc-accent);
}

.page-sub {
  margin-top: 6px;
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-muted);
}

/* 表格观感走 global.css 的 EP 变量映射，这里只补圆角与行高 */
.card-table {
  width: 100%;
}

.card-table :deep(.el-table) {
  border-radius: var(--coc-radius-lg);
}
</style>
