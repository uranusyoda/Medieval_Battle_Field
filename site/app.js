/**
 * 圣殿骑士 · 动作索引
 * 单页三维查看器：主视图单动作播放 + 四联视图同时对比四套动作。
 * 依赖本地 vendored three.js（site/vendor），不联网。
 *
 * 模型库：每条带骨骼状况标签。templar_rig 是已绑骨的游戏网格（25 骨 / 4 动作），
 * templar_tpose_unarmored 是 Tripo 出的静态高模，未绑骨（0 骨 / 0 动作），
 * 索引页要能一眼看出来，所以骨骼数是从载入后的 GLB 里实测的，不是写死的。
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { clone as cloneSkinned } from 'three/addons/utils/SkeletonUtils.js';

const MODELS = [
  {
    id: 'templar_rig',
    title: 'templar_rig',
    variant: '有甲 · 游戏网格',
    url: '../assets/models/characters/templar_rig.glb',
    rig: 'rigged',
    expect: '25 骨 · 4 动作',
    note: '已绑骨：25 根骨骼（含披风 2、佩剑挂点 1），walk / run / jump / crouch 四套动作走 NLA。',
  },
  {
    id: 'templar_tpose_unarmored',
    title: 'templar_tpose_unarmored',
    variant: '无甲 · Tripo 高模',
    url: '../assets/models/characters/templar_tpose_unarmored.glb',
    rig: 'unrigged',
    expect: '0 骨 · 0 动作',
    note: '未绑骨：Tripo 图生 3D 的静态 T-pose，无骨架、无蒙皮权重、无动作，只能看造型与比例。',
  },
  {
    id: 'templar_tpose_unarmored_rigged',
    title: 'templar_tpose_unarmored_rigged',
    variant: '无甲 · 绑骨版',
    url: '../assets/models/characters/templar_tpose_unarmored_rigged.glb',
    rig: 'rigged',
    expect: '20 骨 · 0 动作',
    note: '绑骨版：由 templar_tpose_unarmored 复制而来，只绑大关节——躯干 / 头 / 四肢共 20 骨，手当刚体整体（每边一根 hand 骨，手指不细分、几何不动）；动作尚未制作。',
  },
];


const CLIPS = [
  { id: 'walk',   zh: '行走', en: 'walk',   fps: 24, loop: true,
    desc: '接触—经过—接触，摆臂与腿反向' },
  { id: 'run',    zh: '奔跑', en: 'run',    fps: 24, loop: true,
    desc: '含腾空帧，躯干前倾，摆臂加大' },
  { id: 'jump',   zh: '跳跃', en: 'jump',   fps: 24, loop: false,
    desc: '预备下蹲—蹬伸—顶点收腿—落地缓冲' },
  { id: 'crouch', zh: '下蹲', en: 'crouch', fps: 24, loop: true,
    desc: '蹲姿保持 + 呼吸起伏' },
];

const SPEEDS = [0.25, 0.5, 1, 1.5, 2];

const ui = {
  canvas: document.getElementById('canvas'),
  stage: document.getElementById('stage'),
  clips: document.getElementById('clips'),
  loading: document.getElementById('loading'),
  error: document.getElementById('error'),
  hudName: document.getElementById('hud-name'),
  hudKicker: document.getElementById('hud-kicker'),
  hudMeta: document.getElementById('hud-meta'),
  hudTime: document.getElementById('hud-time'),
  hudDur: document.getElementById('hud-dur'),
  play: document.getElementById('btn-play'),
  scrub: document.getElementById('scrub'),
  ticks: document.getElementById('scrub-ticks'),
  speeds: document.getElementById('speeds'),
  reset: document.getElementById('btn-reset'),
  grid: document.getElementById('tg-grid'),
  skeleton: document.getElementById('tg-skeleton'),
  autorotate: document.getElementById('tg-autorotate'),
  loop: document.getElementById('tg-loop'),
  gridLabels: document.getElementById('grid-labels'),
  statTris: document.getElementById('stat-tris'),
  statBones: document.getElementById('stat-bones'),
  statClips: document.getElementById('stat-clips'),
  statSize: document.getElementById('stat-size'),
  statPath: document.getElementById('stat-path'),
  models: document.getElementById('models'),
  rigArmature: document.getElementById('rig-armature'),
  rigBones: document.getElementById('rig-bones'),
  rigSkin: document.getElementById('rig-skin'),
  rigClips: document.getElementById('rig-clips'),
  rigNote: document.getElementById('rig-note'),
  transportNote: document.getElementById('transport-note'),
};

const state = {
  entry: MODELS[0],     // 当前模型条目
  clips: [],            // [{def, clip, action, duration}]
  current: 0,
  playing: true,
  speed: 1,
  loop: true,
  grid: false,
  cells: [],            // 四联视图用的克隆
  mainMixer: null,
  model: null,
  skeletonHelper: null,
  bones: 0,             // 实测骨骼数
  skinned: 0,           // 实测蒙皮网格数
  rigged: false,
};

/* ---------------------------------------------------------------- renderer */

const renderer = new THREE.WebGLRenderer({
  canvas: ui.canvas,
  antialias: true,
  powerPreference: 'high-performance',
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
scene.background = new THREE.Color('#0a0c0f');
scene.fog = new THREE.Fog('#0a0c0f', 9, 22);

const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
const CAM_HOME = new THREE.Vector3(2.45, 1.62, 3.30);
const CAM_TARGET = new THREE.Vector3(0, 1.00, 0);
camera.position.copy(CAM_HOME);

const gridCamera = new THREE.PerspectiveCamera(34, 1, 0.1, 100);
gridCamera.position.set(2.60, 1.58, 3.40);
gridCamera.lookAt(0, 0.98, 0);

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.copy(CAM_TARGET);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 1.4;
controls.maxDistance = 9;
controls.maxPolarAngle = Math.PI * 0.495;
controls.autoRotateSpeed = 0.9;
controls.update();

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.55;

/* ---------------------------------------------------------------- stage props */

const floor = new THREE.Mesh(
  new THREE.CircleGeometry(9, 96).rotateX(-Math.PI / 2),
  new THREE.MeshStandardMaterial({ color: '#14181d', roughness: 0.94, metalness: 0 })
);
floor.receiveShadow = true;
scene.add(floor);

const ring = new THREE.Mesh(
  new THREE.RingGeometry(1.14, 1.18, 128).rotateX(-Math.PI / 2),
  new THREE.MeshBasicMaterial({ color: '#9e2b25', transparent: true, opacity: 0.32 })
);
ring.position.y = 0.002;
scene.add(ring);

const grid = new THREE.GridHelper(14, 28, '#232a32', '#181d23');
grid.material.transparent = true;
grid.material.opacity = 0.38;
grid.position.y = 0.001;
scene.add(grid);

scene.add(new THREE.HemisphereLight('#9fb6d4', '#0a0c0f', 0.55));

const key = new THREE.DirectionalLight('#fff3e2', 2.6);
key.position.set(3.2, 5.4, 3.6);
key.castShadow = true;
key.shadow.mapSize.set(2048, 2048);
key.shadow.camera.near = 0.5;
key.shadow.camera.far = 16;
key.shadow.camera.left = -3;
key.shadow.camera.right = 3;
key.shadow.camera.top = 5;
key.shadow.camera.bottom = -1;
key.shadow.bias = -0.0008;
key.shadow.normalBias = 0.02;
scene.add(key);

const rim = new THREE.DirectionalLight('#9ec4ff', 2.2);
rim.position.set(-3.4, 2.6, -3.2);
scene.add(rim);

const fill = new THREE.DirectionalLight('#ffe9d2', 0.5);
fill.position.set(-2.2, 1.2, 3.4);
scene.add(fill);

/* ---------------------------------------------------------------- helpers */

function resize() {
  const w = ui.stage.clientWidth;
  const h = ui.stage.clientHeight;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
  gridCamera.aspect = camera.aspect;
  gridCamera.updateProjectionMatrix();
}

function fmt(n, digits = 2) {
  return n.toFixed(digits);
}

function showError(msg) {
  ui.error.hidden = false;
  ui.error.textContent = msg;
  ui.loading.classList.add('is-done');
}

/* ---------------------------------------------------------------- model */

const loader = new GLTFLoader();

/* 换模型时把旧模型的 geometry / material / texture 全释放，否则每切一次涨几十 MB 显存 */
function disposeTree(root) {
  root.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    mats.forEach((m) => {
      Object.values(m).forEach((v) => { if (v && v.isTexture) v.dispose(); });
      m.dispose();
    });
  });
}

function teardownModel() {
  if (state.mainMixer) { state.mainMixer.stopAllAction(); state.mainMixer = null; }
  state.cells.forEach((c) => {
    c.mixer.stopAllAction();
    scene.remove(c.obj);
    disposeTree(c.obj);
  });
  state.cells = [];
  if (state.skeletonHelper) {
    state.skeletonHelper.geometry?.dispose?.();
    state.skeletonHelper.material?.dispose?.();
    scene.remove(state.skeletonHelper);
    state.skeletonHelper = null;
  }
  if (state.model) {
    scene.remove(state.model);
    disposeTree(state.model);
    state.model = null;
  }
  state.clips.forEach((c) => c.action?.stop());
  state.clips = [];
  state.current = 0;
  state.bones = 0;
  state.skinned = 0;
  state.rigged = false;
  state.grid = false;
  ui.grid.checked = false;
  ui.gridLabels.hidden = true;
  ui.gridLabels.innerHTML = '';
  ui.clips.innerHTML = '';
  ui.ticks.innerHTML = '';
  ui.speeds.innerHTML = '';
  ui.scrub.value = '0';
  document.body.classList.remove('grid-mode', 'is-static');
  ui.stage.classList.remove('is-grid');
}

/** 从载入后的场景图实测骨骼状况——索引里显示的数字以此为准，不写死 */
function measure(model) {
  const bones = new Set();
  let skinned = 0;
  let meshes = 0;
  let tris = 0;
  model.traverse((o) => {
    if (o.isBone) bones.add(o.uuid);
    if (o.isSkinnedMesh) {
      skinned += 1;
      o.skeleton?.bones.forEach((b) => bones.add(b.uuid));
    }
    if (o.isMesh) {
      meshes += 1;
      const g = o.geometry;
      if (g) tris += g.index ? g.index.count / 3 : (g.attributes.position?.count || 0) / 3;
    }
  });
  return { bones: bones.size, skinned, meshes, tris: Math.round(tris) };
}

function loadModel(entry) {
  teardownModel();
  state.entry = entry;
  ui.error.hidden = true;
  ui.loading.style.display = '';
  ui.loading.classList.remove('is-done');
  ui.loading.firstElementChild.textContent = `载入 ${entry.title}.glb`;
  const path = entry.url.replace('../', '');
  ui.statPath.textContent = path;
  ui.statPath.title = path;
  renderModelList(entry.id, 'loading');
  loader.load(
    entry.url,
    (gltf) => onLoaded(gltf, entry),
    (evt) => {
      if (evt.lengthComputable && evt.total) {
        const pct = Math.round((evt.loaded / evt.total) * 100);
        ui.loading.firstElementChild.textContent = `载入 ${entry.title}.glb · ${pct}%`;
      }
    },
    (err) => {
      showError(`模型载入失败：${err?.message || err}\n检查是否用 HTTP 打开（file:// 会被 CORS 拦）。`);
      renderModelList(entry.id, 'error');
    }
  );
}

function onLoaded(gltf, entry) {
  const model = gltf.scene;
  model.traverse((o) => {
    if (o.isMesh) {
      o.castShadow = true;
      o.receiveShadow = true;
      if (o.material) {
        o.material.envMapIntensity = 1.1;
        o.material.side = THREE.FrontSide;
      }
    }
  });
  scene.add(model);
  state.model = model;

  const m = measure(model);
  state.bones = m.bones;
  state.skinned = m.skinned;
  state.rigged = m.bones > 0 && m.skinned > 0;

  // glTF 动画名 → 索引元数据
  const byName = new Map((gltf.animations || []).map((a) => [a.name, a]));
  state.clips = CLIPS.filter((c) => byName.has(c.id)).map((c) => {
    const clip = byName.get(c.id);
    return { def: c, clip, duration: clip.duration };
  });

  if (state.clips.length) {
    enterRiggedMode();
    state.mainMixer = new THREE.AnimationMixer(model);
    state.clips.forEach((c) => {
      c.action = state.mainMixer.clipAction(c.clip);
      c.action.clampWhenFinished = !c.def.loop;
      applyLoop(c);
    });
    buildClipList();
    buildGridCells();
    addSkeletonHelper();
    selectClip(0, true);
  } else {
    // 有骨架没动作（刚绑完骨的副本）和没骨架的静态高模，是两种状态
    if (state.rigged) addSkeletonHelper();
    enterNoClipMode(entry, state.rigged);
  }

  buildSpeedButtons();
  updateStats(m);
  renderModelList(entry.id, 'ready');

  ui.loading.classList.add('is-done');
  setTimeout(() => { ui.loading.style.display = 'none'; }, 450);
  ui.play.classList.add('is-playing');

  const params = new URLSearchParams(location.search);
  if (params.get('clip') && state.clips.length) {
    const idx = state.clips.findIndex((c) => c.def.id === params.get('clip'));
    if (idx > 0) selectClip(idx);
  }
  if (params.get('grid') === '1' && state.clips.length) setGrid(true);
  resize();
}

function addSkeletonHelper() {
  if (!state.model) return;
  state.skeletonHelper = new THREE.SkeletonHelper(state.model);
  state.skeletonHelper.visible = false;
  state.skeletonHelper.material.linewidth = 1;
  scene.add(state.skeletonHelper);
}

/**
 * 没有动作的模型分两种：
 *   rigged=true   骨架 + 蒙皮都在，只是还没做 Action（绑完骨的副本）→ 骨架开关仍可用
 *   rigged=false  静态高模，glTF 里连 skeleton / skin 都没有 → 什么都关掉，只留视角
 */
function enterNoClipMode(entry, rigged) {
  document.body.classList.add('is-static');
  ui.play.disabled = true;
  ui.scrub.disabled = true;
  ui.grid.disabled = true;
  ui.skeleton.disabled = !rigged;
  ui.loop.disabled = true;
  ui.transportNote.hidden = false;
  ui.transportNote.textContent = rigged
    ? '已绑骨 · 未做动作 · 可开「骨架」看骨骼'
    : '静态模型 · 未绑骨 · 无动作';
  ui.hudMeta.hidden = true;

  ui.clips.innerHTML = '';
  const li = document.createElement('li');
  li.className = 'clip clip-empty';
  li.dataset.rigged = rigged ? 'yes' : 'no';
  li.innerHTML = `
    <span class="clip-no">00</span>
    <span class="clip-body">
      <span class="clip-name">无动作<em>no clips</em></span>
      <span class="clip-desc">${rigged
        ? `骨架与蒙皮已就位（${state.bones} 骨 / ${state.skinned} 蒙皮网格），但 GLB 里还没有 animation`
        : '未绑骨：glTF 里没有 skeleton / skin / animation，只能看造型与比例'}</span>
    </span>`;
  ui.clips.appendChild(li);

  ui.hudKicker.textContent = rigged
    ? `RIGGED · NO CLIPS · ${entry.title}`
    : `STATIC · UNRIGGED · ${entry.title}`;
  ui.hudName.textContent = rigged ? '已绑骨' : '未绑骨';
  ui.hudTime.textContent = '0.00';
  ui.hudDur.textContent = '0.00';
}

function enterRiggedMode() {
  document.body.classList.remove('is-static');
  ui.play.disabled = false;
  ui.scrub.disabled = false;
  ui.grid.disabled = false;
  ui.skeleton.disabled = false;
  ui.loop.disabled = false;
  ui.transportNote.hidden = true;
  ui.transportNote.textContent = '静态模型 · 未绑骨 · 无动作';
  ui.hudMeta.hidden = false;
}

/* ---------------------------------------------------------------- model list */

function renderModelList(activeId, status = 'ready') {
  ui.models.innerHTML = '';
  MODELS.forEach((m) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'model';
    btn.dataset.model = m.id;
    btn.dataset.rig = m.rig;
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', m.id === activeId ? 'true' : 'false');
    if (m.id === activeId) btn.dataset.status = status;
    btn.innerHTML = `
      <span class="model-head">
        <span class="model-title">${m.title}</span>
        <span class="model-chip">${m.rig === 'rigged' ? '已绑骨' : '未绑骨'}</span>
      </span>
      <span class="model-meta">${m.variant} · ${m.expect}</span>`;
    btn.addEventListener('click', () => switchModel(m.id));
    ui.models.appendChild(btn);
  });
}

function switchModel(id) {
  const entry = MODELS.find((m) => m.id === id);
  if (!entry) return;
  if (state.entry?.id === id && state.model) return;   // 已经在看这个
  loadModel(entry);
}

/* ---------------------------------------------------------------- entry */

const startId = new URLSearchParams(location.search).get('model');
loadModel(MODELS.find((m) => m.id === startId) || MODELS[0]);

// 自检脚本（tools/check_site.mjs）用：只读地看一眼内部状态
window.__index = { state, MODELS };


function applyLoop(c) {
  const repeating = state.loop && c.def.loop;
  c.action.setLoop(repeating ? THREE.LoopRepeat : THREE.LoopOnce, repeating ? Infinity : 1);
  c.action.clampWhenFinished = !repeating;
}

/* ---------------------------------------------------------------- stats */

async function updateStats(m) {
  ui.statTris.textContent = m.tris > 0 ? `${Math.round(m.tris / 1000)}k` : '—';
  ui.statBones.textContent = m.bones > 0 ? `${m.bones}` : '0 · 未绑骨';
  ui.statBones.dataset.state = state.rigged ? 'rigged' : 'unrigged';
  ui.statClips.textContent = `${state.clips.length}`;

  // 骨骼状况明细：骨架 / 骨骼 / 蒙皮网格 / 动作
  ui.rigArmature.textContent = state.rigged ? '有' : '无';
  ui.rigArmature.dataset.state = state.rigged ? 'rigged' : 'unrigged';
  ui.rigBones.textContent = state.rigged ? `${m.bones}` : '0';
  ui.rigBones.dataset.state = state.rigged ? 'rigged' : 'unrigged';
  ui.rigSkin.textContent = `${m.skinned} / ${m.meshes}`;
  ui.rigSkin.dataset.state = state.rigged ? 'rigged' : 'unrigged';
  ui.rigClips.textContent = `${state.clips.length}`;
  ui.rigNote.textContent = state.entry.note;
  ui.rigNote.dataset.state = state.rigged ? 'rigged' : 'unrigged';

  try {
    const head = await fetch(state.entry.url, { method: 'HEAD' });
    const len = Number(head.headers.get('content-length') || 0);
    ui.statSize.textContent = len ? `${(len / 1024 / 1024).toFixed(0)} MB` : '—';
  } catch {
    ui.statSize.textContent = '—';
  }
}

/* ---------------------------------------------------------------- clip list */

function buildClipList() {
  ui.clips.innerHTML = '';
  state.clips.forEach((c, i) => {
    const li = document.createElement('li');
    const btn = document.createElement('button');
    btn.className = 'clip';
    btn.type = 'button';
    btn.setAttribute('role', 'option');
    btn.setAttribute('aria-selected', i === state.current ? 'true' : 'false');
    const frames = Math.round(c.duration * c.def.fps);
    btn.innerHTML = `
      <span class="clip-no">${String(i + 1).padStart(2, '0')}</span>
      <span class="clip-body">
        <span class="clip-name">${c.def.zh}<em>${c.def.en}</em></span>
        <span class="clip-desc">${c.def.desc}</span>
      </span>
      <span class="clip-frames"><b>${fmt(c.duration)}s</b>${frames}f</span>`;
    btn.addEventListener('click', () => selectClip(i));
    li.appendChild(btn);
    ui.clips.appendChild(li);
  });
}

function buildSpeedButtons() {
  ui.speeds.innerHTML = '';
  SPEEDS.forEach((s) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = `${s}×`;
    b.setAttribute('aria-pressed', s === state.speed ? 'true' : 'false');
    b.addEventListener('click', () => {
      state.speed = s;
      [...ui.speeds.children].forEach((el) => el.setAttribute('aria-pressed', el === b ? 'true' : 'false'));
    });
    ui.speeds.appendChild(b);
  });
}

function buildTicks(c) {
  ui.ticks.innerHTML = '';
  const frames = Math.round(c.duration * c.def.fps);
  const step = Math.max(1, Math.round(frames / 12));
  for (let f = 0; f <= frames; f += step) {
    const i = document.createElement('i');
    i.style.left = `${(f / frames) * 100}%`;
    ui.ticks.appendChild(i);
  }
}

function selectClip(index, instant = false) {
  const c = state.clips[index];
  if (!c) return;
  state.current = index;

  state.clips.forEach((other, i) => {
    if (i === index) return;
    other.action.stop();
  });
  c.action.reset();
  applyLoop(c);
  c.action.setEffectiveWeight(1);
  c.action.play();
  // 暂停状态下切动作：mixer 不推进，必须手动求值一次，否则停在 bind pose（T-pose）
  state.mainMixer.update(0);

  [...ui.clips.querySelectorAll('.clip')].forEach((el, i) =>
    el.setAttribute('aria-selected', i === index ? 'true' : 'false'));

  ui.hudName.textContent = c.def.zh;
  ui.hudKicker.textContent = `${c.def.en.toUpperCase()} · ${Math.round(c.duration * c.def.fps)}f @ ${c.def.fps}fps`;
  ui.hudDur.textContent = fmt(c.duration);
  buildTicks(c);
  if (instant) ui.scrub.value = 0;
  updateSkeletonHelper();
  syncGridLabels();
}

/* ---------------------------------------------------------------- grid mode */

function buildGridCells() {
  state.cells = state.clips.map((c) => {
    const obj = cloneSkinned(state.model);
    obj.visible = false;
    obj.traverse((o) => {
      if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; }
    });
    scene.add(obj);
    const mixer = new THREE.AnimationMixer(obj);
    const action = mixer.clipAction(c.clip);
    action.setLoop(state.loop && c.def.loop ? THREE.LoopRepeat : THREE.LoopOnce,
                   state.loop && c.def.loop ? Infinity : 1);
    action.clampWhenFinished = !(state.loop && c.def.loop);
    action.play();
    return { obj, mixer, action };
  });
  buildGridLabels();
}

function buildGridLabels() {
  ui.gridLabels.innerHTML = '';
  state.clips.forEach((c) => {
    const cell = document.createElement('div');
    cell.className = 'grid-cell-label';
    cell.innerHTML = `<span class="cell-tag"><strong>${c.def.zh}</strong><span>${c.def.en} · ${fmt(c.duration)}s · ${Math.round(c.duration * c.def.fps)}f</span></span>`;
    ui.gridLabels.appendChild(cell);
  });
}

function updateSkeletonHelper() {
  if (!state.skeletonHelper) return;
  state.skeletonHelper.visible = ui.skeleton.checked && !state.grid;
}

function syncGridLabels() {
  ui.gridLabels.hidden = !state.grid;
  ui.stage.classList.toggle('is-grid', state.grid);
}

function setGrid(on) {
  if (!state.model) return;
  if (on && !state.cells.length) { ui.grid.checked = false; return; }   // 未绑骨模型没有动作可四联
  state.grid = on;
  ui.grid.checked = on;
  ui.gridLabels.hidden = !on;
  document.body.classList.toggle('grid-mode', on);
  syncGridLabels();
  state.cells.forEach((c) => { c.obj.visible = false; });
  state.model.visible = !on;
  if (state.skeletonHelper) state.skeletonHelper.visible = !on && ui.skeleton.checked;
  if (!on) {
    state.cells.forEach((c) => c.action.stop());
    state.clips[state.current].action.reset().play();
    if (state.mainMixer) state.mainMixer.update(0);
  } else {
    state.clips.forEach((c) => c.action.stop());
    state.cells.forEach((cell, i) => {
      cell.action.reset();
      const repeating = state.loop && state.clips[i].def.loop;
      cell.action.setLoop(repeating ? THREE.LoopRepeat : THREE.LoopOnce, repeating ? Infinity : 1);
      cell.action.clampWhenFinished = !repeating;
      cell.action.play();
      cell.mixer.update(0);   // 暂停时也要把第一帧摆出来
    });
  }
  resize();
}

/* ---------------------------------------------------------------- interaction */

function togglePlay() {
  if (!state.clips.length) return;
  state.playing = !state.playing;
  ui.play.classList.toggle('is-playing', state.playing);
  if (!state.playing && state.mainMixer) state.mainMixer.timeScale = 0;
  if (state.playing && state.mainMixer) state.mainMixer.timeScale = 1;
}

function onScrub() {
  const c = state.clips[state.current];
  if (!c) return;
  const t = (Number(ui.scrub.value) / 1000) * c.duration;
  c.action.reset();
  c.action.play();
  c.action.time = Math.min(t, c.duration - 0.0001);
  state.mainMixer.update(0);
}

function resetCamera() {
  camera.position.copy(CAM_HOME);
  controls.target.copy(CAM_TARGET);
  controls.update();
}

ui.play.addEventListener('click', togglePlay);
ui.reset.addEventListener('click', resetCamera);
ui.scrub.addEventListener('input', onScrub);
ui.grid.addEventListener('change', (e) => setGrid(e.target.checked));
ui.skeleton.addEventListener('change', (e) => {
  if (state.skeletonHelper) state.skeletonHelper.visible = e.target.checked && !state.grid;
});
ui.autorotate.addEventListener('change', (e) => { controls.autoRotate = e.target.checked; });
ui.loop.addEventListener('change', (e) => {
  state.loop = e.target.checked;
  state.clips.forEach((c) => { applyLoop(c); });
  state.cells.forEach((cell, i) => {
    const repeating = state.loop && state.clips[i].def.loop;
    cell.action.setLoop(repeating ? THREE.LoopRepeat : THREE.LoopOnce, repeating ? Infinity : 1);
    cell.action.clampWhenFinished = !repeating;
  });
});

window.addEventListener('keydown', (e) => {
  if (e.target.matches('input')) return;
  const k = e.key.toLowerCase();
  if (e.code === 'Space') { e.preventDefault(); togglePlay(); }
  else if (k === 'arrowright' && state.clips.length) { selectClip((state.current + 1) % state.clips.length); }
  else if (k === 'arrowleft' && state.clips.length) { selectClip((state.current - 1 + state.clips.length) % state.clips.length); }
  else if (k === 'g' && !ui.grid.disabled) setGrid(!state.grid);
  else if (k === 's' && !ui.skeleton.disabled) {
    ui.skeleton.checked = !ui.skeleton.checked;
    ui.skeleton.dispatchEvent(new Event('change'));
  }
  else if (k === 'l') { ui.loop.checked = !ui.loop.checked; ui.loop.dispatchEvent(new Event('change')); }
  else if (k === 'r') resetCamera();
  else if (k === 'm') {
    const i = MODELS.findIndex((m) => m.id === state.entry?.id);
    switchModel(MODELS[(i + 1) % MODELS.length].id);
  }
  else if (/^[1-4]$/.test(k)) {
    const i = Number(k) - 1;
    if (i < state.clips.length) selectClip(i);
  }
});

window.addEventListener('resize', resize);

/* ---------------------------------------------------------------- loop */

const clock = new THREE.Clock();

function tick() {
  requestAnimationFrame(tick);
  const dt = clock.getDelta();
  const d = dt * state.speed;

  if (state.playing) {
    if (state.grid) state.cells.forEach((c) => c.mixer.update(d));
    else if (state.mainMixer) state.mainMixer.update(d);
  }

  if (!state.grid && state.clips[state.current]) {
    const c = state.clips[state.current];
    const t = c.action.time % (c.duration || 1);
    ui.hudTime.textContent = fmt(c.action.isRunning() ? c.action.time : t);
    if (d > 0 && state.playing) ui.scrub.value = String(Math.round((c.action.time / c.duration) * 1000));
  }

  if (state.skeletonHelper) {
    state.skeletonHelper.visible = ui.skeleton.checked && !state.grid;
  }

  controls.update();

  if (state.grid) {
    const w = ui.stage.clientWidth;
    const h = ui.stage.clientHeight;
    const hw = Math.floor(w / 2);
    const hh = Math.floor(h / 2);
    renderer.setScissorTest(true);
    state.cells.forEach((cell, i) => {
      const col = i % 2;
      const row = Math.floor(i / 2);
      const x = col * hw;
      const y = (1 - row) * hh;
      renderer.setViewport(x, y, hw, hh);
      renderer.setScissor(x, y, hw, hh);
      state.cells.forEach((other, j) => { other.obj.visible = i === j; });
      renderer.render(scene, gridCamera);
    });
    renderer.setScissorTest(false);
    renderer.setViewport(0, 0, w, h);
  } else {
    renderer.render(scene, camera);
  }
}

resize();
tick();
