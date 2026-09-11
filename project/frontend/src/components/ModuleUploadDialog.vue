<script setup lang="ts">
/**
 * 模组上传弹窗 — 阶段 5。
 *
 * 只负责「选文件 → 上传 → 后端提取纯文本」，**不触发解析**：
 * 解析要花钱且模型可选，由详情页的解析面板手动点（用户决策 2026-09-10）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { UploadFile, UploadInstance } from 'element-plus'
import { MAX_UPLOAD_BYTES, uploadModule } from '@/api/modules'
import type { ModuleDetail } from '@/types/module'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{
  'update:modelValue': [boolean]
  uploaded: [ModuleDetail]
}>()

const ACCEPT = '.txt,.md,.pdf,.docx'

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})
const uploadRef = ref<UploadInstance>()
const picked = ref<File | null>(null)
const uploading = ref(false)

watch(visible, (open: boolean) => {
  if (open) {
    picked.value = null
    uploadRef.value?.clearFiles()
  }
})

function onPick(file: UploadFile): void {
  const raw = file.raw
  if (!raw) return
  const ext = raw.name.slice(raw.name.lastIndexOf('.')).toLowerCase()
  if (!ACCEPT.includes(ext)) {
    ElMessage.warning('仅支持 TXT / MD / PDF / DOCX')
    uploadRef.value?.clearFiles()
    picked.value = null
    return
  }
  if (raw.size > MAX_UPLOAD_BYTES) {
    ElMessage.warning(`文件超过 ${MAX_UPLOAD_BYTES / 1024 / 1024}MB`)
    uploadRef.value?.clearFiles()
    picked.value = null
    return
  }
  picked.value = raw
}

function onExceed(files: File[]): void {
  uploadRef.value?.clearFiles()
  const [file] = files
  if (file) onPick({ raw: file } as UploadFile)
}

async function submit(): Promise<void> {
  if (!picked.value) {
    ElMessage.warning('请先选择模组文件')
    return
  }
  uploading.value = true
  try {
    const detail = await uploadModule(picked.value)
    ElMessage.success(`已上传「${detail.name}」，提取 ${detail.char_count} 字`)
    emit('uploaded', detail)
    visible.value = false
  } catch {
    // 错误提示由 axios 拦截器统一弹出
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <el-dialog v-model="visible" title="上传模组" width="480px">
    <el-upload
      ref="uploadRef"
      drag
      :auto-upload="false"
      :limit="1"
      :accept="ACCEPT"
      :on-change="onPick"
      :on-exceed="onExceed"
      :show-file-list="false"
    >
      <div class="drop">
        <p class="drop-icon">📜</p>
        <p class="drop-main">把剧本拖到这里，或点击选择文件</p>
        <p class="drop-sub">支持 TXT / MD / PDF / DOCX，单文件不超过 10MB</p>
      </div>
    </el-upload>

    <p v-if="picked" class="picked">已选择：{{ picked.name }}</p>
    <p v-else class="picked picked--empty">尚未选择文件</p>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="uploading" :disabled="!picked" @click="submit">
        上传并提取
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.drop {
  padding: 18px 0;
  text-align: center;
}

.drop-icon {
  margin: 0 0 6px;
  font-size: 30px;
}

.drop-main {
  margin: 0;
  font-size: 14px;
  color: #e8eaed;
}

.drop-sub {
  margin: 6px 0 0;
  font-size: 12px;
  color: var(--coc-text-muted);
}

.picked {
  margin: 12px 0 0;
  font-size: 13px;
  color: #e6a23c;
  word-break: break-all;
}

.picked--empty {
  color: var(--coc-text-muted);
}
</style>
