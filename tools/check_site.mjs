#!/usr/bin/env node
/**
 * 动作索引页的自检：用 Chrome DevTools Protocol 驱动真实浏览器，检查交互是否正常。
 *
 * 需要先起静态服务（仓库根目录）：
 *   python3 -m http.server 8765 --bind 127.0.0.1
 * 再跑：
 *   node tools/check_site.mjs [url]
 *
 * 会覆盖：动作列表数量、点击切换、四联视图开关、HUD 隐藏、播放暂停、时间轴 scrub、
 * 骨架开关、模型库（已绑骨 / 未绑骨）与骨骼状况面板、控制台报错。
 */
const URL_UNDER_TEST = process.argv[2] || 'http://127.0.0.1:8765/site/';
const DEBUG_PORT = 9222;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* chrome 还没起来 */ }
    await sleep(300);
  }
  throw new Error('连不上 Chrome 调试端口');
}

function rpc(ws) {
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
    }
  });
  return (method, params = {}) =>
    new Promise((resolve, reject) => {
      const mid = ++id;
      pending.set(mid, (msg) => (msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)));
      ws.send(JSON.stringify({ id: mid, method, params }));
    });
}

const wsUrl = await connect();
const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
const send = rpc(ws);

const errors = [];
ws.addEventListener('message', (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.method === 'Runtime.exceptionThrown') {
    errors.push(msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text);
  }
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
    errors.push(msg.params.args.map((a) => a.value ?? a.description).join(' '));
  }
});

await send('Runtime.enable');
await send('Page.enable');
await send('Page.navigate', { url: URL_UNDER_TEST });
await sleep(1200);

async function evaluate(expression) {
  const res = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text + ' :: ' + expression);
  return res.result.value;
}

async function waitFor(expression, label, timeout = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (await evaluate(expression)) return;
    await sleep(250);
  }
  throw new Error(`超时：${label}`);
}

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  → ' + detail : ''}`);
};

await waitFor(
  `document.getElementById('loading').style.display === 'none'`,
  '模型加载完成'
);
check('模型加载完成', true);

const clipCount = await evaluate(`document.querySelectorAll('.clip').length`);
check('动作列表有 4 条', clipCount === 4, `实际 ${clipCount}`);

const tris = await evaluate(`document.getElementById('stat-tris').textContent`);
check('网格统计已填充', /k$/.test(tris), `tris=${tris}`);

await evaluate(`document.querySelectorAll('.clip')[2].click()`);
await sleep(300);
const hud = await evaluate(`document.getElementById('hud-name').textContent`);
const selected = await evaluate(`document.querySelector('.clip[aria-selected="true"] .clip-name').textContent`);
check('点击第三条切到「跳跃」', hud === '跳跃' && selected.includes('跳跃'), `hud=${hud} 选中=${selected.trim()}`);

await evaluate(`document.getElementById('tg-grid').click()`);
await sleep(400);
const gridOn = await evaluate(`!document.getElementById('grid-labels').hidden`);
const hudHidden = await evaluate(`getComputedStyle(document.getElementById('hud')).display === 'none'`);
const cells = await evaluate(`document.querySelectorAll('.grid-cell-label').length`);
check('四联视图打开', gridOn, `labels=${cells}`);
check('四联模式下 HUD 隐藏', hudHidden);

await evaluate(`document.getElementById('tg-grid').click()`);
await sleep(300);
check('四联视图关闭', await evaluate(`document.getElementById('grid-labels').hidden === true`));

const playingBefore = await evaluate(`document.getElementById('btn-play').classList.contains('is-playing')`);
await evaluate(`document.getElementById('btn-play').click()`);
await sleep(300);
const playingAfter = await evaluate(`document.getElementById('btn-play').classList.contains('is-playing')`);
check('播放/暂停按钮切换', playingBefore !== playingAfter, `${playingBefore} → ${playingAfter}`);
const t1 = await evaluate(`document.getElementById('hud-time').textContent`);
await sleep(700);
const t2 = await evaluate(`document.getElementById('hud-time').textContent`);
check('暂停后时间不再推进', t1 === t2, `${t1} vs ${t2}`);
await evaluate(`document.getElementById('btn-play').click()`);

await evaluate(`(() => {
  const s = document.getElementById('scrub');
  s.value = '500';
  s.dispatchEvent(new Event('input', { bubbles: true }));
})()`);
await sleep(300);
const scrubTime = await evaluate(`document.getElementById('hud-time').textContent`);
const duration = await evaluate(`document.getElementById('hud-dur').textContent`);
check('时间轴可拖动', Number(scrubTime) > Number(duration) * 0.3, `${scrubTime}s / ${duration}s`);

const skelBefore = await evaluate(`document.getElementById('tg-skeleton').checked`);
await evaluate(`document.getElementById('tg-skeleton').click()`);
await sleep(200);
const skelAfter = await evaluate(`document.getElementById('tg-skeleton').checked`);
check('骨架开关响应', skelBefore !== skelAfter);

const speedSet = await evaluate(`(() => {
  const b = [...document.getElementById('speeds').children].find(e => e.textContent === '2×');
  b.click();
  return b.getAttribute('aria-pressed');
})()`);
check('速度按钮可切换', speedSet === 'true');

/* ---- 模型库 / 骨骼状况 ---- */

const rigPanel = await evaluate(`(() => ({
  armature: document.getElementById('rig-armature').textContent,
  bones: document.getElementById('rig-bones').textContent,
  skin: document.getElementById('rig-skin').textContent,
  clips: document.getElementById('rig-clips').textContent,
  measured: window.__index.state.bones,
  chip: document.querySelector('.model[aria-selected="true"] .model-chip').textContent,
}))()`);
const modelCount = await evaluate(`document.querySelectorAll('.model').length`);
check('模型列表 4 条', modelCount === 4, `实际 ${modelCount}`);
check('templar_rig：25 骨 / 1 蒙皮 / 4 动作',
  rigPanel.bones === '25' && rigPanel.armature === '有' && rigPanel.clips === '4' && rigPanel.measured === 25,
  JSON.stringify(rigPanel));
check('templar_rig 芯片标「已绑骨」', rigPanel.chip === '已绑骨', rigPanel.chip);

await evaluate(`document.querySelector('.model[data-model="templar_tpose_unarmored"]').click()`);
await waitFor(
  `document.getElementById('loading').style.display === 'none' && window.__index.state.entry.id === 'templar_tpose_unarmored'`,
  '未绑骨模型载入完成', 180000);

const staticPanel = await evaluate(`(() => ({
  armature: document.getElementById('rig-armature').textContent,
  bones: document.getElementById('rig-bones').textContent,
  skins: document.getElementById('rig-skin').textContent,
  statBones: document.getElementById('stat-bones').textContent,
  hud: document.getElementById('hud-name').textContent,
  chip: document.querySelector('.model[aria-selected="true"] .model-chip').textContent,
  emptyClip: document.querySelectorAll('.clip-empty').length,
  isStatic: document.body.classList.contains('is-static'),
  gridDisabled: document.getElementById('tg-grid').disabled,
  skelDisabled: document.getElementById('tg-skeleton').disabled,
  playDisabled: document.getElementById('btn-play').disabled,
  loopDisabled: document.getElementById('tg-loop').disabled,
  cardStatus: document.querySelector('.model[aria-selected="true"]').dataset.status,
  skeletonHelper: !!window.__index.state.skeletonHelper,
  measuredBones: window.__index.state.bones,
  measuredSkin: window.__index.state.skinned,
  measuredClips: window.__index.state.clips.length,
}))()`);
check('未绑骨模型实测 0 骨 / 0 蒙皮',
  staticPanel.measuredBones === 0 && staticPanel.measuredSkin === 0,
  `bones=${staticPanel.measuredBones} skinned=${staticPanel.measuredSkin} 面板=${staticPanel.skins}`);
check('骨骼状况面板写「无 / 0」', staticPanel.armature === '无' && staticPanel.bones === '0',
  `${staticPanel.armature} / ${staticPanel.bones}`);
check('顶栏骨骼标「未绑骨」', /未绑骨/.test(staticPanel.statBones), staticPanel.statBones);
check('模型芯片「未绑骨」', staticPanel.chip === '未绑骨', staticPanel.chip);
check('无骨架 helper、无动作', !staticPanel.skeletonHelper && staticPanel.measuredClips === 0);
check('动作列表给「无动作」占位', staticPanel.emptyClip === 1, `占位 ${staticPanel.emptyClip} 条`);
check('播放 / 四联 / 骨架 / 循环控件均停用',
  staticPanel.isStatic && staticPanel.gridDisabled && staticPanel.skelDisabled
  && staticPanel.playDisabled && staticPanel.loopDisabled);
check('载入完成后卡片不再显示「载入中」', staticPanel.cardStatus === 'ready', staticPanel.cardStatus);
check('HUD 标「未绑骨」', staticPanel.hud === '未绑骨', staticPanel.hud);

/* ---- 绑骨版：有骨架、没动作 ---- */
await evaluate(`document.querySelector('.model[data-model="templar_tpose_unarmored_rigged"]').click()`);
await waitFor(
  `document.getElementById('loading').style.display === 'none' && window.__index.state.entry.id === 'templar_tpose_unarmored_rigged'`,
  '绑骨版载入完成', 180000);

const riggedNoClip = await evaluate(`(() => ({
  bones: document.getElementById('rig-bones').textContent,
  armature: document.getElementById('rig-armature').textContent,
  skin: document.getElementById('rig-skin').textContent,
  clips: document.getElementById('rig-clips').textContent,
  statBones: document.getElementById('stat-bones').textContent,
  hud: document.getElementById('hud-name').textContent,
  chip: document.querySelector('.model[aria-selected="true"] .model-chip').textContent,
  measuredBones: window.__index.state.bones,
  measuredClips: window.__index.state.clips.length,
  skelEnabled: !document.getElementById('tg-skeleton').disabled,
  playDisabled: document.getElementById('btn-play').disabled,
  gridDisabled: document.getElementById('tg-grid').disabled,
  skeletonHelper: !!window.__index.state.skeletonHelper,
  note: document.getElementById('transport-note').textContent,
}))()`);
check('绑骨版：20 骨 / 1 蒙皮 / 0 动作',
  riggedNoClip.bones === '20' && riggedNoClip.armature === '有' && riggedNoClip.clips === '0'
  && riggedNoClip.measuredBones === 20 && riggedNoClip.measuredClips === 0,
  JSON.stringify(riggedNoClip));
check('绑骨版芯片标「已绑骨」', riggedNoClip.chip === '已绑骨', riggedNoClip.chip);
check('绑骨版：HUD 标「已绑骨」、顶栏不写未绑骨',
  riggedNoClip.hud === '已绑骨' && !/未绑骨/.test(riggedNoClip.statBones), `${riggedNoClip.hud} / ${riggedNoClip.statBones}`);
check('绑骨版：骨架开关仍可用、播放/四联停用',
  riggedNoClip.skelEnabled && riggedNoClip.playDisabled && riggedNoClip.gridDisabled
  && riggedNoClip.skeletonHelper, riggedNoClip.note);

/* ---- 分块手部修订版：55 骨 / 16 蒙皮网格 ---- */
await evaluate(`document.querySelector('.model[data-model="templar_tpose_unarmored_parts_rig_handfix"]').click()`);
await waitFor(
  `document.getElementById('loading').style.display === 'none' && window.__index.state.entry.id === 'templar_tpose_unarmored_parts_rig_handfix'`,
  '手部修订版载入完成', 180000);
const handfix = await evaluate(`(() => ({
  bones: window.__index.state.bones,
  skins: window.__index.state.skinned,
  clips: window.__index.state.clips.length,
  skinPanel: document.getElementById('rig-skin').textContent,
  skeletonEnabled: !document.getElementById('tg-skeleton').disabled,
  playDisabled: document.getElementById('btn-play').disabled,
  errorHidden: document.getElementById('error').hidden,
}))()`);
check('手部修订版：55 骨 / 16 蒙皮 / 0 动作',
  handfix.bones === 55 && handfix.skins === 16 && handfix.clips === 0
  && handfix.skinPanel === '16 / 16' && handfix.errorHidden, JSON.stringify(handfix));
check('手部修订版：骨架可用、播放停用', handfix.skeletonEnabled && handfix.playDisabled);
const handfixSkeleton = await evaluate(`(() => {
  const toggle = document.getElementById('tg-skeleton');
  toggle.checked = true;
  toggle.dispatchEvent(new Event('change'));
  return window.__index.state.skeletonHelper.visible;
})()`);
check('手部修订版：骨架实际显示', handfixSkeleton === true);

await evaluate(`document.querySelector('.model[data-model="templar_rig"]').click()`);
await waitFor(
  `document.getElementById('loading').style.display === 'none' && window.__index.state.clips.length === 4`,
  '切回已绑骨模型', 120000);
const back = await evaluate(`(() => ({
  bones: document.getElementById('rig-bones').textContent,
  clips: document.querySelectorAll('.clip').length,
  isStatic: document.body.classList.contains('is-static'),
  gridDisabled: document.getElementById('tg-grid').disabled,
}))()`);
check('切回 templar_rig 恢复 25 骨 / 4 动作',
  back.bones === '25' && back.clips === 4 && !back.isStatic && !back.gridDisabled, JSON.stringify(back));

check('无控制台报错', errors.length === 0, errors.slice(0, 3).join(' | '));

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} 通过`);
ws.close();
process.exit(failed.length ? 1 : 0);
