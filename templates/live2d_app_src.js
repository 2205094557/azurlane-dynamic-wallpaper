import { Application } from '@pixi/app'
import { Renderer } from '@pixi/core'
import { InteractionManager } from '@pixi/interaction'
import { Ticker, TickerPlugin } from '@pixi/ticker'
import { Live2DModel } from 'pixi-live2d-display/cubism4'

// 布局统一模块由 wallpaper-layout.js 注入 window.WallpaperLayout
const WL = window.WallpaperLayout

Application.registerPlugin(TickerPlugin)
Live2DModel.registerTicker(Ticker)
Renderer.registerPlugin('interaction', InteractionManager)

let model = null
let app = null
let initW = 0
let initH = 0
let scale = 100
let ox = 0
let oy = 0
let alignment = 'center'
let meta = null
let lastMotionLabel = ''
let forceLoop = null // null=按动作自带 Meta.Loop；true/false=强制循环/播一次
let resumeOnFinish = false
// WE 面板开关（右侧属性面板）：语音开/关、开场动画开/关（login 播一次再回 idle）、
// 互动开/关（点击/拖拽等交互是否生效）
let voiceOn = true
let introOn = true
let interactOn = true
// 互动控制器（start() 内创建，提升为模块级以便 WE 面板实时切换）
let interaction = null

function applyLayout() {
  if (!model || !initW || !initH) return
  const a = WL.anchor(alignment)
  const out = WL.l2dLayout(initW, initH, window.innerWidth, window.innerHeight, {
    scale,
    offsetX: ox,
    offsetY: oy,
    alignX: a.x,
    alignY: a.y,
  })
  model.scale.set(out.sx)
  model.position.set(out.x, out.y)
}

async function start() {
  const cfg = window.__L2D_CONFIG
  const init = window.__L2D_INIT || {}
  scale = WL.clampScale(init.scale != null ? init.scale : 100)
  ox = WL.clampOffset(init.ox != null ? init.ox : 0)
  oy = WL.clampOffset(init.oy != null ? init.oy : 0)
  alignment = init.alignment || 'center'
  const wantAnim = init.anim || ''
  // 面板开关默认值来自导出内联 __L2D_INIT；WE 存储的覆盖值在首推里单独采纳
  voiceOn = init.voice !== false
  introOn = init.intro !== false
  interactOn = init.interact !== false

  app = new Application({
    view: document.getElementById('canvas'),
    transparent: true,
    autoStart: true,
    resizeTo: window,
    antialias: true,
  })
  model = await Live2DModel.from(cfg.model, { autoUpdate: true })
  model.anchor.set(0.5, 0.5)
  app.stage.addChild(model)
  // pixi-live2d-display 0.4.0 会忽略动作自带的 Loop 标志，动作播完会自动随机切 Idle 姿势。
  // 这里强制所有动作循环并禁用随机 Idle：壁纸只会一直播放当前动作。
  const motionManager = model.internalModel?.motionManager
  if (motionManager) {
    motionManager.groups.idle = '__none__'
    motionManager.on('motionStart', (group, index) => {
      const m = motionManager.motionGroups?.[group]?.[index]
      // 循环与否优先按动作自带 Meta.Loop；forceLoop 仅用于拖拽与 home
      const autoLoop = !!(m && m._motionData && m._motionData.loop)
      const loop = forceLoop !== null ? forceLoop : autoLoop
      if (m && typeof m.setIsLoop === 'function') m.setIsLoop(loop)
      // 只回退“显式要求播一次”的动作（头/身/特反应、进场 login）：
      // 数据自带的 Loop 不影响回退决策，保证 idle 区域点击（强制循环）不自动跳回。
      resumeOnFinish = forceLoop === false
    })
    motionManager.on('motionFinish', () => {
      if (resumeOnFinish) {
        resumeOnFinish = false
        if (lastMotionLabel) playMotionByLabel(lastMotionLabel)
      }
    })
  }
  // 碧蓝 model3.json 无 HitAreas，注入 moc3 自带的官方命中部件 TouchHead/TouchSpecial/TouchBody
  WL.setupL2DHitAreas(model)
  initW = model.width
  initH = model.height
  applyLayout()
  try {
    meta = await (await fetch(cfg.model)).json()
    // 进场目标：预览选中的动作优先，否则默认 idle/home/第一个
    const labels = []
    for (const g of Object.keys(meta.Motions || {})) {
      for (const it of meta.Motions[g] || []) {
        const stem = (it.File || '').split('/').pop().replace(/\.motion3\.json$/i, '')
        if (!labels.includes(stem)) labels.push(stem)
      }
    }
    const hasLogin = labels.includes('login')
    const hasIdle = labels.includes('idle')
    lastMotionLabel =
      (wantAnim && labels.includes(wantAnim))
        ? wantAnim
        : (hasIdle ? 'idle' : (labels[0] || ''))
    // 迎宾：开场动画开着时先播一次 login（登入动作），播完自动切到 lastMotionLabel；
    // 关闭时直接播 idle（可在 WE 右侧面板开关，重启壁纸后按存储值生效）
    if (hasLogin && introOn) {
      playMotionByLabel('login', false, false)
      playVoice('login')
    }
    else if (lastMotionLabel) playMotionByLabel(lastMotionLabel)
  } catch (e) { /* 无动作不影响显示 */ }

// touch_idleN 区域点击 → 优先切到 Idle 组同名 idleN（渐进待机动画）；无同名则保持 touch_idleN
function idleRegionLabel(label) {
  const m = /^touch_idle(\d+)$/i.exec(label || '')
  if (!m) return label
  const n = parseInt(m[1], 10)
  const stemOf = (it) => (it.File || '').split('/').pop().replace(/\.motion3\.json$/i, '')
  const has = (l) => {
    const groups = Object.keys(meta.Motions || {})
    for (const g of groups) {
      if ((meta.Motions[g] || []).some((it) => stemOf(it) === l)) return true
    }
    return false
  }
  // 永远映射到 Idle 组动画（渐进待机）：同名 idleN 优先，无同名找最近的可用 idleN，
  // 绝不回退到 touch_idleN 短反应。
  if (has('idle' + n)) return 'idle' + n
  for (let d = 1; d <= 99; d++) {
    if (has('idle' + (n - d))) return 'idle' + (n - d)
    if (has('idle' + (n + d))) return 'idle' + (n + d)
  }
  return has('idle') ? 'idle' : label
}

// meta 里是否存在同名动作
function labelsHas(label) {
  if (!meta) return false
  const groups = Object.keys(meta.Motions || {})
  for (const g of groups) {
    if ((meta.Motions[g] || []).some((it) =>
      (it.File || '').split('/').pop().replace(/\.motion3\.json$/i, '') === label,
    )) return true
  }
  return false
}

// 壁纸端恒为互动模式：点击播 touch_*，按住拖动播 touch_drag*，松手恢复拖拽前动作。
// 互动开关（WE 面板「互动」）可整体关闭：interaction.setEnabled 内部已按 enabled 拦截事件。
interaction = WL.l2dInteraction(model, document.getElementById('canvas'), {
  // touch_* 只播不记录，拖拽结束恢复的还是拖拽前的动作
  play: (label, fromDrag) => {
    const isDrag = /^touch_drag/i.test(label || '')
    // idle 区域点击：先播一次 touch_idleN 短反应，播完自动跳转到 Idle 组动画并保持
    if (!fromDrag && /^touch_idle/i.test(label || '')) {
      const finalTarget = idleRegionLabel(label) // 最终保持的 Idle 组动画（idleN 或最近的）
      lastMotionLabel = finalTarget // 记录为当前：反应播完后的落点
      const hasReaction = labelsHas(label)
      playVoiceRandomMain() // 待机语音
      if (hasReaction && finalTarget !== label) {
        // 先播短反应（播一次，不记录），finish 后 resumeOnFinish 自动切到 finalTarget 保持
        playMotionByLabel(label, false, false)
      } else {
        playMotionByLabel(finalTarget, true, true)
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
    // 拖拽期间强制循环；其余交给 forceLoopArg / 动作自带 Meta.Loop 决定
    playMotionByLabel(target, record, isDrag && fromDrag ? true : forceLoopArg)
  },
    dragLabels: l2dDragLabels,
    revert: () => playMotionByLabel(lastMotionLabel),
  })
  interaction.setEnabled(interactOn)
}

// ---- 互动语音（导出壁纸内嵌 __L2D_VOICE）----
const VOICE_CFG = window.__L2D_VOICE || null
let voiceAudio = null

function playVoiceCue(cue) {
  if (!VOICE_CFG || !cue || !voiceOn) return
  try {
    if (voiceAudio) {
      voiceAudio.pause()
      voiceAudio = null
    }
    const a = new Audio(VOICE_CFG.dir + '/' + cue + '.wav')
    a.volume = 0.9
    a.play().catch(() => {})
    voiceAudio = a
  } catch (e) { /* 无语音不影响互动 */ }
}

// 语音 cue 回退链：很多船语音包没有 touch_head 专属 cue，摸头回退到身体触摸语音
const VOICE_FALLBACK = {
  touch_head: ['touch_head', 'touch_1', 'touch_2'],
  touch_body: ['touch_1', 'touch_2', 'touch_head'],
  touch_special: ['touch_2', 'touch_1', 'touch_head'],
  login: ['login'],
  home: ['home'],
}

function playVoice(label) {
  if (!VOICE_CFG || !VOICE_CFG.pick) return
  const base = label || ''
  for (const b of VOICE_FALLBACK[base] || [base]) {
    if (VOICE_CFG.pick[b]) {
      playVoiceCue(VOICE_CFG.pick[b])
      return
    }
  }
}

function playVoiceRandomMain() {
  if (VOICE_CFG && VOICE_CFG.mains && VOICE_CFG.mains.length) {
    playVoiceCue(VOICE_CFG.mains[Math.floor(Math.random() * VOICE_CFG.mains.length)])
  }
}

// 按动作文件名播放（供初始动作与点击/拖拽互动共用）。
// 切换前重置参数并停掉当前动作（同预览 playMotion，避免旧动作遗留/同优先级被拒）。
function playMotionByLabel(label, record = true, forceLoopArg) {
  if (!label || !meta || !model) return false
  const groups = Object.keys(meta.Motions || {})
  for (const g of groups) {
    const items = meta.Motions[g] || []
    const stemOf = (m) => (m.File || '').split('/').pop().replace(/\.motion3\.json$/i, '')
    let idx = items.findIndex((m) => {
      const stem = stemOf(m)
      return stem === label || stem.startsWith(label + '_')
    })
    // 具体 touch 动作缺失时回退到同类动作（如只有 touch_drag1-3，但拖 11 号区）
    if (idx < 0 && /^touch/i.test(label || '')) {
      const kind = /^touch_drag/i.test(label) ? 'touch_drag' : (/^touch_idle/i.test(label) ? 'touch_idle' : null)
      if (kind) idx = items.findIndex((m) => stemOf(m).startsWith(kind))
    }
    if (idx >= 0) {
      try {
        const im = model.internalModel
        // touch 互动不重置参数（机关/菜单面板由参数状态驱动），只有主动画才重置
        if (im?.parameters && !/^touch/i.test(label || '')) {
          im.parameters.values.set(im.parameters.defaultValues)
        }
        resumeOnFinish = false // 防止 stopAllMotions 触发 finish 误恢复
        forceLoop = forceLoopArg !== undefined ? forceLoopArg : null
        im?.motionManager?.stopAllMotions?.()
        model.motion(g, idx)
      } catch (e) { return false }
      if (record) lastMotionLabel = label
      return true
    }
  }
  return false
}

// 可用拖拽动作（touch_drag*，并非所有模型都有）。
function l2dDragLabels() {
  if (!meta) return []
  const out = []
  const groups = Object.keys(meta.Motions || {})
  for (const g of groups) {
    const items = meta.Motions[g] || []
    for (let i = 0; i < items.length; i++) {
      const label = (items[i].File || '').split('/').pop().replace(/\.motion3\.json$/i, '')
      if (/^touch_drag/i.test(label)) out.push(label)
    }
  }
  return out
}

// WE 加载时会先推送一次“全部属性”（含 config.json 里按路径存的历史覆盖值）。
// 该覆盖值可能来自用户在 WE 里手动拖滑块，也可能来自编辑器导入误写；无论哪种，
// 都不应覆盖导出时调好的版式——壁纸一律以导出值（__L2D_INIT）为准，仅忽略首次推送。
// 之后的单属性推送（用户在 WE 里手动调节）仍然生效。
let _initialPropsApplied = false
window.wallpaperPropertyListener = {
  applyUserProperties: function (properties) {
    try {
      if (!_initialPropsApplied) {
        _initialPropsApplied = true
        // 布局类属性（scale/offset/alignment）一律以导出内联值为准，忽略首推；
        // 语音/开场/互动是用户偏好：首推若含（WE 存储的覆盖值）立即采纳，重启后仍保持
        if (properties.voice) voiceOn = !!properties.voice.value
        if (properties.playintro) introOn = !!properties.playintro.value
        if (properties.interact) interactOn = !!properties.interact.value
        return
      }
      if (properties.scalectrl) scale = WL.clampScale(properties.scalectrl.value)
      if (properties.offsetx) ox = WL.clampOffset(properties.offsetx.value)
      if (properties.offsety) oy = WL.clampOffset(properties.offsety.value)
      if (properties.alignment) alignment = WL.ALIGN_ORDER[properties.alignment.value] || alignment
      if (properties.voice) {
        voiceOn = !!properties.voice.value
        // 关语音立即停掉正在播放的 cue
        if (!voiceOn && voiceAudio) {
          voiceAudio.pause()
          voiceAudio = null
        }
      }
      if (properties.playintro) introOn = !!properties.playintro.value
      if (properties.interact) {
        interactOn = !!properties.interact.value
        // 互动开关实时生效；模型未就绪（interaction 未创建）时由 start() 按 interactOn 初始化
        if (interaction) interaction.setEnabled(interactOn)
      }
      if (model) applyLayout()
    } catch (e) {}
  },
}

window.__captureCanvasDataURL = function () {
  try {
    return document.getElementById('canvas').toDataURL('image/png')
  } catch (e) {
    return ''
  }
}

window.addEventListener('resize', () => { if (model) applyLayout() })
start().catch((e) => { document.title = 'ERR ' + e.message })
