// 前端与后端的统一通信层。
// 浏览器预览模式（无 pywebview）时数据读本地元数据、动作走本地后端 API。

const isPywebview = () => typeof window !== 'undefined' && !!window.pywebview

// 开发模式下预览素材走 Vite 的 /@fs/，需要磁盘绝对路径；路径集中在
// .env.development 的 VITE_DEV_RESOURCES 配置，换机器开发只需改 env 文件。
const DEV_RESOURCES = import.meta.env.VITE_DEV_RESOURCES || ''
// 打包版通过 .env.packaged 的 VITE_API_BASE 指向自己的后端端口，避免连到开发版后端
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8766'

const API_ACTIONS = {
  downloadSkin: { path: '/api/download', method: 'POST' },
  cancelDownload: { path: '/api/download/cancel', method: 'POST' },
  deleteSkin: { path: '/api/library/delete', method: 'POST' },
  clearDownloads: { path: '/api/library/clear', method: 'POST' },
  openDownloadDir: { path: '/api/open/download-dir', method: 'POST' },
  openExtractedDir: { path: '/api/open/extracted-dir', method: 'POST' },
  listDownloaded: { path: '/api/library/downloaded', method: 'GET' },
  updateMetadata: { path: '/api/metadata/update', method: 'POST' },
  syncWiki: { path: '/api/metadata/sync-wiki', method: 'POST' },
  exportWallpaper: { path: '/api/export', method: 'POST' },
  exportImage: { path: '/api/export-image', method: 'POST' },
  exportImageData: { path: '/api/export-image-data', method: 'POST' },
  applyWallpaper: { path: '/api/apply', method: 'POST' },
  getPalette: { path: '/api/palette', method: 'POST' },
  getConfig: { path: '/api/config', method: 'GET' },
  setConfig: { path: '/api/config', method: 'POST' },
}

// pywebview 侧的方法名（Python snake_case）
const PY_API_NAMES = {
  openDownloadDir: 'open_download_dir',
  openExtractedDir: 'open_extracted_dir',
}

function bodyFor(name, args) {
  if (name === 'downloadSkin' || name === 'deleteSkin' || name === 'exportImage') {
    const [ship, bundle, skinName, downloadId] = args
    return { ship: ship || '', bundle: bundle || '', name: skinName || '', download_id: downloadId || '' }
  }
  if (name === 'exportWallpaper' || name === 'applyWallpaper') {
    const [ship, bundle, skinName, options] = args
    return { ship: ship || '', bundle: bundle || '', name: skinName || '', options: options || {} }
  }
  if (name === 'getPalette') {
    const [ship, bundle, skinName, opts] = args
    return {
      ship: ship || '',
      bundle: bundle || '',
      name: skinName || '',
      mode: (opts && opts.mode) || 'auto',
      bgColor: opts && opts.bgColor ? opts.bgColor : undefined,
    }
  }
  if (name === 'cancelDownload') {
    const [id] = args
    return { download_id: id || '' }
  }
  if (name === 'exportImageData') {
    const [ship, bundle, skinName, dataUrl, index] = args
    return { ship: ship || '', bundle: bundle || '', name: skinName || '', dataUrl: dataUrl || '', index: index || null }
  }
  if (name === 'setConfig') {
    const [cfg] = args
    return { config: cfg || {} }
  }
  return {}
}

async function callBackend(name, args) {
  const cfg = API_ACTIONS[name]
  const opts = { method: cfg.method, headers: { 'Content-Type': 'application/json' } }
  if (cfg.method === 'POST') opts.body = JSON.stringify(bodyFor(name, args))
  const resp = await fetch(`${API_BASE}${cfg.path}`, opts)
  return resp.json()
}

export const metadataUrl = (rel) =>
  import.meta.env.DEV
    ? DEV_RESOURCES
      ? `/@fs/${DEV_RESOURCES}/metadata/${rel}`
      : `resources/metadata/${rel}`
    : `resources/metadata/${rel}`
export const assetUrl = (rel) =>
  import.meta.env.DEV
    ? DEV_RESOURCES
      ? `/@fs/${DEV_RESOURCES}/${rel}`
      : `resources/${rel}`
    : `resources/${rel}`

async function call(name, ...args) {
  const mod = await import('../mock/api.js')
  // 数据方法始终读取本地元数据（浏览器/桌面通用）
  if (name === 'listShips' || name === 'getShip') return mod[name](...args)
  // 动作类：优先 pywebview 原生方法（桌面端不需要本地后端服务），否则走本地后端 API
  if (isPywebview()) {
    const py = window.pywebview && window.pywebview.api
    const pyName = PY_API_NAMES[name] || name
    if (py && typeof py[pyName] === 'function') {
      try {
        return await py[pyName](...args)
      } catch (e) {
        // 桌面桥接调用失败时返回统一错误结构，避免未捕获的 rejection 卡死界面状态
        return { ok: false, error: `桌面接口调用失败：${e.message || e}` }
      }
    }
  }
  if (API_ACTIONS[name]) {
    try {
      const result = await callBackend(name, args)
      if (['downloadSkin', 'deleteSkin', 'clearDownloads', 'updateMetadata', 'syncWiki'].includes(name)) mod.invalidateCache()
      return result
    } catch (e) {
      return { ok: false, error: `后端服务未启动（${API_BASE}）：${e.message}` }
    }
  }
  return mod[name](...args)
}

export const bridge = {
  isPywebview,
  listShips: () => call('listShips'),
  getShip: (id) => call('getShip', id),
  exportWallpaper: (ship, bundle, name, options) => call('exportWallpaper', ship, bundle, name, options),
  exportImage: (ship, bundle, name) => call('exportImage', ship, bundle, name),
  applyWallpaper: (ship, bundle, name, options) => call('applyWallpaper', ship, bundle, name, options),
  getPalette: (ship, bundle, name, opts) => call('getPalette', ship, bundle, name, opts),
  downloadSkin: (ship, bundle, name, downloadId) => call('downloadSkin', ship, bundle, name, downloadId),
  cancelDownload: (id) => call('cancelDownload', id),
  exportImageData: (ship, bundle, name, dataUrl, index) => call('exportImageData', ship, bundle, name, dataUrl, index),
  listDownloaded: () => call('listDownloaded'),
  deleteSkin: (ship, bundle, name) => call('deleteSkin', ship, bundle, name),
  clearDownloads: () => call('clearDownloads'),
  openDownloadDir: () => call('openDownloadDir'),
  openExtractedDir: () => call('openExtractedDir'),
  updateMetadata: () => call('updateMetadata'),
  syncWiki: () => call('syncWiki'),
  getConfig: () => call('getConfig'),
  setConfig: (cfg) => call('setConfig', cfg),
}
