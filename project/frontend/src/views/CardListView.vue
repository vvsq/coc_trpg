<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listCards, deleteCard } from '@/api/cards'
import { eraLabel } from '@/types/investigator'

const router = useRouter()
const cards = ref<Awaited<ReturnType<typeof listCards>>>([])
const loading = ref(true)

onMounted(async () => {
  try {
    cards.value = await listCards()
  } finally {
    loading.value = false
  }
})

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
  cards.value = await listCards()
}
</script>

<template>
  <div class="card-list">
    <div class="header">
      <h2>角色卡列表</h2>
      <el-button type="primary" @click="router.push('/cards/new')">新建角色卡</el-button>
    </div>

    <el-table v-loading="loading" :data="cards" border>
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

    <el-empty v-if="!loading && cards.length === 0" description="还没有角色卡，点右上角新建一张" />
  </div>
</template>

<style scoped>
.card-list {
  max-width: 960px;
  margin: 32px auto;
  padding: 24px;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.header h2 {
  margin: 0;
  font-size: 22px;
  color: #1f2937;
  font-weight: 600;
}

/* 深度修改element-plus表格样式，scoped需要:deep() */
:deep(.el-table) {
  border-radius: 12px;
  overflow: hidden;
}
:deep(.el-table th) {
  background-color: #f7f8fa;
  color: #4e5969;
  font-weight: 600;
}
:deep(.el-table .el-table__row:hover > td) {
  background-color: #f2f7ff !important;
}
:deep(.el-table .el-table__row:nth-child(even) > td) {
  background-color: #fbfcfe;
}
:deep(.el-table__cell) {
  padding: 14px 16px;
}

/* 空状态间距 */
:deep(.el-empty) {
  margin: 40px 0 20px;
}

</style>
