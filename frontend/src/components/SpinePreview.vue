<template>
  <canvas ref="canvasRef" class="spine-canvas"></canvas>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl } from '../bridge'
import '../../../templates/wallpaper-layout.js'

const WL = window.WallpaperLayout

const props = defineProps({
  skin: { type: Object, required: true },
  animation: { type: String, default: '' },
  scale: { type: Number, default: 100 },
  offsetX: { type: Number, default: 0 },
  offsetY: { type: Number, default: 0 },
  alignment: { type: String, default: 'center' },
})
const emit = defineEmits(['ready', 'error', 'animations', 'scaleChange', 'panChange'])

const canvasRef = ref(null)

let gl = null
let renderer = null
let layers = []
let raf = 0
let lastFrame = 0
let disposed = false
let boundsCache = null
let drag = null

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v))
}

function parseAtlasPages(text) {
  return [...text.matchAll(/^([^\r\n]+\.png)\s*$/gm)].map((m) => m[1])
}

async function loadLayer(cfg) {
  const base = assetUrl(props.skin.asset.dir)
  const atlasText = await (await fetch(`${base}/${cfg.atlas}`)).text()
  const pages = parseAtlasPages(atlasText)
  const images = {}
  await Promise.all(
    pages.map((p) => {
      return new Promise((resolve, reject) => {
        const img = new Image()
        img.onload = () => {
          images[p] = img
          resolve()
        }
        img.onerror = () => reject(new Error(`texture load failed: ${p}`))
        img.src = `${base}/${p}`
      })
    }),
  )
  const texMap = {}
  // Azur Lane 贴图本身是预乘 alpha（RGB ≤ alpha），必须原样上传；
  // 若设 true 会被浏览器再乘一次 alpha，半透明像素整体变暗（灰线/黑块/光效发黑）。
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
  for (const p of pages) texMap[p] = new spine.webgl.GLTexture(gl, images[p])

  const atlas = new spine.TextureAtlas(atlasText, (page) => texMap[page] || null)
  const loader = new spine.AtlasAttachmentLoader(atlas)
  const skelBuf = await (await fetch(`${base}/${cfg.skel}`)).arrayBuffer()
  const data = new spine.SkeletonBinary(loader).readSkeletonData(new Uint8Array(skelBuf))
  const skeleton = new spine.Skeleton(data)
  skeleton.setSkin(data.defaultSkin || data.skins[0])
  skeleton.setSlotsToSetupPose()
  skeleton.updateWorldTransform()
  const state = new spine.AnimationState(new spine.AnimationStateData(data))
  return { skeleton, state, data }
}

function pickAnim(data) {
  const names = data.animations.map((a) => a.name)
  const idle = names.find((n) => /idle/i.test(n)) || names.find((n) => n === 'normal')
  return idle || names[0] || ''
}

function playAnimation(name) {
  if (!layers.length) return
  for (const l of layers) {
    const target = name && l.data.animations.some((a) => a.name === name) ? name : pickAnim(l.data)
    if (target) l.state.setAnimation(0, target, true)
  }
}

function layerBounds(l) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const slot of l.skeleton.slots) {
    const att = slot.getAttachment()
    if (!att) continue
    // 透明插槽（动画初始不可见的部分）与 kkkkk 位置标记附件不参与取景，
    // 否则会把包围盒撑到巨大、角色被“挤”出视野（云龙-溶于重重夜色 的典型问题）
    if (slot.color && slot.color.a < 0.01) continue
    if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
    const isRegion = att instanceof spine.RegionAttachment
    if (!isRegion && !(att instanceof spine.MeshAttachment) && !(att instanceof spine.BoundingBoxAttachment)) continue
    const len = isRegion ? 8 : att.worldVerticesLength
    if (!len) continue
    const verts = spine.Utils.newFloatArray(len)
    if (isRegion) att.computeWorldVertices(slot.bone, verts, 0, 2)
    else att.computeWorldVertices(slot, 0, len, verts, 0, 2)
    for (let j = 0; j < len; j += 2) {
      if (verts[j] < minX) minX = verts[j]
      if (verts[j] > maxX) maxX = verts[j]
      if (verts[j + 1] < minY) minY = verts[j + 1]
      if (verts[j + 1] > maxY) maxY = verts[j + 1]
    }
  }
  return { minX, maxX, minY, maxY }
}

function contentFrame() {
  // 按附件面积加权的网格密度取景：只框住“内容密集”区域，
  // 用于骨架包围盒被大面积背景网格/稀疏光效撑爆、角色被“挤”小的皮肤
  const raw = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
  const items = []
  for (const l of layers) {
    for (const slot of l.skeleton.slots) {
      const att = slot.getAttachment()
      if (!att) continue
      if (slot.color && slot.color.a < 0.01) continue
      if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
      const isRegion = att instanceof spine.RegionAttachment
      const isMesh = att instanceof spine.MeshAttachment
      if (!isRegion && !isMesh) continue
      const len = isRegion ? 8 : att.worldVerticesLength
      if (!len) continue
      const verts = spine.Utils.newFloatArray(len)
      if (isRegion) att.computeWorldVertices(slot.bone, verts, 0, 2)
      else att.computeWorldVertices(slot, 0, len, verts, 0, 2)
      const b = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
      for (let j = 0; j < len; j += 2) {
        if (verts[j] < b.minX) b.minX = verts[j]
        if (verts[j] > b.maxX) b.maxX = verts[j]
        if (verts[j + 1] < b.minY) b.minY = verts[j + 1]
        if (verts[j + 1] > b.maxY) b.maxY = verts[j + 1]
      }
      items.push(b)
      if (b.minX < raw.minX) raw.minX = b.minX
      if (b.maxX > raw.maxX) raw.maxX = b.maxX
      if (b.minY < raw.minY) raw.minY = b.minY
      if (b.maxY > raw.maxY) raw.maxY = b.maxY
    }
  }
  if (!items.length) return null
  const rawW = raw.maxX - raw.minX
  const rawH = raw.maxY - raw.minY
  const N = 64
  const gw = rawW / N || 1
  const gh = rawH / N || 1
  const grid = new Float64Array(N * N)
  for (const b of items) {
    const cx = (b.minX + b.maxX) / 2
    const cy = (b.minY + b.maxY) / 2
    const gx = Math.min(N - 1, Math.max(0, Math.floor((cx - raw.minX) / gw)))
    const gy = Math.min(N - 1, Math.max(0, Math.floor((cy - raw.minY) / gh)))
    grid[gy * N + gx] += Math.max(1, (b.maxX - b.minX) * (b.maxY - b.minY))
  }
  let maxCell = 0
  for (const v of grid) if (v > maxCell) maxCell = v
  if (!maxCell) return null
  const threshold = maxCell * 0.02
  let fminX = raw.maxX, fmaxX = raw.minX, fminY = raw.maxY, fmaxY = raw.minY, kept = 0
  for (let gy = 0; gy < N; gy++) {
    for (let gx = 0; gx < N; gx++) {
      if (grid[gy * N + gx] >= threshold) {
        kept++
        if (raw.minX + gx * gw < fminX) fminX = raw.minX + gx * gw
        if (raw.minX + (gx + 1) * gw > fmaxX) fmaxX = raw.minX + (gx + 1) * gw
        if (raw.minY + gy * gh < fminY) fminY = raw.minY + gy * gh
        if (raw.minY + (gy + 1) * gh > fmaxY) fmaxY = raw.minY + (gy + 1) * gh
      }
    }
  }
  const fW = fmaxX - fminX
  const fH = fmaxY - fminY
  const ratioW = fW / rawW
  const ratioH = fH / rawH
  // 只有内容明显小于原始包围盒时才裁剪（正常皮肤内容≈包围盒，不受影响）
  if (!kept || ratioW > 0.55 || ratioH > 0.55 || ratioW < 0.08 || ratioH < 0.08) return null
  const padX = fW * 0.15
  const padY = fH * 0.15
  return { minX: fminX - padX, maxX: fmaxX + padX, minY: fminY - padY, maxY: fmaxY + padY }
}

function computeBounds() {
  // 边界只算一次并缓存：动画帧里的超大特效部件会瞬间撑爆边界，
  // 导致拖拽/缩放时相机拉远出现“全屏虚影”。
  if (boundsCache) return boundsCache
  const dense = contentFrame()
  if (dense) {
    boundsCache = dense
    return boundsCache
  }
  // 多部件皮肤（角色+背景）中，背景层面积远大于主体层；取景只按主体层算，
  // 背景/特效层照常渲染但不参与取景，避免角色被巨大的背景“挤”出视野。
  const per = layers.map(layerBounds).filter((b) => Number.isFinite(b.minX))
  if (!per.length) {
    boundsCache = { minX: -1, maxX: 1, minY: -1, maxY: 1 }
    return boundsCache
  }
  let small = per[0]
  for (const b of per) {
    const a = (b.maxX - b.minX) * (b.maxY - b.minY)
    const ra = (small.maxX - small.minX) * (small.maxY - small.minY)
    if (a < ra) small = b
  }
  const baseArea = (small.maxX - small.minX) * (small.maxY - small.minY) || 1
  const frame = per.filter((b) => (b.maxX - b.minX) * (b.maxY - b.minY) <= baseArea * 4)
  boundsCache = {
    minX: Math.min(...frame.map((b) => b.minX)),
    maxX: Math.max(...frame.map((b) => b.maxX)),
    minY: Math.min(...frame.map((b) => b.minY)),
    maxY: Math.max(...frame.map((b) => b.maxY)),
  }
  return boundsCache
}

function applyLayout() {
  const canvas = canvasRef.value
  const cw = canvas.clientWidth
  const ch = canvas.clientHeight
  if (!cw || !ch || !layers.length || !renderer) return // 布局未就绪时跳过，避免除零/无穷大
  const a = WL.anchor(props.alignment)
  const cam = WL.spineCamera(computeBounds(), cw, ch, {
    scale: props.scale,
    offsetX: props.offsetX,
    offsetY: props.offsetY,
    alignX: a.x,
    alignY: a.y,
  })
  renderer.camera.zoom = cam.zoom
  renderer.camera.position.x = cam.x
  renderer.camera.position.y = cam.y
  renderer.camera.position.z = 0
}

function render() {
  if (disposed) return
  const now = performance.now() / 1000
  const delta = Math.min(0.1, now - lastFrame)
  lastFrame = now
  const canvas = canvasRef.value
  if (canvas.width !== canvas.clientWidth || canvas.height !== canvas.clientHeight) {
    canvas.width = canvas.clientWidth
    canvas.height = canvas.clientHeight
    gl.viewport(0, 0, canvas.width, canvas.height)
    renderer.camera.setViewport(canvas.width, canvas.height)
    applyLayout()
  }
  for (const l of layers) {
    l.state.update(delta)
    l.state.apply(l.skeleton)
    l.skeleton.updateWorldTransform()
  }
  gl.clearColor(0, 0, 0, 0)
  gl.clear(gl.COLOR_BUFFER_BIT)
  renderer.begin()
  for (const l of layers) renderer.drawSkeleton(l.skeleton, true)
  renderer.end()
  raf = requestAnimationFrame(render)
}

watch(
  () => [props.scale, props.offsetX, props.offsetY, props.alignment],
  () => applyLayout(),
)

watch(
  () => props.animation,
  (v) => v && playAnimation(v),
)

function enableInteraction() {
  const canvas = canvasRef.value
  canvas.style.cursor = 'grab'
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault()
    const factor = Math.pow(1.1, -e.deltaY / 100)
    const next = WL.clampScale(props.scale * factor)
    emit('scaleChange', Math.round(next))
  }, { passive: false })
  canvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return
    e.preventDefault()
    drag = {
      x: e.clientX,
      y: e.clientY,
      ox: props.offsetX,
      oy: props.offsetY,
      camX: renderer.camera.position.x,
      camY: renderer.camera.position.y,
      zoom: renderer.camera.zoom,
    }
    canvas.style.cursor = 'grabbing'
  })
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

function onMove(e) {
  if (!drag) return
  drag.lastX = e.clientX
  drag.lastY = e.clientY
  // 像素级直拖：和 Live2D 一样跟手（屏幕坐标 → 世界坐标换算）
  const cam = renderer.camera
  const dx = e.clientX - drag.x
  const dy = e.clientY - drag.y
  cam.position.x = drag.camX - dx * drag.zoom
  cam.position.y = drag.camY + dy * drag.zoom
  cam.position.z = 0
}

function onUp() {
  if (!drag) return
  const canvas = canvasRef.value
  const cw = canvas.clientWidth || 1
  const ch = canvas.clientHeight || 1
  const lx = drag.lastX != null ? drag.lastX : drag.x
  const ly = drag.lastY != null ? drag.lastY : drag.y
  const ox = Math.round(WL.clampOffset(drag.ox + ((lx - drag.x) / cw) * 100))
  const oy = Math.round(WL.clampOffset(drag.oy + ((ly - drag.y) / ch) * 100))
  drag = null
  canvas.style.cursor = 'grab'
  emit('panChange', { x: ox, y: oy })
}

onMounted(async () => {
  try {
    const canvas = canvasRef.value
    canvas.width = canvas.clientWidth
    canvas.height = canvas.clientHeight
    gl =
      canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: true }) ||
      canvas.getContext('experimental-webgl', { alpha: true })
    if (!gl) throw new Error('WebGL not supported')
    renderer = new spine.webgl.SceneRenderer(canvas, gl, false)
    const cfgs = props.skin.asset.layers || []
    const loaded = await Promise.all(cfgs.map((c) => loadLayer(c)))
    layers = loaded
    playAnimation(props.animation || '')
    // 把动画推进到 t=0，用初始姿态构建稳定的边界缓存
    for (const l of layers) {
      l.state.update(0)
      l.state.apply(l.skeleton)
      l.skeleton.updateWorldTransform()
    }
    computeBounds()
    const anims = [...new Set(loaded.flatMap((l) => l.data.animations.map((a) => a.name)))]
    emit('animations', anims)
    applyLayout()
    enableInteraction()
    lastFrame = performance.now() / 1000
    emit('ready')
    raf = requestAnimationFrame(render)
  } catch (e) {
    emit('error', e.message || String(e))
  }
})

onBeforeUnmount(() => {
  disposed = true
  cancelAnimationFrame(raf)
  raf = 0
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  if (gl && renderer) renderer.dispose()
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
.spine-canvas {
  width: 100%;
  height: 100%;
  display: block;
  touch-action: none;
  user-select: none;
}
</style>
