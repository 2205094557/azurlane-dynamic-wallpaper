<template>
  <div class="page-wrap">
    <div class="page-header">
      <h1>设置</h1>
      <div class="page-nav">
        <button
          class="wc-btn page-nav-btn"
          :class="{ active: route.path === '/gallery' }"
          @click="router.push('/gallery')"
        >
          ⚓ 舰船图鉴
        </button>
        <button
          class="wc-btn page-nav-btn"
          :class="{ active: route.path === '/settings' }"
          @click="router.push('/settings')"
        >
          ⚙ 设置
        </button>
      </div>
    </div>

    <div class="settings-grid">
      <n-card title="下载目录" size="small">
        <p class="dim">下载的 AssetBundle 与提取产物保存在软件资源目录。</p>
        <div class="row">
          <n-button size="small" @click="openDir('download')">打开下载目录</n-button>
          <n-button size="small" @click="openDir('extracted')">打开提取目录</n-button>
        </div>
      </n-card>

      <n-card title="网络" size="small">
        <div class="field">
          <label>代理服务器</label>
          <n-input v-model:value="proxy" placeholder="http://127.0.0.1:7890（留空不使用）" />
        </div>
        <div class="field">
          <label>并发下载数</label>
          <n-slider v-model:value="concurrency" :min="1" :max="8" />
          <span class="dim">“下载全部 / 批量下载”时同时下载的皮肤数（单个下载不受影响）</span>
        </div>
      </n-card>

      <n-card title="提示音" size="small">
        <div class="field">
          <label>音色</label>
          <n-select v-model:value="soundTimbre" :options="soundOptions" size="small" />
        </div>
        <div class="field">
          <label>音量（{{ soundVolume }}%）</label>
          <n-slider v-model:value="soundVolume" :min="0" :max="100" :step="5" />
        </div>
        <div class="row">
          <n-button size="small" secondary @click="previewSound">▶ 试听</n-button>
          <span class="dim">下载完成时播放，音量 0 即静音</span>
        </div>
      </n-card>

      <n-card title="数据更新" size="small">
        <p class="dim">
          数据源为官方 CDN（新增立绘）与 B站 wiki 的
          <a href="https://wiki.biligame.com/blhx/舰船图鉴" target="_blank">舰船图鉴</a>、
          <a href="https://wiki.biligame.com/blhx/换装图鉴" target="_blank">换装图鉴</a>。
          图鉴同步会修正角色/皮肤中文名并按“换装N”顺序补齐新增内容。
        </p>
        <div class="row" style="margin-bottom: 6px">
          <n-button size="small" type="primary" :loading="updating" @click="updateData">
            检查并更新（CDN + 图鉴）
          </n-button>
          <n-button size="small" secondary :loading="syncing" @click="syncWiki">
            仅同步图鉴数据
          </n-button>
        </div>
        <div v-if="updateResult" class="update-result">
          <div class="group-title">CDN 增量</div>
          <div v-if="(updateResult.cdn_report && updateResult.cdn_report.added || []).length" class="update-added">
            <div class="update-line">新增 {{ updateResult.cdn_report.added.length }} 个皮肤</div>
            <div v-for="a in updateResult.cdn_report.added" :key="a.painting" class="update-line">
              {{ a.ship }} · {{ a.name }}（{{ a.painting }}）
            </div>
          </div>
          <div v-if="!updateResult.cdn_report" class="dim">已是最新（无新增）</div>
          <div v-if="updateResult.steps && updateResult.steps.cdn && updateResult.steps.cdn.error" class="update-error">
            {{ updateResult.steps.cdn.error }}
          </div>
        </div>
        <div v-if="syncResult" class="update-result">
          <div class="group-title">
            图鉴同步 ·
            <span class="dim">船 {{ syncResult.ships_total }} · 皮肤 {{ syncResult.skins_total }}</span>
          </div>
          <template v-if="syncResult.wiki_report">
            <div class="group-title">修正角色名 {{ (syncResult.wiki_report.renamed_ships || []).length }} 处</div>
            <div v-for="r in syncResult.wiki_report.renamed_ships" :key="r.from" class="update-line">
              {{ r.from }} → {{ r.to }}
            </div>
            <div class="group-title">修正皮肤名 {{ (syncResult.wiki_report.fixed_skins || []).length }} 处</div>
            <div v-for="r in (syncResult.wiki_report.fixed_skins || []).slice(0, 12)" :key="r.ship + r.painting" class="update-line">
              {{ r.ship }}：{{ r.from }} → {{ r.to }}
            </div>
            <div
              v-if="(syncResult.wiki_report.missing_wiki || []).length"
              class="update-review"
            >
              图鉴有但本地尚无资源 {{ syncResult.wiki_report.missing_wiki.length }} 艘（运行“检查并更新”后会自动补齐）
            </div>
          </template>
          <div v-if="syncResult.error" class="update-error">{{ syncResult.error }}</div>
        </div>
      </n-card>

      <n-card title="已下载资源" size="small" class="span-2">
        <div class="row" style="margin-bottom: 10px">
          <n-button size="small" type="primary" :loading="loading" @click="refresh">
            刷新列表
          </n-button>
          <n-input
            v-model:value="searchDl"
            placeholder="搜索舰船 / 皮肤…"
            clearable
            size="small"
            style="width: 220px"
          >
            <template #prefix>🔍</template>
          </n-input>
          <n-button size="small" secondary @click="toggleAllSel">
            {{ allSelected ? '取消全选' : '全选' }}
          </n-button>
          <n-popconfirm
            :disabled="!selCount"
            @positive-click="delSelected"
            positive-text="删除所选"
            negative-text="取消"
          >
            <template #trigger>
              <n-button size="small" type="error" secondary :loading="deletingSel" :disabled="!selCount">
                {{ deletingSel ? `删除所选 ${delDone}/${delTotal}` : `删除所选 (${selCount})` }}
              </n-button>
            </template>
            将删除选中的 {{ selCount }} 个皮肤本地文件，确定吗？
          </n-popconfirm>
          <n-popconfirm @positive-click="clearAll" positive-text="全部删除" negative-text="取消">
            <template #trigger>
              <n-button size="small" type="error" secondary :loading="clearing">
                删除全部已下载
              </n-button>
            </template>
            将删除 bundles 与 extracted 目录中的所有下载内容，且不可撤销，确定吗？
          </n-popconfirm>
          <span class="dim">
            共 {{ downloaded.length }} 个皮肤
            <span v-if="selCount"> · 已选 {{ selCount }}</span>
          </span>
        </div>
        <n-spin :show="loading">
          <div v-if="filteredDl.length" class="dl-list">
            <div
              v-for="s in filteredDl"
              :key="s.ship + s.bundle"
              class="dl-item"
              :class="{ selected: isSel(s) }"
              @click="toggleSel(s)"
            >
              <span class="dl-check" :class="{ on: isSel(s) }">✓</span>
              <span class="dl-name">{{ s.ship }} · {{ s.name }}</span>
              <span class="wc-pill" :class="pillClass(s.type)">{{ typeLabel(s.type) }}</span>
              <n-popconfirm @positive-click.stop="delOne(s)" positive-text="删除" negative-text="取消">
                <template #trigger>
                  <n-button size="tiny" quaternary type="error" @click.stop>删除</n-button>
                </template>
                删除 {{ s.ship }} · {{ s.name }} 的本地文件？
              </n-popconfirm>
            </div>
            <div v-if="downloaded.length && !filteredDl.length" class="dim" style="padding: 10px 0">
              无匹配结果
            </div>
          </div>
          <n-empty v-else description="暂无已下载皮肤" style="padding: 20px 0" />
        </n-spin>
      </n-card>

      <n-card title="插件" size="small">
        <div v-for="group in pluginGroups" :key="group.title" class="plugin-group">
          <div class="group-title">{{ group.title }}</div>
          <div v-for="p in group.items" :key="p.id" class="plugin-row">
            <span>{{ p.name }}</span>
            <n-tag size="small" :bordered="false" type="success">已启用</n-tag>
          </div>
        </div>
      </n-card>

      <n-card title="关于" size="small">
        <p class="dim">
          碧蓝航线动态壁纸工具 v0.1.0（M1）<br />
          资源全部自提取，预览后导出 Wallpaper Engine。
        </p>
      </n-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NInput, NSelect, NSlider, NButton, NTag, NSpin, NEmpty, NPopconfirm, useMessage } from 'naive-ui'
import { bridge } from '../../bridge'
import { TIMBRES, getSoundPrefs, playChime, setSoundPrefs, warmAudio } from '../../utils/sound'

const route = useRoute()
const router = useRouter()

const message = useMessage()
const proxy = ref('')
const concurrency = ref(parseInt(localStorage.getItem('azl_concurrency') || '4', 10) || 4)
const downloaded = ref([])
const loading = ref(false)
const clearing = ref(false)
const searchDl = ref('')
const selKeys = ref(new Set())
const deletingSel = ref(false)
const delDone = ref(0)
const delTotal = ref(0)
const updating = ref(false)
const updateResult = ref(null)
const syncing = ref(false)
const syncResult = ref(null)
const soundOptions = TIMBRES.map((t) => ({ label: t.name, value: t.id }))
const soundTimbre = ref(getSoundPrefs().timbre)
const soundVolume = ref(getSoundPrefs().volume)

const pluginGroups = [
  { title: '资源来源', items: [{ id: 'cdn', name: '官方 CDN' }, { id: 'local', name: '本地导入' }] },
  { title: '提取器', items: [{ id: 'spine', name: 'Spine 提取' }, { id: 'live2d', name: 'Live2D 提取' }, { id: 'static', name: '静态立绘提取' }] },
  { title: '导出器', items: [{ id: 'we-spine', name: 'Spine 壁纸导出' }, { id: 'we-l2d', name: 'Live2D 壁纸导出' }] },
]

function typeLabel(t) {
  if (t === 'spine') return 'Spine'
  if (t === 'live2d') return 'L2D'
  return '静态'
}

function pillClass(t) {
  if (t === 'live2d') return 'gold'
  if (t === 'static') return 'blue'
  return 'green'
}

watch([soundTimbre, soundVolume], () => {
  setSoundPrefs({ timbre: soundTimbre.value, volume: soundVolume.value })
})

watch(concurrency, (v) => {
  localStorage.setItem('azl_concurrency', String(v))
})

// 代理设置：读后端配置初始化，修改后防抖保存（立即生效于下一次下载）
let proxyTimer = null
watch(proxy, (v) => {
  clearTimeout(proxyTimer)
  proxyTimer = setTimeout(() => {
    bridge.setConfig({ proxy: v })
  }, 400)
})

async function loadConfig() {
  try {
    const res = await bridge.getConfig()
    if (res && res.ok && res.config) {
      proxy.value = res.config.proxy || ''
    }
  } catch (e) {
    /* 后端未启动时忽略，代理保持空 */
  }
}

function previewSound() {
  warmAudio()
  playChime()
}

const filteredDl = computed(() => {
  const kw = searchDl.value.trim().toLowerCase()
  if (!kw) return downloaded.value
  return downloaded.value.filter((s) => `${s.ship} ${s.name}`.toLowerCase().includes(kw))
})
const selCount = computed(() => selKeys.value.size)
const allSelected = computed(
  () => filteredDl.value.length > 0 && filteredDl.value.every((s) => selKeys.value.has(keyOf(s))),
)

function keyOf(s) {
  return `${s.ship}|${s.bundle}`
}

function isSel(s) {
  return selKeys.value.has(keyOf(s))
}

function toggleSel(s) {
  const k = keyOf(s)
  const set = new Set(selKeys.value)
  if (set.has(k)) set.delete(k)
  else set.add(k)
  selKeys.value = set
}

function toggleAllSel() {
  const set = new Set(selKeys.value)
  if (allSelected.value) {
    for (const s of filteredDl.value) set.delete(keyOf(s))
  } else {
    for (const s of filteredDl.value) set.add(keyOf(s))
  }
  selKeys.value = set
}

async function delSelected() {
  const targets = downloaded.value.filter((s) => selKeys.value.has(keyOf(s)))
  if (!targets.length) return
  deletingSel.value = true
  delDone.value = 0
  delTotal.value = targets.length
  let failed = 0
  for (const s of targets) {
    try {
      const res = await bridge.deleteSkin(s.ship, s.bundle, s.name)
      if (!(res && res.ok)) failed++
    } catch (e) {
      failed++
    }
    delDone.value++
  }
  deletingSel.value = false
  selKeys.value = new Set()
  await refresh()
  message.success(
    failed
      ? `删除完成：${delTotal.value - failed} 成功，${failed} 失败`
      : `已删除 ${delTotal.value} 个皮肤`,
  )
}

async function refresh() {
  loading.value = true
  try {
    const res = await bridge.listDownloaded()
    downloaded.value = (res && res.skins) || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function openDir(kind) {
  const res = kind === 'download' ? await bridge.openDownloadDir() : await bridge.openExtractedDir()
  if (res && res.ok) message.success('已打开目录')
  else message.error((res && res.error) || '打开目录失败')
}

async function delOne(s) {
  const res = await bridge.deleteSkin(s.ship, s.bundle, s.name)
  if (res && res.ok) {
    message.success(`已删除 ${s.ship} · ${s.name}`)
    await refresh()
  } else {
    message.error((res && res.error) || '删除失败')
  }
}

async function clearAll() {
  clearing.value = true
  try {
    const res = await bridge.clearDownloads()
    if (res && res.ok) {
      message.success('已清空全部下载')
      await refresh()
    } else {
      message.error((res && res.error) || '清空失败')
    }
  } finally {
    clearing.value = false
  }
}

async function updateData() {
  updating.value = true
  updateResult.value = null
  syncResult.value = null
  try {
    const res = await bridge.updateMetadata()
    updateResult.value = res
    if (res && res.ok) {
      const n = ((res.cdn_report || {}).added || []).length
      const wr = res.wiki_report || {}
      const renames = (wr.renamed_ships || []).length
      message.success(
        `CDN 新增 ${n} 个皮肤，图鉴修正 ${renames} 艘角色`,
      )
      if (res.wiki_report) syncResult.value = { ...res, wiki_report: res.wiki_report }
    } else {
      message.error((res && res.error) || '更新失败')
    }
  } catch (e) {
    message.error(`更新失败：${e.message}`)
  } finally {
    updating.value = false
  }
}

async function syncWiki() {
  syncing.value = true
  syncResult.value = null
  try {
    const res = await bridge.syncWiki()
    syncResult.value = res
    if (res && res.ok) {
      const wr = res.wiki_report || {}
      const renames = (wr.renamed_ships || []).length
      const fixes = (wr.fixed_skins || []).length
      message.success(`图鉴同步完成：修正 ${renames} 艘角色、${fixes} 个皮肤名`)
    } else {
      message.error((res && res.error) || '同步失败')
    }
  } catch (e) {
    message.error(`同步失败：${e.message}`)
  } finally {
    syncing.value = false
  }
}

onMounted(() => {
  refresh()
  loadConfig()
})
onActivated(refresh)
onBeforeUnmount(() => {
  clearTimeout(proxyTimer)
})
</script>

<style scoped>
.page-wrap {
  padding: 26px 30px 40px;
  max-width: 960px;
  margin: 0 auto;
}

.page-header h1 {
  margin: 0;
  font-family: var(--font-serif);
  font-weight: 300;
  letter-spacing: 3px;
  font-size: 24px;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.page-nav {
  display: flex;
  gap: 8px;
}

.page-nav-btn {
  padding: 7px 14px;
  border-radius: 12px;
}

.page-nav-btn.active {
  background: rgba(74, 111, 165, 0.15);
  border-color: rgba(74, 111, 165, 0.45);
  color: #4a6fa5;
}

.settings-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: 1fr 1fr;
}

.span-2 {
  grid-column: span 2;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}

.dim {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.8;
}

.row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.dl-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 320px;
  overflow-y: auto;
}

.dl-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 12px;
  border-radius: 12px;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.5);
  cursor: pointer;
  transition: all 0.25s ease-out;
}

.dl-item:hover {
  border-color: rgba(74, 111, 165, 0.4);
}

.dl-item.selected {
  border-color: rgba(74, 111, 165, 0.5);
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(180, 120, 140, 0.12));
}

.dl-check {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  border-radius: 50%;
  border: 1px solid var(--line);
  background: rgba(255, 255, 255, 0.75);
  display: grid;
  place-items: center;
  font-size: 11px;
  color: transparent;
}

.dl-check.on {
  background: rgba(74, 111, 165, 0.85);
  color: #fff;
  border-color: transparent;
}

.dl-name {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.update-result {
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.7;
}

.update-line {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.update-review {
  color: #b07a3a;
  margin-top: 6px;
}

.update-error {
  color: #c05a5a;
  margin-top: 6px;
  white-space: pre-wrap;
}

.plugin-group {
  margin-bottom: 14px;
}

.group-title {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}

.plugin-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 0;
  font-size: 14px;
}
</style>
