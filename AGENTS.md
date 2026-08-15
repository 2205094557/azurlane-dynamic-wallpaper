# AGENTS.md — 碧蓝航线动态壁纸工具（azurlane-dynamic-wallpaper）

> 本文件会被 Codex / Claude Code / Cursor 等 agent 在仓库内工作时自动加载。
> 先读本文件，需要细节时再读 `docs/经验总结.md`（全部踩坑实录）。

## 项目一句话
从碧蓝航线官方 CDN 下载/提取 Spine + Live2D + 静态立绘，Web 界面预览，导出 Wallpaper Engine 壁纸。

## 常用命令
- **开发栈**：`scripts/start_dev.py`（后端 8766 + Vite 5173 + 窗口 web_main.py）。⚠️ 改后端代码后**必须重启后端进程**（Python 不热重载，本会话因此踩过 3 次"改了不生效"）。
- **打包**：`python scripts/build_pack.py`（强制 packaged 前端构建 + PyInstaller + 产物自检）。
- **发布验收**：`python tools/verify_package.py --clean`（真实下载三类皮肤、检查提取产物完整性、三种导出、并发一致性；通过后清数据重启）。
- **L2D 产物重建**：`node frontend/node_modules/vite/bin/vite.js build --config frontend/vite.live2d.config.mjs`（`templates/live2d_app_src.js` 源码 → 产物 `templates/live2d-app.js`）。
- **端口**：dev 后端 8766 / Vite 5173；打包版后端 8770 / 静态 5174。前端 API 地址只走 `VITE_API_BASE`（`.env.development` / `.env.packaged`），**永不硬编码**。

## 铁律（每一条都是真实踩过的坑）

1. **Spine 预乘 alpha**：碧蓝 Spine 贴图是预乘 alpha（RGB ≤ alpha），上传前必须 `gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false)`；设 true 会被二次相乘，半透明区变暗（灰线/黑块/光效发黑）。**独立背景 PNG（*BG.png）是直通 alpha**（alpha=0 像素 RGB 仍有残留），必须 `SRC_ALPHA` 混合，用 ONE 会花屏/破碎。
2. **多骨架分层（_T/_B/_M）**：背景层（skel 名去后缀后以 B/BG/_B/bg/_bg 结尾）必须**永远先画**——文件名排序不保证 B 在前（`duyisibao_2.skel` 排在 `duyisibao_2B.skel` 前，背景会盖住人物）。`isBgLayer`/`renderOrder` 在 `SpinePreview.vue` 和 `wallpaper_spine.html` 各有一份，**两处同步改**。
3. **取景链（computeBounds）**：背景层取景（横构图 + 面积护栏 [0.15, 8] 倍）→ `contentFrame`（网格密度）→ `denseAreaFrame`（面积过滤）→ 逐层兜底。人物高度 > 背景 1.15 倍时用 `applyCharacterFit` 等比缩到背景 70%、中心锚定（`skeleton.x = cx*(1-s)`）。预览与导出模板两处代码必须一致。
4. **WE 属性推送**：`wallpaperPropertyListener` 首次推送是历史覆盖值，**无条件跳过**（`_initialPropsApplied`），以导出内联值为准；只有用户偏好开关（语音/开场/互动）在首推里采纳并实时切换。
5. **预览=导出同步**：布局走 `templates/wallpaper-layout.js` 单一事实来源；取景/渲染逻辑在预览组件与导出模板**各抄一份**，改一处必须同步另一处（用 grep 函数名核对）。L2D：改 `live2d_app_src.js` 后必须重建 `live2d-app.js`，否则导出的还是旧逻辑。
6. **语音子进程**：vgmstream 调用必须 `creationflags=CREATE_NO_WINDOW`（否则每个 cue 闪一个黑框）+ `encoding='utf-8', errors='replace'`（系统默认 GBK 遇到日文 cue 名会 `UnicodeDecodeError` 崩掉请求线程）。
7. **前端工程**：keep-alive 只缓存 GalleryView（预览组件 `onDeactivated` 暂停渲染/语音，否则隐藏页 WebGL/rAF 常驻泄漏）；async `load()` 每个 await 后查 `disposed`；事件绑定先全解再按模式绑（幂等）；`vite.config` 已配 `watch.ignored: ['**/*.tmpdir/**']`（编辑器原子写产生的临时目录会让 chokidar EBUSY 崩掉整个 dev server）。
8. **打包**：`requirements.txt` 必须与 `azurlane.spec` 的 `collect_all` 一致（缺一个新机打包直接崩）；运行时动态 import（`core.voice`）必须登记进 hiddenimports；tools 脚本用 `run_tool` 进程内加载，**禁止 `[sys.executable, xx.py]` 起子进程**（frozen 下 sys.executable 是 exe）；本地工具目录（`tools/vgmstream/`、`references/`）不入库。
9. **验收验产物不验接口**：`verify_package.py` 检查提取产物完整性（合成 painting.png 尺寸 / model3.json+moc3+动作数 / skel+atlas），只验返回码会漏"提取器没打包进去"这类静默失败。

## 验证方法论
渲染/取景/配色类改动：headless Edge 截图 → PIL 像素分析（alpha 包围盒/尺寸比例）→ 视觉模型（vision skill）描述构图；**对照官方海报量化"正确构图"再定参数**（如人物占画面 %、相对家具倍数），不凭感觉调参。完整案例见 `docs/经验总结.md`。
