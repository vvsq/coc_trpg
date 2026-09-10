<script setup lang="ts">
/**
 * 模组库列表 — 阶段 5。
 *
 * 上传剧本 → 解析为结构化骨架 → 在 KP 台挂载到房间。
 * 列表接口不返回原文与结构化结果，进详情页才拉全量（防大字段拖垮列表）。
 */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteModule, listModules } from '@/api/modules'
import ModuleUploadDialog from '@/components/ModuleUploadDialog.vue'
import { useRoomReturn } from '@/composables/useRoomReturn'
import {
  PARSE_STATUS_LABEL,
  PARSE_STATUS_TAG,
  SOURCE_TYPE_LABEL,
  formatTime,
  type ModuleMeta,
} from '@/types/module'

const router = useRouter()
// 顶栏返回：带来源房间时回 KP 控制台，否则回大厅（并负责离开工作区时拆连接）
const { returnLabel, goBack, carryQuery } = useRoomReturn()
const modules = ref<ModuleMeta[]>([])
const loading = ref(true)
const uploadVisible = ref(false)

async function refresh(): Promise<void> {
  loading.value = true
  try {
    modules.value = await listModules()
  } finally {
    loading.value = false
  }
}

onMounted(refresh)

function openDetail(id: number): void {
  router.push({ name: 'module-detail', params: { id: String(id) }, query: carryQuery() })
}

function onUploaded(meta: ModuleMeta): void {
  refresh()
  // 上传完直接进详情页：下一步就是选模型解析，少点一次
  openDetail(meta.id)
}

async function onDelete(row: ModuleMeta): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除模组「${row.name}」？挂载它的房间会自动回退到默认骨架。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  await deleteModule(row.id)
  ElMessage.success('已删除')
  await refresh()
}
</script>

<template>
  <main class="module-list">
    <div class="head">
      <div>
        <h2>模组库</h2>
        <p class="sub">上传剧本 → 解析为结构化骨架 → 在 KP 台挂载</p>
      </div>
      <div class="head-actions">
        <el-button @click="goBack">{{ returnLabel }}</el-button>
        <el-button type="primary" @click="uploadVisible = true">上传模组</el-button>
      </div>
    </div>

    <div v-loading="loading" class="grid">
      <div
        v-for="row in modules"
        :key="row.id"
        class="mod-card"
        @click="openDetail(row.id)"
      >
        <div class="mod-head">
          <span class="mod-name" :title="row.name">{{ row.name }}</span>
          <el-tag size="small" :type="PARSE_STATUS_TAG[row.parse_status]" effect="dark">
            {{ PARSE_STATUS_LABEL[row.parse_status] }}
          </el-tag>
        </div>
        <div class="mod-tags">
          <span class="src-tag">{{ SOURCE_TYPE_LABEL[row.source_type] }}</span>
          <span class="mod-meta">{{ row.char_count }} 字</span>
        </div>
        <p class="mod-foot">
          <span>{{ row.parse_model || '未指定模型' }}</span>
          <span>{{ formatTime(row.parsed_at ?? row.created_at) }}</span>
        </p>
        <div class="mod-actions" @click.stop>
          <el-button size="small" text type="primary" @click="router.push({ name: 'module-detail', params: { id: String(row.id) } })">
            查看
          </el-button>
          <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
        </div>
      </div>
    </div>

    <el-empty
      v-if="!loading && modules.length === 0"
      description="还没有模组，先上传一个剧本吧"
    >
      <el-button type="primary" @click="uploadVisible = true">上传模组</el-button>
    </el-empty>

    <ModuleUploadDialog v-model="uploadVisible" @uploaded="onUploaded" />
  </main>
</template>

<style scoped>
.module-list {
  min-height: calc(100vh - 54px);
  padding: 32px 32px 56px;
  background:
    radial-gradient(ellipse at 15% 0%, rgba(44, 62, 80, 0.5), transparent 55%),
    #1b2431;
  color: #e8eaed;
}

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  max-width: 1080px;
  margin: 0 auto 22px;
}

.head h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 1px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.sub {
  margin: 6px 0 0;
  font-size: 13px;
  color: #909399;
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  max-width: 1080px;
  min-height: 120px;
  margin: 0 auto;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 620px) {
  .grid {
    grid-template-columns: 1fr;
  }
}

.mod-card {
  padding: 16px;
  border: 1px solid #2c3e50;
  border-radius: 10px;
  background: #222d3d;
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
}

.mod-card:hover {
  transform: translateY(-2px);
  border-color: #e6a23c;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.35);
}

.mod-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mod-name {
  font-size: 15px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mod-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
}

.src-tag {
  padding: 1px 7px;
  font-size: 11px;
  color: #e6a23c;
  border: 1px solid #6b5324;
  border-radius: 4px;
}

.mod-meta {
  font-size: 12px;
  color: #909399;
}

.mod-foot {
  display: flex;
  justify-content: space-between;
  margin: 12px 0 0;
  font-size: 12px;
  color: #909399;
}

.mod-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 8px;
}

/* Element Plus 暗色适配：卡片内的浅色表格/折叠面板统一压暗 */
:deep(.el-empty__description p) {
  color: #909399;
}
</style>
