/*
 * 壁纸布局统一模块（预览与导出共用，单一事实来源）。
 *
 * 语义约定：
 *  - scale：百分比，100 = 自适应（contain，模型占画布 90%），20~300。
 *  - offsetX / offsetY：画布宽/高的百分比，±100。
 *  - alignX / alignY：0=左/上，0.5=居中，1=右/下（画布坐标系，Y 向下）。
 *
 * 经典脚本（无 import/export），可被导出壁纸 <script> 直接加载；
 * 前端通过副作用 import 读取 window.WallpaperLayout。
 */
(function (root) {
  'use strict'

  var MARGIN = 0.9 // 模型包围盒最多占画布 90%
  var MIN_SCALE = 20
  var MAX_SCALE = 300
  var MAX_OFFSET = 100
  var ALIGN_ORDER = ['center', 'left-top', 'right-top', 'left-bottom', 'right-bottom']
  var ALIGNMENTS = {
    center: { x: 0.5, y: 0.5 },
    'left-top': { x: 0, y: 0 },
    'right-top': { x: 1, y: 0 },
    'left-bottom': { x: 0, y: 1 },
    'right-bottom': { x: 1, y: 1 },
  }

  function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v))
  }

  function clampScale(pct) {
    return clamp(pct == null ? 100 : pct, MIN_SCALE, MAX_SCALE)
  }

  function clampOffset(pct) {
    return clamp(pct == null ? 0 : pct, -MAX_OFFSET, MAX_OFFSET)
  }

  function fitFactor(scalePct) {
    return clampScale(scalePct) / 100
  }

  function anchor(name) {
    var a = ALIGNMENTS[name || 'center']
    return a ? { x: a.x, y: a.y } : { x: 0.5, y: 0.5 }
  }

  /*
   * Spine：把模型包围盒放进画布，返回相机参数（world 坐标）。
   * zoom 为“像素/世界单位”，越大看到的区域越大、模型越小，
   * 所以缩放比例作为除数：zoom = fitZoom / scaleFactor。
   */
  function spineCamera(bounds, canvasW, canvasH, opts) {
    opts = opts || {}
    var scale = fitFactor(opts.scale)
    var ox = clampOffset(opts.offsetX)
    var oy = clampOffset(opts.offsetY)
    var ax = opts.alignX != null ? opts.alignX : 0.5
    var ay = opts.alignY != null ? opts.alignY : 0.5
    var w = Math.max(1e-3, bounds.maxX - bounds.minX)
    var h = Math.max(1e-3, bounds.maxY - bounds.minY)
    var cx = (bounds.maxX + bounds.minX) / 2
    var cy = (bounds.maxY + bounds.minY) / 2
    var fitZoom = Math.max(w / (canvasW * MARGIN), h / (canvasH * MARGIN))
    var zoom = Math.max(1e-6, fitZoom / scale)
    var slackW = canvasW * zoom - w
    var slackH = canvasH * zoom - h
    return {
      zoom: zoom,
      x: cx + (0.5 - ax) * slackW - ((ox / 100) * canvasW) * zoom,
      y: cy + (ay - 0.5) * slackH + ((oy / 100) * canvasH) * zoom,
    }
  }

  /*
   * Live2D：把模型画布（moc 尺寸）放进画布，返回模型 scale/position（锚点 0.5,0.5）。
   */
  function l2dLayout(modelW, modelH, canvasW, canvasH, opts) {
    opts = opts || {}
    var scale = fitFactor(opts.scale)
    var ox = clampOffset(opts.offsetX)
    var oy = clampOffset(opts.offsetY)
    var ax = opts.alignX != null ? opts.alignX : 0.5
    var ay = opts.alignY != null ? opts.alignY : 0.5
    var fit = Math.min(canvasW / Math.max(1, modelW), canvasH / Math.max(1, modelH)) * MARGIN
    var sx = fit * scale
    return {
      sx: sx,
      x: (modelW * sx) / 2 + ax * (canvasW - modelW * sx) + ((ox / 100) * canvasW),
      y: (modelH * sx) / 2 + ay * (canvasH - modelH * sx) + ((oy / 100) * canvasH),
    }
  }

  root.WallpaperLayout = {
    MARGIN: MARGIN,
    MIN_SCALE: MIN_SCALE,
    MAX_SCALE: MAX_SCALE,
    MAX_OFFSET: MAX_OFFSET,
    ALIGN_ORDER: ALIGN_ORDER,
    ALIGNMENTS: ALIGNMENTS,
    clampScale: clampScale,
    clampOffset: clampOffset,
    fitFactor: fitFactor,
    anchor: anchor,
    spineCamera: spineCamera,
    l2dLayout: l2dLayout,
  }
})(typeof window !== 'undefined' ? window : this)
