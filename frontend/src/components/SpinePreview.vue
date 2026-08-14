<template>
  <canvas ref="canvasRef" class="spine-canvas"></canvas>
</template>

<script setup>
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
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
let paused = false // keep-alive 切走（onDeactivated）时暂停渲染循环
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
  // 选 skin：优先 default，但有些碧蓝皮肤的 default skin 是简略版（如
  // 阿罗芒什·足尖弓矢 default 只有脚部，skin "1"/"2" 才是完整全身）。
  // 比较各 skin 的附件数量，选可见部件最多的，保证预览显示完整角色。
  skeleton.setSkin(bestSkin(data))
  skeleton.setSlotsToSetupPose()
  skeleton.updateWorldTransform()
  const state = new spine.AnimationState(new spine.AnimationStateData(data))
  return { skeleton, state, data }
}

// 选附件最多的 skin：默认优先，同数时保持 default；遍历计数（不含透明插槽与位置标记）
function bestSkin(data) {
  const skins = data.skins || []
  if (skins.length <= 1) return data.defaultSkin || skins[0]
  let best = data.defaultSkin || skins[0]
  let bestCount = -1
  for (const sk of skins) {
    let count = 0
    const skel = new spine.Skeleton(data)
    skel.setSkin(sk)
    skel.setSlotsToSetupPose()
    skel.updateWorldTransform()
    for (const slot of skel.slots) {
      const att = slot.getAttachment()
      if (!att) continue
      if (slot.color && slot.color.a < 0.01) continue
      if ((att.name || '').toLowerCase().startsWith('kkkkk')) continue
      count++
    }
    if (count > bestCount) {
      bestCount = count
      best = sk
    }
  }
  return best
}

// 独立背景图层（*BG.png，无骨架）：加载为 Image，渲染时铺在角色层下面
async function loadBg(cfg) {
  const base = assetUrl(props.skin.asset.dir)
  const img = await new Promise((resolve, reject) => {
    const im = new Image()
    im.onload = () => resolve(im)
    im.onerror = () => reject(new Error(`bg load failed: ${cfg.bg}`))
    im.src = `${base}/${cfg.bg}`
  })
  return { bg: img, bgName: cfg.bg }
}

function pickAnim(data) {
  const names = data.animations.map((a) => a.name)
  const idle = names.find((n) => /idle/i.test(n)) || names.find((n) => n === 'normal')
  return idle || names[0] || ''
}

function playAnimation(name) {
  if (!layers.length) return
  for (const l of layers) {
    if (!l.skeleton) continue
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
    if (!l.skeleton) continue
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
  // 面积过滤兜底：contentFrame 放弃时，有些皮肤的包围盒被巨大的背景/云朵部件
  // 撑爆（如 DEAD MASTER·战士的小憩 两侧的云把宽撑到 1.2 万），角色被挤成很小。
  // 这里保留“面积 ≤ 最大附件 40%”的部件参与取景，滤掉超大背景附件；
  // 若过滤后仍占满 90% 以上或附件过少，说明不是背景撑爆，回退常规逻辑。
  const areaFrame = denseAreaFrame()
  if (areaFrame) {
    boundsCache = areaFrame
    return boundsCache
  }
  // 多部件皮肤（角色+背景）中，背景层面积远大于主体层；取景只按主体层算，
  // 背景/特效层照常渲染但不参与取景，避免角色被巨大的背景“挤”出视野。
  const per = layers.filter((l) => l.skeleton).map(layerBounds).filter((b) => Number.isFinite(b.minX))
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

// 面积过滤取景：保留面积 ≤ 最大附件 40% 的部件（跨所有层），滤掉超大背景/云朵。
// 返回 null 表示不适用（内容未被撑爆），调用方回退常规逻辑。
function denseAreaFrame() {
  const raw = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity }
  const items = []
  for (const l of layers) {
    if (!l.skeleton) continue
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
  const areas = items.map((b) => (b.maxX - b.minX) * (b.maxY - b.minY))
  const maxA = Math.max(...areas)
  // 最大附件本身就占满画面（无超大背景）时不适用
  if (maxA >= rawW * rawH * 0.8) return null
  const keep = items.filter((b, i) => areas[i] <= maxA * 0.4)
  if (!keep.length) return null
  // 在过滤后的集合上再做一次网格密度裁剪：滤掉散落的浪花/骷髅/云朵等
  // 分散装饰（如 DEAD MASTER·战士的小憩），把取景收到角色主体。
  const N = 64
  const gw = rawW / N || 1
  const gh = rawH / N || 1
  const grid = new Float64Array(N * N)
  for (const b of keep) {
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
  let fminX = raw.maxX, fmaxX = raw.minX, fminY = raw.maxY, fmaxY = raw.minY, keptCells = 0
  for (let gy = 0; gy < N; gy++) {
    for (let gx = 0; gx < N; gx++) {
      if (grid[gy * N + gx] >= threshold) {
        keptCells++
        if (raw.minX + gx * gw < fminX) fminX = raw.minX + gx * gw
        if (raw.minX + (gx + 1) * gw > fmaxX) fmaxX = raw.minX + (gx + 1) * gw
        if (raw.minY + gy * gh < fminY) fminY = raw.minY + gy * gh
        if (raw.minY + (gy + 1) * gh > fmaxY) fmaxY = raw.minY + (gy + 1) * gh
      }
    }
  }
  const fW = fmaxX - fminX
  const fH = fmaxY - fminY
  // 网格保留太少（内容过于稀疏）或过滤后仍占满 90%+：回退原逻辑
  if (!keptCells || fW >= rawW * 0.9 || fH >= rawH * 0.9) return null
  const padX = fW * 0.12
  const padY = fH * 0.12
  return { minX: fminX - padX, maxX: fmaxX + padX, minY: fminY - padY, maxY: fmaxY + padY }
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
  if (disposed || paused) return
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
    if (!l.skeleton) continue
    l.state.update(delta)
    l.state.apply(l.skeleton)
    l.skeleton.updateWorldTransform()
  }
  gl.clearColor(0, 0, 0, 0)
  gl.clear(gl.COLOR_BUFFER_BIT)
  renderer.begin()
  // 独立背景图：铺在角色层下面，覆盖整个取景框
  for (const l of layers) {
    if (!l.bg) continue
    drawBg(l.bg)
  }
  for (const l of layers) {
    if (!l.skeleton) continue
    renderer.drawSkeleton(l.skeleton, true)
  }
  renderer.end()
  raf = requestAnimationFrame(render)
}

// 背景图绘制：铺满整个画布可视区域（世界坐标）。
// 用相机反算画布对应的世界范围，背景等比 cover 铺满它。
// 关键：背景 PNG 是直通 alpha（非预乘）数据——alpha=0 的像素 RGB 仍有残留色
//（如俾斯麦Zwei 45% 透明但 RGB 均值 140+），必须用 SRC_ALPHA 混合：
// 残留 RGB × alpha(0) = 0，透明区正确透出下层；若误用 ONE（预乘混合）会把
// 残留 RGB 当不透明绘制，表现为破碎/花屏。
let bgTexCache = null

function drawBg(img) {
  if (!renderer) return
  if (!bgTexCache || bgTexCache._img !== img) {
    // 直通 alpha：原样上传（不预乘）
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)
    bgTexCache = new spine.webgl.GLTexture(gl, img)
    bgTexCache._img = img
  }
  // 背景世界尺寸 = 角色取景框（bounds），对齐取景框中心。
  // 背景图是整幅场景（角色站位居中设计），与角色骨架同一坐标系；
  // 用取景框而非"画布可视区域"，保证背景几何中心 = 角色取景中心，人物不分离。
  const bounds = computeBounds()
  const bw = bounds.maxX - bounds.minX
  const bh = bounds.maxY - bounds.minY
  if (!bw || !bh) return
  const iw = img.width || 1
  const ih = img.height || 1
  // 等比 cover 铺满取景框，再向外扩 15%（防边缘采样问题）
  const scale = (Math.max(bw / iw, bh / ih)) * 1.15
  const w = iw * scale
  const h = ih * scale
  const cx = (bounds.minX + bounds.maxX) / 2
  const cy = (bounds.minY + bounds.maxY) / 2
  // 直通 alpha 混合（透明区透出下层），画完恢复（角色 drawSkeleton 用自身混合）
  renderer.batcher.setBlendMode(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA)
  renderer.drawTexture(bgTexCache, cx - w / 2, cy - h / 2, w, h)
  renderer.batcher.setBlendMode(gl.ONE, gl.ONE_MINUS_SRC_ALPHA)
}

watch(
  () => [props.scale, props.offsetX, props.offsetY, props.alignment],
  () => applyLayout(),
)

watch(
  () => props.animation,
  (v) => v && playAnimation(v),
)

function onCanvasWheel(e) {
  e.preventDefault()
  const factor = Math.pow(1.1, -e.deltaY / 100)
  const next = WL.clampScale(props.scale * factor)
  emit('scaleChange', Math.round(next))
}

function onCanvasDown(e) {
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
  canvasRef.value.style.cursor = 'grabbing'
}

function enableInteraction() {
  const canvas = canvasRef.value
  canvas.style.cursor = 'grab'
  canvas.addEventListener('wheel', onCanvasWheel, { passive: false })
  canvas.addEventListener('mousedown', onCanvasDown)
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
    const loaded = await Promise.all(
      cfgs.map((c) => (c.bg ? loadBg(c) : loadLayer(c))),
    )
    // 卸载发生在材质加载期间：不能再用已卸载的 canvas / GL 上下文
    if (disposed) return
    layers = loaded
    // 骨架层播放动画；背景图层无骨架，跳过
    const skelLayers = loaded.filter((l) => l.skeleton)
    playAnimation(props.animation || '')
    // 把动画推进到 t=0，用初始姿态构建稳定的边界缓存
    for (const l of skelLayers) {
      l.state.update(0)
      l.state.apply(l.skeleton)
      l.skeleton.updateWorldTransform()
    }
    computeBounds()
    const anims = [...new Set(skelLayers.flatMap((l) => l.data.animations.map((a) => a.name)))]
    emit('animations', anims)
    applyLayout()
    enableInteraction()
    lastFrame = performance.now() / 1000
    emit('ready')
    raf = requestAnimationFrame(render)
  } catch (e) {
    if (!disposed) emit('error', e.message || String(e))
  }
})

// keep-alive 缓存（图鉴页）下切走时暂停渲染循环；切回时恢复
onDeactivated(() => {
  paused = true
  cancelAnimationFrame(raf)
  raf = 0
})
onActivated(() => {
  paused = false
  if (!disposed && layers.length && !raf) {
    lastFrame = performance.now() / 1000
    raf = requestAnimationFrame(render)
  }
})

onBeforeUnmount(() => {
  disposed = true
  paused = false
  cancelAnimationFrame(raf)
  raf = 0
  window.removeEventListener('mousemove', onMove)
  window.removeEventListener('mouseup', onUp)
  if (canvasRef.value) {
    canvasRef.value.removeEventListener('wheel', onCanvasWheel)
    canvasRef.value.removeEventListener('mousedown', onCanvasDown)
  }
  // 背景纹理缓存随上下文一起释放：keep-alive 复活后旧 GLTexture 指向
  // 已销毁的上下文，复用会报错/花屏
  if (bgTexCache) {
    bgTexCache.dispose?.()
    bgTexCache = null
  }
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
