import { defineConfig } from 'vite'
import path from 'node:path'

const TEMPLATES = 'D:/download/codex/azurlane-dynamic-wallpaper/templates'

export default defineConfig({
  root: process.cwd(),
  build: {
    lib: {
      entry: path.join(process.cwd(), 'live2d_app_src.js'),
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