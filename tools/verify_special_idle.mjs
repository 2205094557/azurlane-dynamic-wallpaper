/* 状态机回归测试：特殊待机（touch_special_normal）不得「进入后跳回 normal」。
 *
 * 背景（真实 bug）：jinluhao_4 等 6 个皮肤的 hitAreas 含 touch_special_normal 区域。
 * 它在官方 drag_data.config_client 里是 change_idle（点击 touch_special 后进入的
 * 循环待机态），但降级路径曾把它当「点一下播一次的动作」→ 播完 complete 回调切回
 * normal，表现为「进入这个动作不循环、跳回 normal」。
 *
 * 验证方式：从 templates/wallpaper_spine.html 逐字提取互动状态机函数源码，
 * 在 Node 里用真实 spine 运行时 + 真实骨架驱动，断言状态流转。
 * 不用浏览器（Edge 在受限环境不可用），且测的是导出模板的真实实现。
 *
 * 用法：
 *   node tools/verify_special_idle.mjs                # 全部 6 个皮肤
 *   node tools/verify_special_idle.mjs jinluhao_4     # 单个皮肤
 */
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ALL_SKINS = ['jinluhao_4', 'feiteliedadi_5', 'mojiaduoer_5', 'siwanshi_4', 'yuekechengii_4', 'antu_3'];
const targets = process.argv.slice(2).filter((a) => !a.startsWith('-'));
const SKINS = targets.length ? targets : ALL_SKINS;

// ---- spine 运行时（vendor 单文件 IIFE） ----
function loadSpine() {
  const code = fs.readFileSync(path.join(ROOT, 'frontend/public/vendor/spine-webgl-3.8.js'), 'utf8');
  const ctx = { console, window: {}, document: undefined, XMLHttpRequest: undefined, Image: undefined };
  ctx.globalThis = ctx;
  ctx.self = ctx;
  vm.createContext(ctx);
  vm.runInContext(code + '\n;this.__spine = spine;', ctx);
  return ctx.__spine;
}

// ---- 从导出模板提取真实函数源码（大括号配对） ----
function extractFn(html, name) {
  const re = new RegExp('^function ' + name + '\\s*\\(', 'm');
  const m = re.exec(html);
  if (!m) throw new Error('模板中未找到函数 ' + name);
  let i = html.indexOf('{', m.index);
  let depth = 0;
  let end = -1;
  for (let j = i; j < html.length; j++) {
    const c = html[j];
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) {
        end = j + 1;
        break;
      }
    }
  }
  return html.slice(m.index, end);
}

function buildHarness(spine, skelPath, atlasPath, html) {
  const ab = Uint8Array.from(fs.readFileSync(skelPath));
  const atlas = new spine.TextureAtlas(fs.readFileSync(atlasPath, 'utf8'), () => ({
    setFilters() {},
    setWraps() {},
    dispose() {},
    getImage() {
      return { width: 1, height: 1 };
    },
  }));
  const skelData = new spine.SkeletonBinary(new spine.AtlasAttachmentLoader(atlas)).readSkeletonData(ab);
  const skel = new spine.Skeleton(skelData);
  const state = new spine.AnimationState(new spine.AnimationStateData(skelData));
  const skeletons = [{ skeleton: skel, state, data: skelData }];

  const FN_NAMES = [
    'animNames0',
    'hasAnim0',
    'isSpecialIdle',
    'specialIdleAfter',
    'hasTouchAnim',
    'playInteractAnim',
    'enterInteract',
    'onInteractComplete',
    'cycleTouchInteract',
  ];
  const stateSrc = `
var interactState = "normal"; var _dragSeq = 0; var _touchIndex = -1; var currentIdle = "normal";
var TOUCH_ANIMS = ["touch_body", "touch_head", "touch_special"];
var INTERACT_RULES = [];
`;
  const fullSrc =
    stateSrc +
    '\n' +
    FN_NAMES.map((n) => extractFn(html, n)).join('\n\n') +
    `
;this.__api = {
  animNames0, isSpecialIdle, specialIdleAfter, playInteractAnim, onInteractComplete,
  cycleTouchInteract, hasAnim0, hasTouchAnim,
  getCurrentIdle: function () { return currentIdle; },
  setCurrentIdle: function (v) { currentIdle = v; },
};`;
  const ctx2 = {
    console,
    skeletons,
    Math,
    parseInt,
    String,
    RegExp,
    JSON,
    undefined,
    // 副作用桩：验证只关心状态机流转
    spinePlayVoice() {},
    spinePlayVoiceRandom() {},
    cycleExpression() {},
  };
  ctx2.globalThis = ctx2;
  vm.createContext(ctx2);
  vm.runInContext(fullSrc, ctx2);
  const api = ctx2.__api;
  // 与模板 initInteract 一致：注册 complete 回调
  state.addListener({ complete: (entry) => api.onInteractComplete(entry) });

  const durOf = (n) => {
    const a = skelData.animations.find((x) => x.name === n);
    return a ? a.duration : 0;
  };
  const tick = (sec) => {
    const dt = 1 / 60;
    for (let t = 0; t < sec; t += dt) {
      state.update(dt);
      state.apply(skel);
      skel.updateWorldTransform();
    }
  };
  const cur = () => {
    const e = state.getCurrent(0);
    return e && e.animation ? e.animation.name : '(none)';
  };
  const curLoop = () => {
    const e = state.getCurrent(0);
    return e ? !!e.loop : null;
  };
  return { api, skelData, durOf, tick, cur, curLoop };
}

function runSkin(spine, html, painting) {
  const skelPath = path.join(ROOT, 'resources/extracted/spine', painting, painting + '.skel');
  const atlasPath = path.join(ROOT, 'resources/extracted/spine', painting, painting + '.atlas');
  if (!fs.existsSync(skelPath) || !fs.existsSync(atlasPath)) {
    console.log(`[SKIP] ${painting}: 本地缺骨架/图集`);
    return null;
  }
  const h = buildHarness(spine, skelPath, atlasPath, html);
  const { api, durOf, tick, cur, curLoop } = h;
  const names = api.animNames0();
  if (!names.includes('touch_special_normal')) {
    console.log(`[SKIP] ${painting}: 无 touch_special_normal 动画`);
    return null;
  }
  const results = [];
  const check = (label, got, want) => results.push({ label, got, want, ok: got === want });

  // ① 静态判定
  check('isSpecialIdle(touch_special_normal)', api.isSpecialIdle('touch_special_normal'), true);
  check('isSpecialIdle(normal)=false', api.isSpecialIdle('normal'), false);
  check('specialIdleAfter(touch_special)', api.specialIdleAfter('touch_special'), 'touch_special_normal');

  // ② 旧 bug 路径：显式 loop=false 调特殊待机 → 必须被强制循环（修复前此处 FAIL）
  api.playInteractAnim('touch_special_normal', false);
  check('特殊待机强制循环(loop=true)', curLoop(), true);
  check('特殊待机动画名', cur(), 'touch_special_normal');

  // ③ 点 touch_special 播完 → 进特殊待机循环（而非回 normal）
  api.setCurrentIdle('touch_special_normal');
  api.playInteractAnim('touch_special', false);
  tick(durOf('touch_special') + 3);
  check('touch_special 播完进特殊待机', cur(), 'touch_special_normal');
  check('特殊待机仍在循环', curLoop(), true);

  // ④ 特殊待机下点 touch_special_2 → 播完回 normal
  api.setCurrentIdle('normal');
  api.playInteractAnim('touch_special_2', false);
  tick(durOf('touch_special_2') + 3);
  check('touch_special_2 播完回 normal', cur(), 'normal');

  // ⑤ 轮换路径同样记录特殊待机
  api.setCurrentIdle('normal');
  let saw = false;
  for (let i = 0; i < 6; i++) {
    api.cycleTouchInteract();
    if (cur() === 'touch_special') {
      tick(durOf('touch_special') + 3);
      saw = api.getCurrentIdle() === 'touch_special_normal';
      break;
    }
    tick(1);
  }
  check('轮换到 touch_special 后进特殊待机', saw, true);

  const ok = results.every((r) => r.ok);
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${painting}`);
  for (const r of results) {
    if (!r.ok) console.log(`   FAIL ${r.label}: got=${JSON.stringify(r.got)} want=${JSON.stringify(r.want)}`);
  }
  return ok;
}

// ---- main ----
const spine = loadSpine();
const html = fs.readFileSync(path.join(ROOT, 'templates/wallpaper_spine.html'), 'utf8');
let allOk = true;
let ran = 0;
for (const s of SKINS) {
  const r = runSkin(spine, html, s);
  if (r === null) continue;
  ran++;
  if (!r) allOk = false;
}
console.log('');
if (!ran) {
  console.log('没有可测的皮肤');
  process.exit(2);
}
console.log(allOk ? `全部通过（${ran} 个皮肤）` : '存在失败');
process.exit(allOk ? 0 : 1);
