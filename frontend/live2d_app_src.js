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
  initW = model.width
  initH = model.height
  applyLayout()
  try {
    const meta = await (await fetch(cfg.model)).json()
    const groups = Object.keys(meta.Motions || {})
    if (groups.length) model.motion(groups[0], 0)
  } catch (e) { /* 无动作不影响显示 */ }
}

window.wallpaperPropertyListener = {
  applyUserProperties: function (properties) {
    try {
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
