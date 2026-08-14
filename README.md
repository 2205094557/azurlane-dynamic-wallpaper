# AzurLane Dynamic Wallpaper

碧蓝航线（Azur Lane）动态壁纸工具：从官方资源通道下载并提取 **Spine 动态立绘** 与 **Live2D 皮肤**，在 Web 界面中预览，然后导出为 Wallpaper Engine 壁纸项目。

## 功能特性

- **Spine 动态立绘**（`spinepainting`，支持 `_T` 人物 / `_B` 背景 / `_M` 舰装等多骨架分层合并，自动选附件最多的完整 skin）
- **Live2D 皮肤**（`live2d`，Cubism 3）
- **静态立绘**（`painting` 碎片重组，基于 azur-paint 合成完整立绘）
- 官方 CDN 抓取 + AssetBundle 本地解包提取（TCP 握手协议，参考开源实现）
- 本地导入已解包资源
- 图鉴式 Web 预览（Spine / Live2D 双引擎，背景样式含取色、莫奈、毛玻璃、星空等）
- **互动语音**：官方 CriWare cue 语音包下载 + vgmstream 本地解码，点击角色播放台词与语音
- 导出 Wallpaper Engine 壁纸项目（含 project.json 原生属性、一键应用；L2D 壁纸右侧面板可随时切换**语音 / 开场动画 / 互动**三个开关）
- **四套主题**：水彩画风（默认）/ 少女漫画风 / 赛博朋克 / 太阳朋克，设置里一键切换

## 技术栈

- 外壳：pywebview + WebView2
- 后端：Python 3.12，插件化模块设计（sources / extractors / exporters + 注册表）
- 前端：Vue 3 + Vite + Naive UI；Spine 用 spine-ts 3.8 WebGL 运行时，Live2D 用 Cubism Web SDK（pixi-live2d-display）
- 导出：Wallpaper Engine web 壁纸项目（模板 + project.json + preview）

## 目录结构

```
azurlane-dynamic-wallpaper/
├── backend_server.py        # 本地后端 API（下载/提取/导出/取色）
├── app.py                   # 应用装配（插件注册 + 元数据 + 资源库）
├── app_pack.py              # 打包版入口（内置后端 + 静态前端 + pywebview）
├── web_main.py              # 源码版桌面入口（加载 Vite dev server）
├── core/                    # 服务层：注册表 / 元数据 / 资源库 / 取色 / 语音 / WE 集成
├── plugins/                 # sources / extractors / exporters 插件
├── templates/               # 导出壁纸模板 + 共享布局模块 wallpaper-layout.js
├── tools/                   # 元数据同步、索引重建、语音词表、打包验收等脚本
├── frontend/                # Vue 3 + Vite SPA
├── scripts/start_dev.py     # 一键启动脚本（关闭窗口后自动清理进程）
├── start_dev.bat            # 双击启动源码版
├── azurlane.spec            # PyInstaller 打包配置
└── docs/                    # 设计文档
```

## 环境要求

- Windows 10 / 11（需要 WebView2 运行时）
- Python 3.12
- Node.js 18+

## 快速开始（源码版）

```bash
# 1. 安装 Python 依赖
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. 安装前端依赖
cd frontend
npm install
cd ..

# 3. 一键启动（后端 8766 + Vite 5173 + 桌面窗口）
start_dev.bat

# 关闭窗口后，脚本会自动终止后端与 Vite；
# 也可随时用 start_dev.bat --stop 一键关闭整个开发栈。
```

首次使用请在「设置」里运行**更新元数据**（联网抓取官方 CDN 清单与 bwiki 图鉴数据），之后即可在图鉴中下载、预览皮肤。

## 语音（可选）

- 语音解码依赖 [vgmstream](https://github.com/vgmstream/vgmstream)：把 `vgmstream-cli.exe` 及同目录 DLL 放到 `tools/vgmstream/`（本机工具，不入库）；缺失时语音功能降级为仅显示台词文本
- 首次使用：在「设置」→ 语音中下载对应舰船语音包（官方 CriWare cue，本地解码为 wav），之后预览点击角色即可播放

## 打包发布

```bash
# 一键打包：强制 packaged 前端构建（API 指向 8770）→ 校验 → PyInstaller → 产物自检
python scripts/build_pack.py

# 发布前全链路验收（真实下载三类皮肤并校验提取/导出产物）
python tools/verify_package.py --clean
```

产物位于 `dist/azurlane-wallpaper/`，入口为 `azurlane-wallpaper.exe`（内置后端 8770 + 静态前端 5174）。

> 注意：`frontend/dist` 一旦被普通 `npm run build`（无 `--mode packaged`）覆盖，
> 打包版就会去连开发版后端 8766，表现为「后端服务未启动 / 下载失败 / 显示开发机数据」。
> `build_pack.py` 每次都会重新构建并校验产物里只有 8770，从根上避免这个问题。

端口约定：开发版后端 8766 / Vite 5173；打包版后端 8770 / 静态前端 5174。

## 第三方提取器（references/）

Live2D 完整转换与静态立绘合成依赖以下第三方实现，仓库未随附，请自行按需获取后放入 `references/`：

- `references/UnityPyLive2DExtractor/` — Live2D 完整模型转换（moc3 / model3.json / 动作）
- `references/azur-paint/`（`main2.py`）— 静态立绘图层合成引擎

缺失时相关类型会退化为兜底提取（Live2D 仅导出原始贴图、静态仅简单拼接），打包自检 `tools/verify_package.py` 会校验完整产物。

## 合规说明

- 仅从游戏官方通道拉取资源并在本地处理；不内置、不上传、不传播游戏素材
- 元数据来自官方数据与 bwiki 图鉴（仅文本数据）
- 请遵守游戏服务条款；本工具定位为个人学习与壁纸创作用途

## 致谢

- [nobbyfix/AzurLane-AssetDownloader](https://github.com/nobbyfix/AzurLane-AssetDownloader) — CDN 协议参考
- UnityPy / spine-ts / pixi-live2d-display / azur-paint / vgmstream 等开源项目
