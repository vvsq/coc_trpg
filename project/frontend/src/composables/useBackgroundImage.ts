/**
 * 自选背景图（仅本机浏览器）— 阶段 6.2④。
 *
 * 用户决策：背景图**不上传服务器**，只影响自己这台机器，故用原生 IndexedDB 存图片
 * Blob（localStorage 只有 ~5MB 且只能存字符串，放不下稍大的图）。
 *
 * 生命周期：objectURL 由本模块统一创建/回收，避免更换背景时泄漏。
 */
import { onUnmounted, ref, type Ref } from 'vue'

const DB_NAME = 'coc_ui'
const DB_VERSION = 1
const STORE = 'images'
/** 单张自选图上限 6MB：局域网浏览器本地使用足够，且避免把 IndexedDB 撑爆 */
export const MAX_BG_BYTES = 6 * 1024 * 1024
const KEY = 'background'

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(STORE)) db.createObjectStore(STORE)
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function tx<T>(mode: IDBTransactionMode, run: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return openDb().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const t = db.transaction(STORE, mode)
        const req = run(t.objectStore(STORE))
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
        t.oncomplete = () => db.close()
      }),
  )
}

/** 当前自选图的 objectURL（无自选图为 null）；多组件共享同一份 */
const url = ref<string | null>(null)
/** 是否已尝试过从 IndexedDB 读取（首屏只需读一次） */
let loaded = false
let refCount = 0

function revoke(): void {
  if (url.value) {
    URL.revokeObjectURL(url.value)
    url.value = null
  }
}

/** 把 Blob 转成 objectURL（替换旧的并回收） */
function useBlob(blob: Blob | undefined | null): void {
  revoke()
  if (blob) url.value = URL.createObjectURL(blob)
}

async function loadFromDb(): Promise<void> {
  if (loaded) return
  loaded = true
  try {
    const blob = await tx<Blob | undefined>('readonly', (s) => s.get(KEY) as IDBRequest<Blob | undefined>)
    useBlob(blob)
  } catch {
    // IndexedDB 不可用（隐私模式/被禁用）：静默降级为无自选图
  }
}

export interface UseBackgroundImage {
  url: Ref<string | null>
  /** 保存自选图并立即生效；超出体积上限时抛错（调用方给用户提示） */
  save: (file: File) => Promise<void>
  /** 删除自选图并回落预设 */
  clear: () => Promise<void>
}

export function useBackgroundImage(): UseBackgroundImage {
  refCount++
  void loadFromDb()

  async function save(file: File): Promise<void> {
    if (file.size > MAX_BG_BYTES) {
      const mb = (MAX_BG_BYTES / 1024 / 1024).toFixed(0)
      throw new Error(`图片体积需小于 ${mb}MB（当前 ${(file.size / 1024 / 1024).toFixed(1)}MB）`)
    }
    if (!file.type.startsWith('image/')) throw new Error('请选择图片文件')
    await tx('readwrite', (s) => s.put(file, KEY) as IDBRequest<IDBValidKey>)
    useBlob(file)
    loaded = true
  }

  async function clear(): Promise<void> {
    try {
      await tx('readwrite', (s) => s.delete(KEY) as IDBRequest<undefined>)
    } catch {
      // 删除失败也要让内存态先回落，UI 不卡住
    }
    revoke()
  }

  onUnmounted(() => {
    // 最后一个使用方卸载时才回收 objectURL，多组件共享不会互相打断
    refCount = Math.max(0, refCount - 1)
    if (refCount === 0) revoke()
  })

  return { url, save, clear }
}
