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
import CocIcon from '@/components/common/CocIcon.vue'
import StateView from '@/components/common/StateView.vue'
import SkeletonBlock from '@/components/common/SkeletonBlock.vue'
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
const error = ref('')
const uploadVisible = ref(false)

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    modules.value = await listModules()
  } catch {
    // 拦截器已提示一次，页面上给可重试的错误态（6.2⑨）
    error.value = '模组列表加载失败，请确认后端服务仍在运行'
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
        <h2 class="head-title">
          <CocIcon name="book" :size="20" />
          模组库
        </h2>
        <p class="sub">上传剧本 → 解析为结构化骨架 → 在 KP 台挂载</p>
      </div>
      <div class="head-actions">
        <el-button @click="goBack">{{ returnLabel }}</el-button>
        <el-button type="primary" @click="uploadVisible = true">
          <CocIcon name="upload" :size="14" />
          上传模组
        </el-button>
      </div>
    </div>

    <SkeletonBlock v-if="loading" variant="card" :count="3" :rows="2" class="grid-skeleton" />

    <StateView v-else-if="error" state="error" title="加载失败" :description="error">
      <el-button size="small" type="primary" plain @click="refresh">重试</el-button>
    </StateView>

    <StateView
      v-else-if="modules.length === 0"
      state="empty"
      title="还没有模组"
      description="上传一份 TXT / PDF / DOCX 剧本，解析成结构化骨架后就能挂到房间"
    >
      <el-button type="primary" @click="uploadVisible = true">上传模组</el-button>
    </StateView>

    <div v-else class="grid">
      <div
        v-for="row in modules"
        :key="row.id"
        class="mod-card coc-glow-hover"
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

    <ModuleUploadDialog v-model="uploadVisible" @uploaded="onUploaded" />
  </main>
</template>

<style scoped>
.module-list {
  display: flex;
  flex-direction: column;
  gap: var(--coc-sp-3);
  min-height: 100%;
  padding: var(--coc-sp-6) var(--coc-sp-5) var(--coc-sp-10);
  color: var(--coc-text);
}

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--coc-sp-4);
  max-width: 1080px;
  width: 100%;
  margin: 0 auto var(--coc-sp-2);
  padding-bottom: var(--coc-sp-3);
  border-bottom: 1px solid var(--coc-border);
}

.head-title {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  color: var(--coc-text-strong);
}

.head-title .coc-icon-svg {
  color: var(--coc-accent);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
}

.sub {
  margin-top: 6px;
  font-size: var(--coc-fs-sm);
  color: var(--coc-text-muted);
}

.grid,
.grid-skeleton {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--coc-sp-4);
  max-width: 1080px;
  width: 100%;
  margin: 0 auto;
}

.grid-skeleton {
  display: grid;
}

@media (max-width: 900px) {
  .grid,
  .grid-skeleton {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 620px) {
  .grid,
  .grid-skeleton {
    grid-template-columns: 1fr;
  }
}

.mod-card {
  display: flex;
  flex-direction: column;
  padding: var(--coc-sp-4);
  border: 1px solid var(--coc-border);
  border-radius: var(--coc-radius-lg);
  background: rgba(22, 32, 50, 0.72);
  cursor: pointer;
}

.mod-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--coc-sp-2);
}

.mod-name {
  font-size: var(--coc-fs-md);
  font-weight: 600;
  color: var(--coc-text-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mod-tags {
  display: flex;
  align-items: center;
  gap: var(--coc-sp-2);
  margin-top: var(--coc-sp-3);
}

.src-tag {
  padding: 1px 7px;
  border: 1px solid rgba(230, 162, 60, 0.5);
  border-radius: var(--coc-radius-sm);
  background: var(--coc-brand-soft);
  color: var(--coc-brand);
  font-size: var(--coc-fs-xs);
}

.mod-meta {
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.mod-foot {
  display: flex;
  justify-content: space-between;
  gap: var(--coc-sp-2);
  margin: var(--coc-sp-3) 0 0;
  font-size: var(--coc-fs-xs);
  color: var(--coc-text-muted);
}

.mod-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
  margin-top: var(--coc-sp-2);
  padding-top: var(--coc-sp-2);
  border-top: 1px solid var(--coc-border-soft);
}
</style>
