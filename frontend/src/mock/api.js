// M1 数据层：从 resources/metadata 读取官方元数据 + local_skins.json 标记本地已提取资源
import { metadataUrl } from '../bridge'

const delay = (ms) => new Promise((r) => setTimeout(r, ms))

function gradientFrom(name) {
  let h = 0
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)) >>> 0
  const hue = h % 360
  return [`hsl(${hue} 45% 34%)`, `hsl(${(hue + 45) % 360} 55% 12%)`]
}

let cache = null

export function invalidateCache() {
  cache = null
}

async function loadAll() {
  if (cache) return cache
  // 打包版静态服务器默认允许浏览器缓存（Last-Modified 启发式缓存）：
  // 下载/提取后 local_skins.json 会更新，若不禁用缓存会读到旧文件，
  // 导致"下载完但界面仍显示未下载、预览不出来"。统一 no-store。
  const noCache = { cache: 'no-store' }
  const [ships, skins, local] = await Promise.all([
    (await fetch(metadataUrl('ships.json'), noCache)).json(),
    (await fetch(metadataUrl('skins.json'), noCache)).json(),
    (await fetch(metadataUrl('local_skins.json'), noCache)).json(),
  ])
  const byShip = {}
  for (const s of ships) {
    byShip[s.name] = { ...s, id: s.name, gradient: gradientFrom(s.name), skins: [] }
  }
  const localByPainting = {}
  for (const l of local) {
    if (l.painting && !(l.painting in localByPainting)) localByPainting[l.painting] = l
  }
  for (const sk of skins) {
    const ship = byShip[sk.ship]
    if (!ship) continue
    // 本地资源只按 painting 精确匹配：同一 ship+bundle 下可能挂多个皮肤
    // （DOA 联动基础皮与动态皮肤 bundle 均为空），不能用 ship+bundle 回退，
    // 否则会把基础皮肤的静态资源误挂到动态皮肤上。
    const loc = sk.painting ? (localByPainting[sk.painting] || null) : null
    ship.skins.push({
      key: `${sk.ship}|${sk.bundle}|${sk.name}`,
      ship: sk.ship,
      bundle: sk.bundle,
      name: sk.name,
      theme: sk.theme || '',
      type: loc ? loc.type : sk.type || 'unknown',
      status: loc ? 'downloaded' : 'remote',
      asset: loc ? loc.asset : null,
    })
  }
  cache = Object.values(byShip)
  return cache
}

export async function listShips() {
  await delay(150)
  return (await loadAll()).map((s) => ({ ...s, skins: s.skins }))
}

export async function getShip(id) {
  await delay(100)
  return (await loadAll()).find((s) => s.name === id || s.id === String(id)) || null
}
