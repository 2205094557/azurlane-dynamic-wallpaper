<template>
  <div ref="wrapRef" class="l2d-wrap">
    <canvas ref="canvasRef"></canvas>
    <div v-if="showHitAreas && hitRects.length" class="l2d-hit-overlay">
      <div
        v-for="r in hitRects"
        :key="r.label"
        class="l2d-hit-box"
        :class="'l2d-hit-' + r.kind"
        :style="{ left: r.rect.x + 'px', top: r.rect.y + 'px', width: r.rect.w + 'px', height: r.rect.h + 'px' }"
      >{{ r.label }}</div>
    </div>
    <div v-if="traceText" class="l2d-trace">追踪：{{ traceText }}</div>
  </div>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { Application } from '@pixi/app'
import { Renderer } from '@pixi/core'
import { InteractionManager } from '@pixi/interaction'
import { Ticker, TickerPlugin } from '@pixi/ticker'
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import { assetUrl, bridge } from '../bridge'
import { voiceEnabled } from '../utils/voice'
import '../../../templates/wallpaper-layout.js'

const WL = window.WallpaperLayout

Application.registerPlugin(TickerPlugin)
Live2DModel.registerTicker(Ticker)
Renderer.registerPlugin('interaction', InteractionManager)

const props = defineProps({
  skin: { type: Object, required: true },
  animation: { type: String, default: '' },
  scale: { type: Number, default: 100 },
  offsetX: { type: Number, default: 0 },
  offsetY: { type: Number, default: 0 },
  alignment: { type: String, default: 'center' },
  interactionMode: { type: Boolean, default: false },
  showHitAreas: { type: Boolean, default: false },
})
const emit = defineEmits(['ready', 'error', 'animations', 'scaleChange', 'panChange', 'subtitle'])

const wrapRef = ref(null)
const canvasRef = ref(null)

let app = null
let model = null
let motionList = []
let initW = 0
let initH = 0
let drag = null
let currentLabel = ''
let interactionCtrl = null
let forceLoop = null // null=按动作自带 Meta.Loop；true/false=强制循环/播一次
let resumeOnFinish = false
let entryPlan = null // 入场 home→idle：父级自动选中的目标动作在 home 播完前先忽略
let disposed = false // 卸载后置位：异步 load() 恢复时不再触碰已销毁的实例
const hitRects = ref([])
let lastHitKey = ''
const traceText = ref('')

// 运行时交互追踪（排障用）：显示最近一次点击/播放/回退决策
function trace(msg) {
  traceText.value = `${new Date().toLocaleTimeString()} ${msg}`
}

// ---- 互动语音（本地有该船语音时播放对应 cue）----
let voiceShipId = null
let voicePick = null // {touch_head: cue, touch_1: cue, ...}
let voiceMains = [] // 待机 main_* cue 列表
let voiceWords = {} // 台词文本（headtouch/touch/touch2/login/home/main）
let voiceAudio = null
const subtitleText = ref('')
// 台词 → 右侧面板文本框（父级在预览右侧面板展示，不再叠加在画布上）
watch(subtitleText, (t) => emit('subtitle', t))
// 语音开关（与「拖拽/互动」控件组共享，utils/voice.js 管理状态）；关闭时停音清字幕
watch(voiceEnabled, (on) => {
  if (!on) {
    if (voiceAudio) {
      voiceAudio.pause()
      voiceAudio.close && voiceAudio.close()
      voiceAudio = null
    }
    subtitleText.value = ''
  }
})

// 互动动作 → 语音 cue 基础名
const VOICE_BASE = {
  touch_head: 'touch_head',
  touch_body: 'touch_1',
  touch_special: 'touch_2',
  login: 'login',
  home: 'home',
}
// cue 基础名 → 台词分类
const WORDS_KEY = {
  touch_head: 'headtouch',
  touch_1: 'touch',
  touch_2: 'touch2',
  login: 'login',
  home: 'home',
}
// 语音 cue 回退链：很多船（企业/Z46 等）语音包没有 touch_head 专属 cue，
// 摸头时回退到身体触摸（touch_1）再特殊（touch_2），保证点击必有语音。
const VOICE_FALLBACK = {
  touch_head: ['touch_head', 'touch_1', 'touch_2'],
  touch_body: ['touch_1', 'touch_2', 'touch_head'],
  touch_special: ['touch_2', 'touch_1', 'touch_head'],
  login: ['login'],
  home: ['home'],
}
// 台词回退链：语音有但该类别无台词文本（或后端已按船借用）时，逐级回退
const WORDS_FALLBACK = {
  headtouch: ['headtouch', 'touch', 'touch2'],
  touch: ['touch', 'touch2', 'headtouch'],
  touch2: ['touch2', 'touch', 'headtouch'],
  login: ['login'],
  home: ['home'],
}

async function loadVoiceStatus() {
  try {
    const vs = await bridge.voiceStatus(props.skin.painting || '')
    if (vs && vs.ok && vs.shipId && vs.cues.length) {
      voiceShipId = vs.shipId
      voicePick = vs.pick || {}
      voiceMains = (vs.cues || []).filter((c) => /^main_\d+/.test(c))
      voiceWords = vs.words || {}
      trace(`语音就绪：船 ${voiceShipId}，pick=${JSON.stringify(voicePick)}，words=${Object.keys(voiceWords).length} 类`)
    } else {
      trace(`语音不可用：${props.skin.painting || '(无painting)'} → ${vs && vs.error ? vs.error : '该船未下载语音'}`)
    }
  } catch (e) {
    trace(`语音加载失败：${e.message || e}`)
  }
}

function playVoiceCue(cue, text) {
  if (!voiceShipId || !cue) {
    trace(`语音跳过：${!voiceShipId ? '无shipId' : '无cue'}`)
    return
  }
  if (!voiceEnabled.value) {
    trace(`语音跳过：开关已关`)
    return
  }
  try {
    if (voiceAudio) {
      voiceAudio.pause()
      voiceAudio.close && voiceAudio.close()
      voiceAudio = null
    }
    const a = new Audio(assetUrl(`voice/${voiceShipId}/${cue}.wav`))
    a.volume = 0.9
    // 播放失败（cue 文件缺失等）：清掉字幕，避免显示“无内容的台词”
    a.play().catch(() => {
      if (voiceAudio === a) {
        voiceAudio = null
        subtitleText.value = ''
      }
    })
    voiceAudio = a
    subtitleText.value = text || ''
    trace(`▶ 语音 ${cue}${text ? '（' + text.slice(0, 14) + '…）' : ''}`)
  } catch (e) {
    /* 无语音不影响互动 */
  }
}

function playVoice(label) {
  if (!voicePick) return
  // label 是互动区域名（touch_body/touch_special），voicePick 按 cue 基础名
  //（touch_1/touch_2）收录，必须先经 VOICE_BASE 映射，否则身体/特殊点击查不到语音。
  const base = VOICE_BASE[label] || label
  // cue 回退：本类别无语音时沿回退链找第一个可用的（如摸头无专属 → 用身体触摸语音）
  let cue = null
  let cueBase = ''
  for (const b of VOICE_FALLBACK[base] || [base]) {
    if (voicePick[b]) {
      cue = voicePick[b]
      cueBase = b
      break
    }
  }
  if (!cue) {
    trace(`语音跳过：${label} 无可用 cue`)
    return
  }
  // 台词回退：该类别无文本时沿回退链找（如无 headtouch 台词 → 用 touch 台词）
  const wantKey = WORDS_KEY[cueBase] || WORDS_KEY[base]
  let text = ''
  for (const k of WORDS_FALLBACK[wantKey] || [wantKey]) {
    if (voiceWords[k]) {
      text = voiceWords[k]
      break
    }
  }
  playVoiceCue(cue, text)
}

function playVoiceRandomMain() {
  if (!voiceMains.length) return
  const cue = voiceMains[Math.floor(Math.random() * voiceMains.length)]
  const m = /^main_(\d+)/.exec(cue)
  const idx = m ? parseInt(m[1], 10) - 1 : 0
  const lines = Array.isArray(voiceWords.main) ? voiceWords.main : []
  playVoiceCue(cue, lines[idx] || '')
}

function updateHitOverlay() {
  if (!props.showHitAreas || !model) {
    hitRects.value = []
    lastHitKey = ''
    return
  }
  try {
    hitRects.value = WL.l2dHitAreaRects(model) || []
  } catch (e) {
    hitRects.value = []
  }
}

function applyLayout() {
  if (!model || !initW || !initH) return
  const w = wrapRef.value.clientWidth
  const h = wrapRef.value.clientHeight
  if (!w || !h) return
  const a = WL.anchor(props.alignment)
  const out = WL.l2dLayout(initW, initH, w, h, {
    scale: props.scale,
    offsetX: props.offsetX,
    offsetY: props.offsetY,
    alignX: a.x,
    alignY: a.y,
  })
  model.scale.set(out.sx)
  model.position.set(out.x, out.y)
  updateHitOverlay()
}

function onResize() {
  applyLayout()
}

function playMotion(label, record = true, forceLoopArg) {
  if (!model || !motionList.length) return
  const findLabel = (l) =>
    motionList.find((m) => m.label === l || (l && m.label.startsWith(l + '_')))
  let target = findLabel(label)
  // 具体 touch 动作缺失时回退到同类动作（如只有 touch_drag1-3，但拖 11 号区）
  if (!target && /^touch/i.test(label || '')) {
    const kind = /^touch_drag/i.test(label)
      ? 'touch_drag'
      : /^touch_idle/i.test(label)
        ? 'touch_idle'
        : null
    if (kind) target = motionList.find((m) => m.label.startsWith(kind))
  }
  if (!target && (!label || !/^touch/i.test(label))) {
    target =
      motionList.find((m) => /^idle$/i.test(m.label)) ||
      motionList.find((m) => m.label === 'home') ||
      motionList[0]
  }
  if (!target) return
  try {
    const im = model.internalModel
    // touch 互动动作不重置参数：碧蓝模型的机关/菜单面板由参数状态驱动
    //（如 ParamrenwuTMD / Base_DecisionBox），重置会关掉面板，破坏“二次点击”层级。
    // 只有切换主动画/Idle 时才重置，避免旧动作的部件/表情参数残留。
    const isTouch = /^touch/i.test(label || '')
    if (im?.parameters && !isTouch) {
      im.parameters.values.set(im.parameters.defaultValues)
    }
    // 动作被强制循环后，当前动作的 NORMAL 优先级不会复位，同优先级的新动作会被库拒绝
    //（MotionState.reserve: priority <= currentPriority 直接 return false）。
    // 切换前先停掉当前动作把状态清空（currentPriority=0），再播新的。
    resumeOnFinish = false // 防止 stopAllMotions 触发 finish 误恢复
    forceLoop = forceLoopArg !== undefined ? forceLoopArg : null
    im?.motionManager?.stopAllMotions?.()
    model.motion(target.group, target.index)
    if (record) currentLabel = target.label
    trace(`▶ 播放 ${target.label}（${target.group}，loop=${forceLoop === null ? '自动' : forceLoop}${record ? '，记录为当前' : ''}）`)
  } catch (e) {
    /* 动作组不存在时忽略 */
  }
}

async function load() {
  const base = assetUrl(props.skin.asset.dir)
  const modelPath = props.skin.asset.model
  const meta = await (await fetch(`${base}/${modelPath}`)).json()
  // 皮肤切换/退出预览发生在加载期间：组件已卸载，不能再碰 refs 与 emit
  if (disposed) return

  motionList = []
  for (const [group, items] of Object.entries(meta.Motions || {})) {
    for (let i = 0; i < items.length; i++) {
      const file = items[i].File || ''
      const label = file.split('/').pop().replace(/\.motion3\.json$/i, '')
      motionList.push({ label, group, index: i })
    }
  }
  emit('animations', motionList.map((m) => m.label))

  app = new Application({
    view: canvasRef.value,
    transparent: true,
    autoStart: true,
    resizeTo: wrapRef.value,
    antialias: true,
    // 透明 WebGL 画布在拖拽时容易在合成阶段留下上一帧的“虚影”，
    // preserveDrawingBuffer 可避免浏览器在合成后清空/残留缓冲
    preserveDrawingBuffer: true,
  })
  // 命中区指示框逐帧跟随模型：动作/拖动会移动部件，不能只算一次快照
  app.ticker.add(() => {
    if (!props.showHitAreas || !model) return
    try {
      const rects = WL.l2dHitAreaRects(model) || []
      const key = rects
        .map((r) => `${r.label}|${Math.round(r.rect.x)},${Math.round(r.rect.y)},${Math.round(r.rect.w)},${Math.round(r.rect.h)}`)
        .join(';')
      if (key !== lastHitKey) {
        lastHitKey = key
        hitRects.value = rects
      }
    } catch (e) {
      /* 忽略单帧异常 */
    }
  })
  model = await Live2DModel.from(`${base}/${modelPath}`, { autoUpdate: true })
  if (disposed) {
    // 卸载时 app 已 destroy，model 尚未挂到舞台：手动释放避免资源残留
    model.destroy?.()
    return
  }
  model.anchor.set(0.5, 0.5)
  app.stage.addChild(model)
  // pixi-live2d-display 0.4.0 会忽略动作自带的 Loop 标志（Meta.Loop 解析后从未应用），
  // 导致每个动作播完就触发“自动随机播放 Idle 姿势”，看起来像莫名换姿势。
  // 这里强制让所有动作循环，并禁用自动随机 Idle：只有手动切换动画才会换姿势。
  const motionManager = model.internalModel?.motionManager
  if (motionManager) {
    motionManager.groups.idle = '__none__'
    motionManager.on('motionStart', (group, index) => {
      const m = motionManager.motionGroups?.[group]?.[index]
      // 循环与否优先按动作自带 Meta.Loop（如 touch_idle1 是 1.2s 短循环渐进动画）；
      // forceLoop 仅用于拖拽（拖动期间循环）和 home（入场播一次）。
      const autoLoop = !!(m && m._motionData && m._motionData.loop)
      const loop = forceLoop !== null ? forceLoop : autoLoop
      if (m && typeof m.setIsLoop === 'function') m.setIsLoop(loop)
      // 只回退“显式要求播一次”的动作（头/身/特反应、进场 login）：
      // 循环与否按 forceLoop 显式值判断，数据自带的 Loop 不影响回退决策，
      // 保证 idle 区域点击（强制循环）无论发生什么都不自动跳回。
      resumeOnFinish = forceLoop === false
    })
    motionManager.on('motionFinish', () => {
      if (resumeOnFinish) {
        resumeOnFinish = false
        entryPlan = null
        trace(`⏎ 动作播完 → 自动切回待机 ${currentLabel || '无'}`)
        if (currentLabel) playMotion(currentLabel)
      }
    })
  }
  // 记录加载时的稳定模型尺寸，作为基础缩放基准
  initW = model.width
  initH = model.height
  applyLayout()
  // 进场目标：父级选中的动画优先，否则默认 idle/第一个
  const want = props.animation || ''
  const hasLogin = motionList.some((m) => m.label === 'login')
  const hasIdle = motionList.some((m) => m.label === 'idle')
  currentLabel =
    (want && motionList.some((m) => m.label === want))
      ? want
      : (hasIdle ? 'idle' : (motionList[0]?.label || ''))
  // 迎宾：进场先播一次 login（登入动作），播完自动切到 currentLabel；无 login 直接播
  entryPlan = hasLogin ? currentLabel : null
  await loadVoiceStatus()
  if (disposed) return
  if (hasLogin) {
    playMotion('login', false, false)
    playVoice('login')
  }
  else if (currentLabel) playMotion(currentLabel)
  emit('ready')
  createInteraction()
  syncMode()
}

watch(
  () => [props.scale, props.offsetX, props.offsetY, props.alignment],
  () => applyLayout(),
)

watch(
  () => props.animation,
  (v) => {
    // 入场 home 播完会自动切到该目标，忽略父级自动选中，避免打断 home
    if (entryPlan && v === entryPlan) return
    entryPlan = null
    if (v) playMotion(v)
  },
)

watch(
  () => props.interactionMode,
  () => syncMode(),
)

watch(
  () => props.showHitAreas,
  () => updateHitOverlay(),
)

function onWheel(e) {
  if (props.interactionMode) return
  e.preventDefault()
  const factor = Math.pow(1.1, -e.deltaY / 100)
  const next = WL.clampScale(props.scale * factor)
  emit('scaleChange', Math.round(next))
}

function onPanDown(e) {
  if (props.interactionMode || e.button !== 0) return
  drag = { x: e.clientX, y: e.clientY, ox: props.offsetX, oy: props.offsetY }
  wrapRef.value.style.cursor = 'grabbing'
}

// 拖拽/缩放（布局模式）与互动模式互斥：按 interactionMode 附加/移除各自的事件。
// 幂等：先全部解绑再按模式绑定（syncMode 在 onMounted 与 load() 末尾各调用一次，
// 若直接 add 会把事件绑两遍，卸载时只解一遍，残留引用已销毁实例的僵尸监听）。
function syncMode() {
  const interactive = props.interactionMode
  if (interactionCtrl) interactionCtrl.setEnabled(interactive)
  const wrap = wrapRef.value
  wrap.removeEventListener('wheel', onWheel)
  wrap.removeEventListener('mousedown', onPanDown)
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  if (interactive) {
    wrap.style.cursor = 'default'
  } else {
    wrap.addEventListener('wheel', onWheel, { passive: false })
    wrap.addEventListener('mousedown', onPanDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    wrap.style.cursor = 'grab'
  }
}

// touch_idleN 区域点击 → 永远映射到 Idle 组动画（渐进待机）：
// 同名 idleN 优先；无同名找最近的可用 idleN（idle2 缺失 → idle1/idle3）；
// 绝不回退到 touch_idleN 短反应。
function idleRegionLabel(label) {
  const m = /^touch_idle(\d+)$/i.exec(label || '')
  if (!m) return label
  const n = parseInt(m[1], 10)
  const has = (l) => motionList.some((x) => x.label === l)
  if (has('idle' + n)) return 'idle' + n
  for (let d = 1; d <= 99; d++) {
    if (has('idle' + (n - d))) return 'idle' + (n - d)
    if (has('idle' + (n + d))) return 'idle' + (n + d)
  }
  return has('idle') ? 'idle' : label
}

// 点击/拖拽互动控制器（共享模块 wallpaper-layout.js，与导出壁纸同一套逻辑）。
function createInteraction() {
  if (interactionCtrl || !model) return
  interactionCtrl = WL.l2dInteraction(model, wrapRef.value, {
    // 点击/拖拽的 touch_* 动作只播不记录，拖拽结束恢复的还是点之前的动作
    play: (label, fromDrag) => {
      const isDrag = /^touch_drag/i.test(label || '')
      // idle 区域点击：先播一次 touch_idleN 短反应，播完自动跳转到 Idle 组动画并保持
      if (!fromDrag && /^touch_idle/i.test(label || '')) {
        const finalTarget = idleRegionLabel(label) // 最终保持的 Idle 组动画（idleN 或最近的）
        currentLabel = finalTarget // 记录为当前：反应播完后的落点
        const hasReaction = motionList.some((x) => x.label === label)
        entryPlan = null
        playVoiceRandomMain() // 待机语音
        if (hasReaction && finalTarget !== label) {
          // 先播短反应（播一次，不记录），finish 后 resumeOnFinish 自动切到 finalTarget 保持
          trace(`点击 idle 区域 ${label} → 先播 ${label}，播完跳转 ${finalTarget} 保持`)
          playMotion(label, false, false)
        } else {
          trace(`点击 idle 区域 ${label} → 直接跳转 ${finalTarget} 保持`)
          playMotion(finalTarget, true, true)
        }
        return
      }
      let target = label
      // 拖拽动作也记录为当前动画：松手后保持播放，直到下一次点击/拖动
      let record = fromDrag || (!fromDrag && !/^touch/i.test(label || ''))
      let forceLoopArg = null
      if (!fromDrag && /^touch_idle/i.test(label || '')) {
        // idleN 区域点击：切到 Idle 组同名 idleN 渐进动画并强制循环保持（保证不自动回退）
        target = idleRegionLabel(label)
        record = true
        forceLoopArg = true
      } else if (!fromDrag && /^touch_(head|body|special)$/i.test(label || '')) {
        // 头/身/特：一次性反应，播完由 resumeOnFinish 自动切回当前待机动画
        forceLoopArg = false
        playVoice(label) // 对应台词
      }
      entryPlan = null // 用户互动打断进场迎宾，避免旧 entryPlan 吞掉后续下拉选择
      trace(`${fromDrag ? '拖拽' : '点击'} 命中 ${label} → 目标 ${target}（record=${record}，loop=${forceLoopArg === null ? '自动' : forceLoopArg}）`)
      // 拖拽期间强制循环；其余交给 forceLoopArg / 动作自带 Meta.Loop 决定
      playMotion(target, record, isDrag && fromDrag ? true : forceLoopArg)
    },
    dragLabels: () =>
      motionList.filter((m) => /^touch_drag/i.test(m.label)).map((m) => m.label),
    revert: () => {
      trace(`↩ 拖拽结束 → 恢复 ${currentLabel || '无'}`)
      currentLabel && playMotion(currentLabel)
    },
  })
  interactionCtrl.setEnabled(props.interactionMode)
  updateHitOverlay()
}

function onMove(e) {
  if (!drag) return
  drag.lastX = e.clientX
  drag.lastY = e.clientY
  const w = wrapRef.value.clientWidth || 1
  const h = wrapRef.value.clientHeight || 1
  const ox = WL.clampOffset(drag.ox + ((e.clientX - drag.x) / w) * 100)
  const oy = WL.clampOffset(drag.oy + ((e.clientY - drag.y) / h) * 100)
  const a = WL.anchor(props.alignment)
  const out = WL.l2dLayout(initW, initH, w, h, {
    scale: props.scale,
    offsetX: ox,
    offsetY: oy,
    alignX: a.x,
    alignY: a.y,
  })
  model.scale.set(out.sx)
  model.position.set(out.x, out.y)
}

function onUp() {
  if (!drag) return
  const w = wrapRef.value.clientWidth || 1
  const h = wrapRef.value.clientHeight || 1
  const lx = drag.lastX != null ? drag.lastX : drag.x
  const ly = drag.lastY != null ? drag.lastY : drag.y
  const ox = Math.round(WL.clampOffset(drag.ox + ((lx - drag.x) / w) * 100))
  const oy = Math.round(WL.clampOffset(drag.oy + ((ly - drag.y) / h) * 100))
  drag = null
  wrapRef.value.style.cursor = 'grab'
  emit('panChange', { x: ox, y: oy })
}

onMounted(() => {
  load().catch((e) => emit('error', e.message || String(e)))
  syncMode()
  window.addEventListener('resize', onResize)
})

// keep-alive 缓存（图鉴页）下切走时暂停渲染与语音：隐藏页继续跑 ticker 是纯资源浪费
onDeactivated(() => {
  if (app) app.ticker.stop()
  if (voiceAudio) {
    voiceAudio.pause()
    voiceAudio.close && voiceAudio.close()
    voiceAudio = null
  }
})
onActivated(() => {
  if (app) app.ticker.start()
})

onBeforeUnmount(() => {
  disposed = true
  // 切换皮肤/退出预览会销毁组件：不暂停会导致上一个皮肤的语音继续响
  if (voiceAudio) {
    voiceAudio.pause()
    voiceAudio.close && voiceAudio.close()
    voiceAudio = null
  }
  window.removeEventListener('resize', onResize)
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  if (interactionCtrl) interactionCtrl.destroy()
  if (app) app.destroy(true)
})

defineExpose({
  capture: () => {
    try {
      return canvasRef.value ? canvasRef.value.toDataURL('image/png') : null
    } catch (e) {
      return null
    }
  },
})
</script>

<style scoped>
.l2d-wrap {
  width: 100%;
  height: 100%;
  position: relative;
  touch-action: none;
}

.l2d-wrap canvas {
  width: 100%;
  height: 100%;
}

.l2d-hit-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.l2d-trace {
  position: absolute;
  top: 10px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 6;
  max-width: 92%;
  font-size: 14px;
  line-height: 22px;
  color: #ffd77a;
  background: rgba(0, 0, 0, 0.75);
  padding: 4px 14px;
  border-radius: 6px;
  pointer-events: none;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.l2d-hit-box {
  position: absolute;
  border: 1.5px dashed rgba(255, 255, 255, 0.85);
  color: #fff;
  font-size: 11px;
  line-height: 16px;
  padding: 0 4px;
  border-radius: 4px;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.85);
  box-sizing: border-box;
}

.l2d-hit-head {
  background: rgba(255, 90, 90, 0.24);
  border-color: rgba(255, 120, 120, 0.9);
}

.l2d-hit-body {
  background: rgba(90, 140, 255, 0.22);
  border-color: rgba(140, 180, 255, 0.9);
}

.l2d-hit-special {
  background: rgba(90, 220, 140, 0.22);
  border-color: rgba(140, 255, 180, 0.9);
}

.l2d-hit-drag {
  background: rgba(190, 120, 255, 0.25);
  border-color: rgba(210, 160, 255, 0.9);
}

.l2d-hit-idle {
  background: rgba(255, 170, 80, 0.25);
  border-color: rgba(255, 200, 120, 0.9);
}
</style>
