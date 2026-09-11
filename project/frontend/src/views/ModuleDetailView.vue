<script setup lang="ts">
/**
 * 模组详情 — 阶段 5。
 *
 * 三个动作都在这一页：改名、手动解析（选模型）、校对结构化结果。
 * 数据来源全部是服务端返回值（保存/解析后就地刷新），前端不做乐观更新。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getModule, updateModule } from '@/api/modules'
import ModuleParsePanel from '@/components/ModuleParsePanel.vue'
import ModuleResultEditor from '@/components/ModuleResultEditor.vue'
import { useRoomReturn } from '@/composables/useRoomReturn'
import {
  EMPTY_PARSED,
  PARSE_STATUS_LABEL,
  PARSE_STATUS_TAG,
  SOURCE_TYPE_LABEL,
  formatTime,
  type ModuleDetail,
  type ModuleParsed,
} from '@/types/module'

const route = useRoute()
const router = useRouter()
// 顶栏返回：带来源房间时回 KP 控制台，否则回大厅（并负责离开工作区时拆连接）
const { returnLabel, goBack, carryQuery } = useRoomReturn()

const moduleId = Number(route.params.id)
const detail = ref<ModuleDetail | null>(null)
const loading = ref(true)
const tab = ref('parsed')
const keyword = ref('')
const renaming = ref(false)
const nameDraft = ref('')

const parsed = computed<ModuleParsed>(() => detail.value?.parsed ?? EMPTY_PARSED)

onMounted(async () => {
  try {
    detail.value = await getModule(moduleId)
    nameDraft.value = detail.value.name
  } finally {
    loading.value = false
  }
})

function onRefresh(fresh: ModuleDetail): void {
  detail.value = fresh
}

async function saveParsed(patch: Partial<ModuleParsed>): Promise<void> {
  const fresh = await updateModule(moduleId, { parsed: patch })
  detail.value = fresh
}

async function saveName(): Promise<void> {
  const name = nameDraft.value.trim()
  if (!name) {
    ElMessage.warning('模组名不能为空')
    return
  }
  const fresh = await updateModule(moduleId, { name })
  detail.value = fresh
  renaming.value = false
  ElMessage.success('已保存')
}

/** 原文检索高亮：先转义再套 <mark>，避免模组文本里的 < > 破坏渲染 */
const renderedText = computed<string>(() => {
  const text = escapeHtml(detail.value?.raw_text ?? '')
  const keywordText = keyword.value.trim()
  if (!keywordText) return text
  const pattern = escapeHtml(keywordText).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return text.replace(new RegExp(pattern, 'gi'), (hit) => `<mark>${hit}</mark>`)
})

function escapeHtml(raw: string): string {
  return raw.replace(/[&<>"]/g, (char) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[char] as string
  ))
}
</script>

<template>
  <main v-loading="loading" class="module-detail">
    <template v-if="detail">
      <div class="topbar">
        <el-button
          text
          class="back"
          @click="router.push({ name: 'module-list', query: carryQuery() })"
        >
          ← 模组库
        </el-button>
        <div class="title-area">
          <el-input
            v-if="renaming"
            v-model="nameDraft"
            size="small"
            class="name-input"
            maxlength="100"
            @keyup.enter="saveName"
          />
          <h2 v-else class="name" @click="renaming = true">{{ detail.name }}</h2>
          <el-tag size="small" :type="PARSE_STATUS_TAG[detail.parse_status]" effect="dark">
            {{ PARSE_STATUS_LABEL[detail.parse_status] }}
          </el-tag>
          <span class="src">{{ SOURCE_TYPE_LABEL[detail.source_type] }} · {{ detail.source_filename }}</span>
        </div>
        <div class="title-actions">
          <el-button v-if="renaming" size="small" type="primary" @click="saveName">保存名称</el-button>
          <el-button v-else size="small" @click="renaming = true">改名</el-button>
          <!-- 从 KP 台进来的，解析完可以直接回控制台挂载（2026-09-10 用户反馈 #2） -->
          <el-button size="small" type="primary" plain @click="goBack">{{ returnLabel }}</el-button>
        </div>
      </div>

      <ModuleParsePanel :module="detail" @refresh="onRefresh" />

      <el-tabs v-model="tab" class="tabs">
        <el-tab-pane label="结构化结果" name="parsed">
          <ModuleResultEditor
            v-if="detail.has_parsed"
            :parsed="parsed"
            :save-handler="saveParsed"
          />
          <el-empty
            v-else
            :description="detail.parse_status === 'parsing' ? '解析中，稍候可查看结构化结果' : '还没有结构化结果，点上方「开始解析」'"
          />
        </el-tab-pane>

        <el-tab-pane label="原文" name="raw">
          <div class="raw-tools">
            <el-input
              v-model="keyword"
              size="small"
              class="search"
              placeholder="在原文中检索…"
              clearable
            />
            <span class="raw-meta">{{ detail.char_count }} 字</span>
          </div>
          <!-- eslint-disable-next-line vue/no-v-html -- 内容已转义，仅用于 <mark> 高亮 -->
          <pre class="raw" v-html="renderedText" />
        </el-tab-pane>
      </el-tabs>

      <p class="foot">
        创建于 {{ formatTime(detail.created_at) }}
        <span v-if="detail.parsed_at"> · 上次解析 {{ formatTime(detail.parsed_at) }}（{{ detail.parse_model || '默认模型' }}）</span>
      </p>
    </template>
  </main>
</template>

<style scoped>
.module-detail {
  min-height: calc(100vh - 54px);
  padding: 24px 32px 56px;
  background: #1b2431;
  color: #e8eaed;
}

.topbar {
  display: flex;
  align-items: center;
  gap: 14px;
  max-width: 1080px;
  margin: 0 auto 16px;
}

.back {
  color: var(--coc-text-muted);
}

.title-area {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.name {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  cursor: pointer;
}

.name:hover {
  color: #e6a23c;
}

.name-input {
  max-width: 300px;
}

.src {
  font-size: 12px;
  color: var(--coc-text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tabs {
  max-width: 1080px;
  margin: 16px auto 0;
}

.raw-tools {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.search {
  max-width: 320px;
}

.raw-meta {
  font-size: 12px;
  color: var(--coc-text-muted);
}

.raw {
  max-height: 60vh;
  margin: 0;
  padding: 16px;
  overflow: auto;
  font-family: ui-monospace, 'Cascadia Code', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.75;
  color: #c7ccd4;
  white-space: pre-wrap;
  word-break: break-word;
  background: #1f2937;
  border: 1px solid #2c3e50;
  border-radius: 8px;
}

.foot {
  max-width: 1080px;
  margin: 18px auto 0;
  font-size: 12px;
  color: var(--coc-text-muted);
}

/* 暗色主题适配 */
:deep(.el-tabs__item) {
  color: var(--coc-text-muted);
}

:deep(.el-tabs__item.is-active) {
  color: #e6a23c;
}

:deep(.el-tabs__nav-wrap::after) {
  background-color: #2c3e50;
}

:deep(.raw mark) {
  padding: 0 2px;
  color: #1b2431;
  background: #e6a23c;
}
</style>
