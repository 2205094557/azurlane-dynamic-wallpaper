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
      if (m && typeof m.setIsLoop === 'function') m.setIsLoop(true)
    })
  }
  initW = model.width
  initH = model.height
  applyLayout()
  try {
    const meta = await (await fetch(cfg.model)).json()
    const groups = Object.keys(meta.Motions || {})
    // 优先播放预览里选中的动作（按动作文件名匹配），找不到再回退到第一个动作组。
    let played = false
    if (wantAnim) {
      for (const g of groups) {
        const items = meta.Motions[g] || []
        const idx = items.findIndex((m) =>
          (m.File || '').split('/').pop().replace(/\.motion3\.json$/i, '') === wantAnim,
        )
        if (idx >= 0) {
          model.motion(g, idx)
          played = true
          break
        }
      }
    }
    if (!played && groups.length) model.motion(groups[0], 0)
  } catch (e) { /* 无动作不影响显示 */ }
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
        return
      }
      if (properties.scalectrl) scale = WL.clampScale(properties.scalectrl.value)
      if (properties.offsetx) ox = WL.clampOffset(properties.offsetx.value)
      if (properties.offsety) oy = WL.clampOffset(properties.offsety.value)
      if (properties.alignment) alignment = WL.ALIGN_ORDER[properties.alignment.value] || alignment
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
