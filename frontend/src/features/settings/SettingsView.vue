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
      <n-card title="下载目录" size="small" class="wc-card">
        <p class="dim">下载的 AssetBundle 与提取产物保存在软件资源目录。</p>
        <div class="row">
          <n-button size="small" secondary @click="openDir('download')">打开下载目录</n-button>
          <n-button size="small" secondary @click="openDir('extracted')">打开提取目录</n-button>
        </div>
      </n-card>

      <n-card title="壁纸导出" size="small" class="wc-card">
        <div class="row">
          <n-button size="small" type="primary" :loading="openingWe" @click="openWe">
            打开壁纸文件夹
          </n-button>
          <n-popconfirm @positive-click="cleanExports" positive-text="清理" negative-text="取消">
            <template #trigger>
              <n-button size="small" type="error" secondary :loading="cleaningExports">
                清理导出目录
              </n-button>
            </template>
            将删除 resources/wallpapers 与 resources/exports 下所有导出的壁纸项目与截图，确定吗？
          </n-popconfirm>
          <span class="dim">清理后需重新导出壁纸</span>
        </div>
      </n-card>

      <n-card title="网络" size="small" class="wc-card">
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

      <n-card title="外观主题" size="small" class="wc-card">
        <div class="field">
          <label>界面主题</label>
          <div class="theme-picker">
            <div
              v-for="t in themeOptions"
              :key="t.key"
              class="theme-opt"
              :class="{ active: themeKey === t.key }"
              @click="setTheme(t.key)"
            >
              <span class="theme-swatch" :class="'theme-swatch-' + t.key"></span>
              <span class="theme-name">{{ t.label }}</span>
              <span class="theme-check" :class="{ show: themeKey === t.key }">✓</span>
            </div>
          </div>
          <span class="dim">切换立即生效，选择会保存；少女漫画风含樱花粉、网点与花朵元素。</span>
        </div>
      </n-card>

      <n-card title="提示音" size="small" class="wc-card">
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

      <n-card title="语音" size="small" class="wc-card">
        <div class="field">
          <n-checkbox v-model:checked="voiceDownload">
            下载 Live2D 皮肤语音（仅 L2D 皮肤，下载时同步下载该船互动语音）
          </n-checkbox>
          <span class="dim">语音来自官方 CDN，按船下载；互动点击（点头/身/特、登录、待机）会播放对应台词。Spine / 静态立绘不下载语音，避免额外耗时。</span>
        </div>
        <div class="row">
          <n-button size="small" secondary :loading="voiceBackfilling" @click="doVoiceBackfill">
            为已下载皮肤补下语音
          </n-button>
          <span class="dim">已下载的 Live2D 皮肤可一键补下其所在船的语音</span>
        </div>
        <div class="row">
          <n-button size="small" :loading="voiceCleaning" @click="doVoiceClean(false)">
            清理语音
          </n-button>
          <n-button size="small" quaternary type="error" :loading="voiceCleaning" @click="doVoiceClean(true)">
            全部删除
          </n-button>
          <span class="dim">清理：删除「没有已下载 L2D 皮肤」的船的语音；全部删除：清空所有语音（需确认）</span>
        </div>
        <div v-if="voiceDlStage" class="voice-dl-stage">{{ voiceDlStage }}</div>
      </n-card>

      <n-card title="数据更新" size="small" class="wc-card">
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

      <n-card title="已下载资源" size="small" class="wc-card span-2">
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

      <n-card title="插件" size="small" class="wc-card">
        <div v-for="group in pluginGroups" :key="group.title" class="plugin-group">
          <div class="group-title">{{ group.title }}</div>
          <div v-for="p in group.items" :key="p.id" class="plugin-row">
            <span>{{ p.name }}</span>
            <n-tag size="small" :bordered="false" type="success">已启用</n-tag>
          </div>
        </div>
      </n-card>

      <n-card title="关于" size="small" class="wc-card">
        <div class="about">
          <div class="about-head">
            <span class="about-logo">⚓</span>
            <div class="about-title">
              <div class="about-name">碧蓝航线动态壁纸工具</div>
              <div class="about-version">v0.1.0（M1）</div>
            </div>
          </div>
          <p class="about-desc">
            从官方资源通道下载并提取 <b>Spine 动态立绘</b> 与 <b>Live2D 皮肤</b>，在图鉴式 Web 界面中预览，
            导出为 Wallpaper Engine 壁纸项目，一键应用到桌面。
          </p>
          <div class="about-sec">功能特性</div>
          <ul class="about-list">
            <li>Spine 动态立绘（支持 _T 人物 / _B 背景 / _M 舰装多骨架分层合并）</li>
            <li>Live2D 皮肤（Cubism 3）与静态立绘碎片重组合成</li>
            <li>官方 CDN 抓取 + AssetBundle 本地解包提取（TCP 握手协议）</li>
            <li>本地导入已解包资源，图鉴式预览（取色 / 莫奈 / 毛玻璃 / 星空等背景）</li>
            <li>L2D 互动：点击头 / 身 / 特殊区域播放动画与角色语音台词</li>
            <li>导出 Wallpaper Engine 壁纸项目（project.json 原生属性 + 一键应用）</li>
          </ul>
          <div class="about-sec">技术栈</div>
          <p class="about-desc">
            桌面外壳 pywebview + WebView2 · 后端 Python 3.12 插件化（sources / extractors / exporters）·
            前端 Vue 3 + Vite + Naive UI · Spine 用 spine-ts 3.8 WebGL 运行时 ·
            Live2D 用 Cubism Web SDK（pixi-live2d-display）· 资源全部自提取。
          </p>
          <div class="about-foot">Windows 10 / 11 · 资源仅供个人学习交流使用</div>
        </div>
      </n-card>
    </div>
  </div>
</template>

<script setup>
import { computed, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NCard, NInput, NSelect, NSlider, NButton, NTag, NSpin, NEmpty, NPopconfirm, NCheckbox, useMessage } from 'naive-ui'
import { bridge, sseUrl } from '../../bridge'
import { themeKey, setTheme, THEMES } from '../../utils/theme'
import { TIMBRES, getSoundPrefs, playChime, setSoundPrefs, warmAudio } from '../../utils/sound'

const route = useRoute()
const router = useRouter()

const message = useMessage()
const themeOptions = THEMES
const proxy = ref('')
const concurrency = ref(parseInt(localStorage.getItem('azl_concurrency') || '4', 10) || 4)
const downloaded = ref([])
const loading = ref(false)
const clearing = ref(false)
const openingWe = ref(false)
const cleaningExports = ref(false)
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
const voiceDownload = ref(false)
const voiceBackfilling = ref(false)
const voiceCleaning = ref(false)
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
      voiceDownload.value = !!res.config.voice_download
    }
  } catch (e) {
    /* 后端未启动时忽略，代理保持空 */
  }
}

// 语音下载开关：修改后保存到后端配置（立即生效于下一次下载）
let voiceTimer = null
watch(voiceDownload, (v) => {
  clearTimeout(voiceTimer)
  voiceTimer = setTimeout(() => {
    bridge.setConfig({ voice_download: !!v })
  }, 400)
})

const voiceDlStage = ref('')
let voiceDlSource = null

async function doVoiceBackfill() {
  voiceBackfilling.value = true
  voiceDlStage.value = '正在连接后端…'
  // SSE：实时显示 正在下载语音：船 X（i/N）/ 正在解码语音 等阶段（后端不支持时静默降级）
  try {
    voiceDlSource = new EventSource(sseUrl())
    voiceDlSource.addEventListener('stage', (e) => {
      try {
        const d = JSON.parse(e.data)
        const detail = d.progress ? `${d.detail || ''}（${d.progress}）` : (d.detail || '')
        voiceDlStage.value = detail ? `${d.stage}：${detail}` : (d.stage || '')
      } catch (err) {
        /* 忽略异常事件 */
      }
    })
  } catch (e) {
    /* SSE 不可用时仅按钮 loading，不阻塞补下流程 */
  }
  try {
    const res = await bridge.voiceBackfill()
    if (res && res.ok) {
      message.success(`语音补齐完成：新下载 ${res.downloaded} 艘，跳过 ${res.skipped} 艘`)
      voiceDlStage.value = ''
    } else {
      message.error(`语音补齐失败：${(res && res.error) || '未知错误'}`)
    }
  } catch (e) {
    message.error(`语音补齐失败：${e.message || e}`)
  } finally {
    if (voiceDlSource) {
      voiceDlSource.close()
      voiceDlSource = null
    }
    voiceBackfilling.value = false
    // 下载完成但仍显示最后阶段 3 秒，方便用户看清收尾动作
    if (voiceDlStage.value) {
      setTimeout(() => { voiceDlStage.value = '' }, 3000)
    }
  }
}

// 清理语音：默认只清「没有已下载 L2D 皮肤」的船的语音；all=true 全部删除（需确认）
async function doVoiceClean(all) {
  if (all && !window.confirm('确定删除全部已下载语音吗？此操作不可恢复。')) return
  voiceCleaning.value = true
  try {
    const res = await bridge.voiceClean(all)
    if (res && res.ok) {
      message.success(`语音清理完成：删除 ${res.removed_ships} 艘船的语音（${res.removed_files} 个文件）`)
    } else {
      message.error(`语音清理失败：${(res && res.error) || '未知错误'}`)
    }
  } catch (e) {
    message.error(`语音清理失败：${e.message || e}`)
  } finally {
    voiceCleaning.value = false
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

async function openWe() {
  openingWe.value = true
  try {
    const res = await bridge.openWallpapersDir()
    if (res && res.ok) message.success('已打开壁纸文件夹')
    else message.error((res && res.error) || '打开失败')
  } finally {
    openingWe.value = false
  }
}

async function cleanExports() {
  cleaningExports.value = true
  try {
    const res = await bridge.cleanExports()
    if (res && res.ok) message.success(`已清理 ${res.removed} 个导出文件/目录`)
    else message.error((res && res.error) || '清理失败')
  } finally {
    cleaningExports.value = false
  }
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
  clearTimeout(voiceTimer)
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
  padding: 7px 16px;
  border-radius: 999px;
}

.page-nav-btn.active {
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(133, 205, 202, 0.14));
  border-color: rgba(74, 111, 165, 0.55);
  color: #3a5a88;
  box-shadow: 0 4px 16px rgba(74, 111, 165, 0.14);
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

.voice-dl-stage {
  margin-top: 8px;
  padding: 8px 12px;
  background: rgba(255, 215, 122, 0.12);
  border: 1px solid rgba(255, 215, 122, 0.4);
  border-radius: 10px;
  font-size: 12px;
  color: #b07a3a;
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

/* ---- 水彩卡片皮肤：对齐主页面右侧 .panel-card 观感 ---- */
.wc-card {
  background: rgba(255, 255, 255, 0.6) !important;
  border: 1px solid var(--line) !important;
  border-radius: 14px !important;
  box-shadow: var(--shadow-soft) !important;
}
.wc-card > .n-card-header {
  padding: 14px 16px 10px;
}
.wc-card > .n-card-header .n-card-header__main {
  color: var(--ink);
  font-family: var(--font-serif);
  font-weight: 300;
  letter-spacing: 2px;
  font-size: 14px;
}
.wc-card > .n-card__content {
  padding: 6px 16px 16px;
  color: var(--ink);
}

/* 设置页顶部大标题与主页一致 */
.page-header h1 {
  font-family: var(--font-serif);
  font-weight: 300;
  letter-spacing: 4px;
  font-size: 22px;
}

/* Naive 输入框水彩化（纸感浅底已在全局 themeOverrides，这里强化边框） */
.wc-card .n-input, .wc-card .n-select, .wc-card .n-input-number {
  --n-border: 1px solid rgba(74, 111, 165, 0.28);
  --n-border-hover: 1px solid rgba(74, 111, 165, 0.55);
  --n-border-focus: 1px solid rgba(74, 111, 165, 0.7);
}

/* checkbox 与标签颜色统一 */
.wc-card .n-checkbox__label {
  color: var(--ink);
  font-weight: 300;
}

/* ---- 主题选择器 ---- */
.theme-picker {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.theme-opt {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  flex: 1;
  min-width: 140px;
  padding: 10px 16px;
  border-radius: 14px;
  border: 1.5px solid rgba(74, 111, 165, 0.25);
  background: rgba(255, 255, 255, 0.7);
  cursor: pointer;
  user-select: none;
  transition: border-color 0.3s ease-out, box-shadow 0.3s ease-out, background 0.3s ease-out;
}
.theme-opt:hover {
  border-color: rgba(74, 111, 165, 0.5);
  box-shadow: var(--shadow-soft);
}
.theme-opt.active {
  border-color: rgba(74, 111, 165, 0.6);
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.1), rgba(133, 205, 202, 0.1));
  box-shadow: var(--shadow-soft);
}
.theme-swatch {
  width: 26px;
  height: 26px;
  flex: none;
  border-radius: 50%;
  border: 1px solid rgba(120, 120, 120, 0.25);
}
.theme-swatch-watercolor {
  background:
    radial-gradient(60% 60% at 30% 30%, rgba(74, 111, 165, 0.85), transparent 70%),
    radial-gradient(60% 60% at 70% 65%, rgba(133, 205, 202, 0.85), transparent 70%),
    linear-gradient(135deg, #faf8f5, #f0ebe3);
}
.theme-swatch-shoujo {
  background:
    radial-gradient(60% 60% at 30% 30%, rgba(255, 183, 197, 0.9), transparent 70%),
    radial-gradient(60% 60% at 70% 65%, rgba(196, 181, 253, 0.9), transparent 70%),
    linear-gradient(135deg, #fff5f7, #ffe9ee);
}
.theme-swatch-cyberpunk {
  background:
    radial-gradient(60% 60% at 30% 30%, rgba(34, 211, 238, 0.95), transparent 70%),
    radial-gradient(60% 60% at 70% 65%, rgba(232, 121, 249, 0.9), transparent 70%),
    linear-gradient(135deg, #0a0a0f, #0d0d15);
}
.theme-swatch-solarpunk {
  background:
    radial-gradient(60% 60% at 30% 30%, rgba(74, 222, 128, 0.95), transparent 70%),
    radial-gradient(60% 60% at 70% 65%, rgba(251, 191, 36, 0.9), transparent 70%),
    linear-gradient(135deg, #f0fdf4, #dcfce7);
}
.theme-name {
  font-size: 13px;
  letter-spacing: 1px;
  color: var(--ink);
}
.theme-check {
  margin-left: auto;
  width: 14px;
  flex: none;
  color: var(--blue);
  font-weight: 600;
  font-size: 13px;
  opacity: 0;
  transition: opacity 0.2s ease-out;
}
.theme-check.show {
  opacity: 1;
}
body.theme-shoujo .theme-opt {
  border-color: rgba(255, 183, 197, 0.35);
  background: #fff;
}
body.theme-shoujo .theme-opt.active {
  border-color: rgba(244, 114, 160, 0.6);
  background: linear-gradient(135deg, rgba(255, 183, 197, 0.18), rgba(196, 181, 253, 0.14));
}
body.theme-shoujo .theme-check {
  color: #f472a0;
}

/* ---- 关于卡片 ---- */.about-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.about-logo {
  width: 44px;
  height: 44px;
  flex: none;
  display: grid;
  place-items: center;
  font-size: 22px;
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(74, 111, 165, 0.16), rgba(133, 205, 202, 0.18));
  border: 1px solid rgba(74, 111, 165, 0.3);
  box-shadow: var(--shadow-soft);
}
.about-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.about-name {
  font-family: var(--font-serif);
  font-size: 16px;
  letter-spacing: 2px;
  color: var(--ink);
}
.about-version {
  font-size: 11.5px;
  letter-spacing: 1px;
  color: var(--gold-deep, #a8862f);
  background: rgba(201, 168, 76, 0.16);
  display: inline-flex;
  align-items: center;
  padding: 1px 10px;
  border-radius: 999px;
  width: fit-content;
}
.about-desc {
  margin: 0 0 10px;
  font-size: 12.5px;
  line-height: 1.8;
  color: var(--ink);
}
.about-desc b {
  font-weight: 400;
  color: var(--blue);
}
.about-sec {
  font-size: 11.5px;
  letter-spacing: 2px;
  color: var(--muted);
  margin: 12px 0 6px;
  padding-bottom: 5px;
  border-bottom: 1px dashed rgba(74, 111, 165, 0.25);
}
.about-list {
  margin: 0;
  padding-left: 18px;
  font-size: 12.5px;
  line-height: 2;
  color: var(--ink);
}
.about-list li::marker {
  color: var(--blue);
}
.about-foot {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed rgba(74, 111, 165, 0.25);
  font-size: 11px;
  letter-spacing: 1px;
  color: var(--muted);
}
</style>
