# 碧蓝航线动态壁纸工具 (azurlane-dynamic-wallpaper) — 会话接续与项目上下文

本文件汇总了截止当前会话的**所有系统架构、近期修改记录、已解决的核心 Bug 与后续待办事项**。可以直接在 ZCode 中通过 `@PROJECT_CONTEXT.md` 引用，或将下方内容复制作为 ZCode 新对话的开场提示词。

---

## 一、项目概况与核心技术栈

- **项目定位**：从碧蓝航线官方 CDN 下载/提取 Spine + Live2D + 静态立绘，提供 Web 界面预览，并支持导出为 Wallpaper Engine (WE) 动态壁纸与一键应用。
- **核心技术栈**：
  - 前端：Vue 3 + Vite 5 + Spine-WebGL 3.8 + Pixi-Live2D-Display (Cubism 3/4)
  - 后端：Python 3.12 (HTTP API / 端口 8766，打包版 8770)
  - 音频：CriWare ACB/HCA 解码（vgmstream-cli）
  - 导出目标：Wallpaper Engine Web 壁纸（HTML/JS 独立运行时，16:9 画布自适应布局）

---

## 二、近期已完成的核心修改与 Bug 修复清单

### 1. Spine 拖拽与待机状态机卡顿修复 (`3af95ac`)
- **问题**：在 Spine 预览与 WE 导出壁纸中，点击角色播放完拖拽变身动作（`drag`）切换到深度待机动作（`ex`）时，角色会出现明显的单帧抽搐/卡顿。
- **根因**：
  - `playInteractAnim` 在每次切换动作时无差别调用了 `l.skeleton.setToSetupPose()`，导致整个骨架被重置为 T-pose / 绑定姿态，画布在当帧被绘制为裸骨架；
  - 缺少过渡混合时间（`defaultMix = 0`），导致骨骼在单帧内发生千像素级的突变。
- **修复方案**：
  - 移除对骨骼坐标的破坏性重置，仅在 Track 1 真实存在表情时清空表情并调用 `setSlotsToSetupPose()` 还原插槽；
  - 在 `SpinePreview.vue` 与 `wallpaper_spine.html` 中同步配置 `stateData.defaultMix = 0.2`，实现 0.2 秒平滑插值过渡；表情动画显式设置 `mixDuration = 0`。

### 2. 北卡罗来纳「与阳光一同闪耀」交互失效修复 (`0f59c8d`)
- **问题**：点击该皮肤身体任意部位完全无法触发互动或表情。
- **根因**：`hitAreaAt` 判定函数此前读取了视图渲染专用的 `hitAreas.value`；当用户未开启右侧「显示交互区域」开关时，该数组被清空为空数组，导致底层物理命中判定直接失效。
- **修复方案**：将碰撞判定与视图渲染彻底解耦，无论开关状态如何，`hitAreaAt` 始终直接读取官方 `remoteHitAreas` 真实碰撞数据。

### 3. 经典双待机状态机闭环恢复 (`d9e4b80`)
- **逻辑闭环**：
  - 初始状态为 `normal` 待机：点击角色身体 ➔ 播放 `drag` 动作 ➔ 播完自动切入 `ex` 深度互动待机；
  - 处于 `ex` 待机时：点击角色身体 ➔ 播放 `drag_ex` 动作 ➔ 播完自动切回初始 `normal` 待机；
  - 点击面部表情框（`1~6` 等）：独立切换表情，不破坏身体状态机。

### 4. 天津风「狐仙大人驾到」超大背景渲染修复 (`23d0666`)
- **问题**：天津风皮肤加载后只有人物和部件，缺失巨型神社/鸟居背景。
- **根因**：`tools/build_local_index.py` 中的图层匹配规则只匹配单字母 `_T / _B / _M`，将天津风关键的第二背景层 `tianjinfeng_2B2.skel`（5063x5501 尺寸）误判过滤。
- **修复方案**：将图层正则升级为支持数字后缀（`r"_?[tbmf]\d*"`），使全部 5 个骨架层（`2B`, `2B2`, `主控`, `2M`, `2T`）完整入库并优先渲染背景层。

### 5. 新增船只全套语音与台词气泡补全
- 为 **天津风**（`tianjinfeng`，船只编号 `30119`）、**安土**（`antu`，`30409`）、**虎**（`hu`，`20238`）、**伊14**（`i14`，`31703`）逆向提取官方 CDN 语音包；
- 补全 `resources/metadata/voice_words.json` 中的中文台词文本（摸头、触摸、特殊触摸、待机等多段台词），实现了发声与字幕气泡同步展示。

### 6. 超大模型缩放支持
- 将 Wallpaper Engine 导出壁纸及预览端的缩放滑块上限由 300% 提升至 800%（`MAX_SCALE = 800`），完美适配 10000x8000 分辨率级别的超大 Live2D/Spine 模型。

---

## 三、开发与维护铁律（必读）

1. **预览与导出双端同步（铁律 6）**：
   - 预览组件：`frontend/src/components/SpinePreview.vue`
   - 导出模板：`templates/wallpaper_spine.html`
   - Live2D 源码：`templates/live2d_app_src.js`（改动后需执行 `npm run build:live2d` 生成 `templates/live2d-app.js`）
   - 凡涉及 Spine / Live2D 的交互、动作状态机、事件监听改动，**两端代码必须同步修改**，确保软件内预览与 Wallpaper Engine 导出效果 100% 一致。
2. **进程安全守则**：
   - 严禁按进程名批量杀进程（如 `killall node`、`taskkill /IM python.exe`）；
   - DSH / 外部宿主也是 Node.js 进程，误杀会导致连接中断；
   - 启动命令：`scripts/start_dev.py`。
3. **后端热重载注意**：
   - 修改 Python 后端代码后必须重启后端服务（端口 8766），Python 进程不会自动热重载。

---

## 四、ZCode 对话接续开场指令示例

如果你在 ZCode 中开启新对话，可以直接发送以下指令：
> “你好，我已经把当前项目的最新完整上下文保存在了 `@PROJECT_CONTEXT.md` 中。该项目是碧蓝航线动态壁纸工具，采用 Vue 3 + Spine 3.8 + Live2D + Python。近期刚刚修复了 Spine 拖拽到 ex 待机的过渡卡顿、天津风/安土/虎的语音台词与大背景加载。请基于该文档上下文继续接下来的开发工作。”
