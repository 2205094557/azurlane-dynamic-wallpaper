<template>
  <div ref="wrapRef" class="l2d-wrap">
    <canvas ref="canvasRef"></canvas>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Application } from '@pixi/app'
import { Renderer } from '@pixi/core'
import { InteractionManager } from '@pixi/interaction'
import { Ticker, TickerPlugin } from '@pixi/ticker'
import { Live2DModel } from 'pixi-live2d-display/cubism4'
import { assetUrl } from '../bridge'
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
})
const emit = defineEmits(['ready', 'error', 'animations', 'scaleChange', 'panChange'])

const wrapRef = ref(null)
const canvasRef = ref(null)

let app = null
let model = null
let motionList = []
let initW = 0
let initH = 0
let drag = null

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
}

function onResize() {
  applyLayout()
}

function playMotion(label) {
  if (!model || !motionList.length) return
  const target =
    motionList.find((m) => m.label === label) ||
    motionList.find((m) => /^idle$/i.test(m.label)) ||
    motionList.find((m) => m.label === 'home') ||
    motionList[0]
  try {
    // 切换动画前重置所有参数到默认值：上一个动作遗留的部件/表情参数
    //（如部件透明度、眨眼、表情）不会被新动作覆盖，会导致旧动作的组件
    // 残留显示在下一个动作上。
    const im = model.internalModel
    if (im?.parameters) {
      im.parameters.values.set(im.parameters.defaultValues)
    }
    // 动作被强制循环后，当前动作的 NORMAL 优先级不会复位，同优先级的新动作会被库拒绝
    //（MotionState.reserve: priority <= currentPriority 直接 return false）。
    // 切换前先停掉当前动作把状态清空（currentPriority=0），再播新的。
    im?.motionManager?.stopAllMotions?.()
    model.motion(target.group, target.index)
  } catch (e) {
    /* 动作组不存在时忽略 */
  }
}

async function load() {
  const base = assetUrl(props.skin.asset.dir)
  const modelPath = props.skin.asset.model
  const meta = await (await fetch(`${base}/${modelPath}`)).json()

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
  model = await Live2DModel.from(`${base}/${modelPath}`, { autoUpdate: true })
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
      if (m && typeof m.setIsLoop === 'function') m.setIsLoop(true)
    })
  }
  // 记录加载时的稳定模型尺寸，作为基础缩放基准
  initW = model.width
  initH = model.height
  applyLayout()
  playMotion(props.animation || '')
  emit('ready')
}

watch(
  () => [props.scale, props.offsetX, props.offsetY, props.alignment],
  () => applyLayout(),
)

watch(
  () => props.animation,
  (v) => v && playMotion(v),
)

function enableInteraction() {
  const wrap = wrapRef.value
  wrap.style.cursor = 'grab'
  wrap.addEventListener('wheel', (e) => {
    e.preventDefault()
    const factor = Math.pow(1.1, -e.deltaY / 100)
    const next = WL.clampScale(props.scale * factor)
    emit('scaleChange', Math.round(next))
  }, { passive: false })
  wrap.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return
    drag = { x: e.clientX, y: e.clientY, ox: props.offsetX, oy: props.offsetY }
    wrap.style.cursor = 'grabbing'
  })
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
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
  enableInteraction()
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
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
</style>
