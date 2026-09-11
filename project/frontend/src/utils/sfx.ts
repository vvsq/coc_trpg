/**
 * 极简音效（WebAudio 合成，零音频文件）— 阶段 6.2④。
 *
 * 为什么不用音频文件：项目没有音频素材，且比赛现场可能断网；借鉴 ui-example 的做法
 * 用振荡器 + 增益包络合成几个短音即可（代码体积远小于一个 mp3）。
 *
 * 约定：
 *   - 默认关闭，由设置页「音效」开关控制（AppLayout 同步 settings.sound → setSfxEnabled）；
 *   - 浏览器要求用户手势后才能出声，音频上下文延迟创建，创建失败静默降级（不影响主流程）；
 *   - 任何时候出错都不能打断游戏流程，故所有调用点都做 try/catch 兜底。
 */

export type SfxName = 'dice' | 'message' | 'click'

/** 单个音粒：起止频率 + 时长 + 波形 + 音量 */
interface Blip {
  from: number
  to: number
  dur: number
  type: OscillatorType
  gain: number
  /** 相对音效起点的延迟（毫秒），用于合成"咔哒"双击感 */
  delay?: number
}

const RECIPES: Record<SfxName, Blip[]> = {
  // 骰子落地：两声短促的木质撞击
  dice: [
    { from: 240, to: 90, dur: 0.07, type: 'triangle', gain: 0.22 },
    { from: 180, to: 70, dur: 0.09, type: 'triangle', gain: 0.16, delay: 70 },
  ],
  // 新消息：一记柔和提示音
  message: [{ from: 720, to: 520, dur: 0.12, type: 'sine', gain: 0.12 }],
  // 交互反馈：极短轻点
  click: [{ from: 900, to: 700, dur: 0.04, type: 'square', gain: 0.06 }],
}

let ctx: AudioContext | null = null
let enabled = false

/** 设置页写入；关掉后再调用 playSfx 直接返回 */
export function setSfxEnabled(value: boolean): void {
  enabled = value
}

function getCtx(): AudioContext | null {
  if (!enabled || typeof window === 'undefined') return null
  if (!ctx) {
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    ctx = new Ctor()
  }
  if (ctx.state === 'suspended') void ctx.resume()
  return ctx
}

/** 播放一个合成音效；关闭/不支持/被浏览器拦截时静默返回 */
export function playSfx(name: SfxName): void {
  const audio = getCtx()
  if (!audio) return
  try {
    const now = audio.currentTime
    for (const blip of RECIPES[name]) {
      const start = now + (blip.delay ?? 0) / 1000
      const osc = audio.createOscillator()
      const gain = audio.createGain()
      osc.type = blip.type
      osc.frequency.setValueAtTime(blip.from, start)
      osc.frequency.exponentialRampToValueAtTime(Math.max(40, blip.to), start + blip.dur)
      // 快起快落，避免爆音
      gain.gain.setValueAtTime(0.0001, start)
      gain.gain.linearRampToValueAtTime(blip.gain, start + 0.008)
      gain.gain.exponentialRampToValueAtTime(0.0001, start + blip.dur)
      osc.connect(gain).connect(audio.destination)
      osc.start(start)
      osc.stop(start + blip.dur + 0.02)
    }
  } catch {
    // 音频不可用不影响游戏流程
  }
}
