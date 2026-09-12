import { defineConfig } from 'vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// 与 SRC 一致，从本文件位置推导 templates/，不再硬编码机器绝对路径
const FRONTEND = path.dirname(fileURLToPath(import.meta.url))
const TEMPLATES = path.join(FRONTEND, '..', 'templates')
const NM = path.join(FRONTEND, 'node_modules')
// 权威源固定指向 templates/live2d_app_src.js（不要再依赖 cwd 下的旧拷贝）。
const SRC = path.join(FRONTEND, '..', 'templates', 'live2d_app_src.js')

export default defineConfig({
  root: process.cwd(),
  // entry 位于 templates/，无法向上找到 frontend/node_modules，
  // 显式把库导入指到 frontend/node_modules 下的绝对路径。
  resolve: {
    alias: [
      // Live2D 运行时已迁移：pixi.js v7 + pixi-live2d-display-lipsyncpatch 0.5.0
      // （0.4.0 内置的 Cubism 4.x 框架渲染不了最新代 Cubism 5 模型，会整模黑屏）
      { find: 'pixi-live2d-display-lipsyncpatch/cubism4', replacement: path.join(NM, 'pixi-live2d-display-lipsyncpatch/dist/cubism4.es.js') },
      { find: 'pixi.js', replacement: path.join(NM, 'pixi.js/dist/pixi.mjs') },
    ],
  },
  build: {
    lib: {
      entry: SRC,
      name: 'L2DApp',
      formats: ['iife'],
    },
    outDir: TEMPLATES,
    emptyOutDir: false,
    minify: false,
    rollupOptions: {
      output: { entryFileNames: 'live2d-app.js' },
    },
    target: 'es2018',
  },
})