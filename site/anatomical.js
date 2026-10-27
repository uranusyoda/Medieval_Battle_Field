import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { clone as cloneSkinned } from 'three/addons/utils/SkeletonUtils.js';

const $ = (s) => document.querySelector(s);
const MODEL_DIR = '../assets/models/characters/parts/';
const MANIFEST_URL = new URL(MODEL_DIR + 'templar_anatomical_animations.json', location.href);
const FALLBACK = [
  ['idle', '待机', true, '自然站姿与轻微呼吸，查看整体骨架的稳定性。', 'body'],
  ['walk', '行走', true, '双腿交替迈步，手臂自然反向摆动。', 'body'],
  ['run', '奔跑', true, '更大的步幅与屈肘摆臂，观察运动中的身体协调。', 'body'],
  ['jump', '跳跃', false, '预备、蹬伸、腾空与落地缓冲。', 'body'],
  ['crouch', '忍者低姿', true, '前后错步、低重心，双臂错开辅助平衡。', 'body'],
  ['grip', '握持', true, '四指依次屈曲，拇指向掌内对掌。', 'hand'],
  ['finger_wave', '逐指弯曲', true, '分别弯曲每根手指，查看独立指骨与指缝变形。', 'hand'],
  ['wrist', '转腕', true, '手掌屈伸与转动，观察手腕和袖口的过渡。', 'hand'],
].map(([id,label,loop,description,focus])=>({id,label,loop,description,focus}));
const state = { ready:false, playing:true, grid:false, skeleton:false, speed:1,
  clip:'idle', camera:'three', loop:true, userCamera:false, frames:0, error:null };
let manifest={fps:24,clips:FALLBACK}, renderer, scene, camera, controls, root, mixer, currentAction, skeleton;
let animations=[], cells=[], env, lastTime=performance.now(), handFollow=null;
const clockVector=new THREE.Vector3(), handLast=new THREE.Vector3();
const stage=$('#stage'), canvas=$('#motion-canvas');
const resizeObserver = new ResizeObserver(resize);

const lightbox=$('#lightbox');
for (const button of document.querySelectorAll('.gallery-item')) {
  const url=button.href,label=button.querySelector('img').alt;
  button.addEventListener('click',(event)=>{event.preventDefault(); $('#lightbox-image').src=url; $('#lightbox-image').alt=label;
    $('#lightbox-caption').textContent=label; $('#lightbox-original').href=url; lightbox.showModal(); });
}
$('.lightbox-close').addEventListener('click',()=>lightbox.close());
lightbox.addEventListener('click',(e)=>{if(e.target===lightbox)lightbox.close();});
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{
  document.querySelectorAll('[data-filter]').forEach(b=>b.classList.toggle('active',b===button));
  document.querySelectorAll('.gallery-item').forEach(item=>{item.hidden=button.dataset.filter!=='all'&&item.dataset.type!==button.dataset.filter;});
}));

function renderClipList(){
  $('#clip-list').replaceChildren();
  manifest.clips.forEach((entry,index)=>{
    const button=document.createElement('button'); button.className='clip-button';button.id=`clip-${entry.id}`;
    button.setAttribute('role','tab');button.setAttribute('aria-selected',String(state.clip===entry.id));
    button.setAttribute('aria-controls','stage');button.dataset.clip=entry.id;
    button.innerHTML=`<span class="clip-index">${String(index+1).padStart(2,'0')}</span><span class="clip-title"></span><span class="clip-arrow">↗</span>`;
    const label=button.querySelector('.clip-title');label.textContent=entry.label;
    const small=document.createElement('small');small.textContent=entry.id.replaceAll('_',' ').toUpperCase();label.append(small);
    button.addEventListener('click',()=>selectClip(entry.id));$('#clip-list').append(button);
  });
}
renderClipList();

function fail(error){
  state.error=error instanceof Error?error.message:String(error);state.ready=false;
  $('#loading').hidden=true;$('#error').hidden=false;$('#asset-status').textContent='三维展品暂未就绪';
  const local=location.protocol==='file:';
  $('#error-detail').textContent=local?'请通过本地服务打开页面。\n在项目目录运行 ./tools/serve_site.sh，再访问\nhttp://127.0.0.1:8765/site/anatomical.html':`载入失败：${state.error}\n请检查模型文件是否完整，或刷新重试。`;
  console.error('[Anatomical showcase]',error);
}
function createScene({overview=false}={}){
  const s=new THREE.Scene();s.background=new THREE.Color('#252c2b');s.environment=env;
  s.add(new THREE.HemisphereLight(0xf8eee0,0x767c6d,1.7));
  const key=new THREE.DirectionalLight(0xffeddc,2.2);key.position.set(-3,4,4);
  key.target.position.set(0,1,0);s.add(key.target);key.castShadow=true;
  key.shadow.mapSize.set(overview?512:1024,overview?512:1024);
  Object.assign(key.shadow.camera,{left:-2.2,right:2.2,top:2.2,bottom:-2.2,near:.3,far:12});
  key.shadow.camera.updateProjectionMatrix();
  key.shadow.bias=-.00015;key.shadow.normalBias=.006;key.shadow.radius=3;
  key.shadow.intensity=.75;s.add(key);
  const rim=new THREE.DirectionalLight(0xcbd9cc,1.4);rim.position.set(2,3,-3);s.add(rim);
  const floor=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshStandardMaterial({color:0x353e38,roughness:.95}));
  floor.rotation.x=-Math.PI/2;floor.position.y=-.008;floor.receiveShadow=true;s.add(floor);
  const grid=new THREE.GridHelper(8,32,0x63705b,0x414b40);grid.material.transparent=true;grid.material.opacity=.21;grid.position.y=-.006;s.add(grid);
  return s;
}
function makeCamera(){return new THREE.PerspectiveCamera(33,1,.005,100);}
function getBone(model,name){const target=name.replace(/[^a-z0-9]/gi,'').toLowerCase();let found=null;model.traverse(o=>{if(o.isBone&&o.name.replace(/[^a-z0-9]/gi,'').toLowerCase()===target)found=o;});return found;}
function getHandTarget(model,side){
  const bone=getBone(model,`hand.${side}`)||model;
  const point=bone.getWorldPosition(new THREE.Vector3());
  const middle=getBone(model,`middle.01.${side}`);
  if(middle)point.lerp(middle.getWorldPosition(new THREE.Vector3()),.7);
  return {bone,point};
}
function presetCamera(which,cam=camera,model=root,follow=true,clipId=cam===camera?state.clip:null){
  if(!cam||!model)return;
  let target=new THREE.Vector3(0,.9,0),offset=new THREE.Vector3(2.6,.55,4.5);
  if(which==='front')offset.set(0,.25,4.8);
  if(which==='side')offset.set(4.8,.25,.02);
  if(which==='handL'||which==='handR'){
    const side=which==='handL'?'L':'R', found=getHandTarget(model,side);
    target=found.point;offset.set(side==='L'?.23:-.23,.30,.38);
    if(follow&&cam===camera){handFollow=found.bone;handFollow.getWorldPosition(handLast);}
  }else{
    if(cam===camera)handFollow=null;
    // The jumping silhouette rises above the standing frame. Leave room for
    // the raised hands as well as the feet, in the main view and grid cells.
    if(clipId==='jump'){target.y=1.25;offset.multiplyScalar(1.18);}
    if(clipId==='crouch'){target.y=.72;offset.multiplyScalar(.92);}
  }
  cam.position.copy(target).add(offset);cam.lookAt(target);cam.near=which.startsWith('hand')?.002:.01;cam.updateProjectionMatrix();
  if(cam===camera&&controls){controls.target.copy(target);controls.minDistance=which.startsWith('hand')?.12:1.1;controls.maxDistance=which.startsWith('hand')?1.6:10;controls.update();}
  if(cam===camera){state.camera=which;document.querySelectorAll('[data-camera]').forEach(b=>b.classList.toggle('active',b.dataset.camera===which));}
}
function applyLoop(action,entry,loop){action.setLoop(loop?THREE.LoopRepeat:THREE.LoopOnce,loop?Infinity:1);action.clampWhenFinished=!loop;}
function selectClip(id,{autoCamera=true}={}){
  const entry=manifest.clips.find(c=>c.id===id);if(!entry)return false;
  if(state.grid)setGrid(false);
  state.clip=id;state.loop=entry.loop!==false;
  const clip=animations.find(c=>c.name===id);
  if(mixer&&clip){mixer.stopAllAction();currentAction=mixer.clipAction(clip);currentAction.reset().setEffectiveWeight(1).setEffectiveTimeScale(1);applyLoop(currentAction,entry,state.loop);currentAction.play();mixer.update(0);state.playing=true;}
  $('#active-no').textContent=String(manifest.clips.indexOf(entry)+1).padStart(2,'0');$('#active-label').textContent=entry.label;$('#active-en').textContent=id.replaceAll('_',' ').toUpperCase();
  $('#clip-description').textContent=entry.description||'';
  const duration=clip?.duration||entry.duration||0;$('#time-duration').textContent=duration?duration.toFixed(2)+'s':'—';
  $('#clip-meta').textContent=duration?`${entry.frames||Math.round(duration*(manifest.fps||24))} F / ${manifest.fps||24} FPS`:'—';
  document.querySelectorAll('.clip-button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.clip===id)));
  $('#btn-loop').setAttribute('aria-pressed',String(state.loop));
  if(autoCamera&&root){state.userCamera=false;presetCamera(entry.focus==='hand'?'handL':'three');}
  updateTransport();return true;
}
function setPlaying(value){
  if(!state.ready)return;
  if(value&&currentAction){
    if(currentAction.time>=currentAction.getClip().duration-.001){currentAction.reset();currentAction.play();}
    currentAction.paused=false;
  }
  state.playing=Boolean(value);updateTransport();
}
function updateTransport(){
  $('#btn-play').textContent=state.playing?'Ⅱ':'▶';$('#btn-play').setAttribute('aria-label',state.playing?'暂停':'播放');
  $('#btn-loop').setAttribute('aria-pressed',String(state.loop));
  $('#btn-skeleton').setAttribute('aria-pressed',String(state.skeleton));$('#btn-grid').setAttribute('aria-pressed',String(state.grid));
}
function buildCells(){
  if(cells.length||!root)return;
  const labels=$('#grid-labels');labels.replaceChildren();
  for(const entry of manifest.clips){
    const model=cloneSkinned(root),s=createScene({overview:true});s.add(model);const m=new THREE.AnimationMixer(model);
    const clip=animations.find(c=>c.name===entry.id);let action=null;
    if(clip){action=m.clipAction(clip);action.setLoop(THREE.LoopRepeat,Infinity).play();m.update(0);}
    const cam=makeCamera();presetCamera(entry.focus==='hand'?'handL':'three',cam,model,false,entry.id);
    const helper=new THREE.SkeletonHelper(model);helper.visible=state.skeleton;helper.material.depthTest=false;helper.material.transparent=true;helper.material.opacity=.75;helper.renderOrder=10;s.add(helper);
    cells.push({scene:s,model,mixer:m,action,camera:cam,helper,entry});
    const label=document.createElement('div');label.className='grid-label';const b=document.createElement('button');b.textContent=entry.label;
    const small=document.createElement('small');small.textContent=entry.id.replaceAll('_',' ').toUpperCase();b.append(small);
    b.addEventListener('click',()=>{setGrid(false);selectClip(entry.id);});label.append(b);labels.append(label);
  }
}
function setGrid(value){
  if(!state.ready)return;
  state.grid=Boolean(value);if(state.grid)buildCells();stage.classList.toggle('grid-mode',state.grid);$('#grid-labels').hidden=!state.grid;
  controls.enabled=!state.grid;$('#scrub').disabled=state.grid||!state.ready;$('#btn-loop').disabled=state.grid||!state.ready;
  document.querySelectorAll('[data-camera]').forEach(b=>b.disabled=state.grid);
  const entry=manifest.clips.find(c=>c.id===state.clip);
  $('#clip-description').textContent=state.grid?'八套动作独立循环播放；点击每格标题，可单独查看。':entry?.description||'';
  $('#clip-meta').textContent=state.grid?`08 CLIPS / ${manifest.fps||24} FPS`:`${entry?.frames||0} F / ${manifest.fps||24} FPS`;
  $('#stage-kicker').hidden=state.grid;updateTransport();resize();
}
function toggleSkeleton(value=!state.skeleton){state.skeleton=Boolean(value);if(skeleton)skeleton.visible=state.skeleton;cells.forEach(c=>c.helper.visible=state.skeleton);updateTransport();}
function resize(){
  if(!renderer||!camera)return;const width=stage.clientWidth;
  if(state.grid){
    const {cols,rows}=gridLayout();
    $('#grid-labels').style.gridTemplateColumns=`repeat(${cols},1fr)`;
    $('#grid-labels').style.gridTemplateRows=`repeat(${rows},1fr)`;
    stage.style.height=cols===2?'1000px':'650px';
  }else stage.style.height='';
  const actualHeight=stage.clientHeight;
  renderer.setSize(width,actualHeight,false);camera.aspect=width/actualHeight;camera.updateProjectionMatrix();
}
function gridLayout(){
  const cols=stage.clientWidth<700?2:4;
  return {cols,rows:Math.ceil((cells.length||manifest.clips.length)/cols)};
}
function animate(now){
  requestAnimationFrame(animate);const delta=Math.min((now-lastTime)/1000,.06);lastTime=now;
  if(!state.ready||!renderer)return;
  const dt=state.playing?delta*state.speed:0;
  if(!state.grid){
    mixer.update(dt);
    if(handFollow){
      handFollow.getWorldPosition(clockVector);const shift=clockVector.clone().sub(handLast);
      camera.position.add(shift);controls.target.add(shift);handLast.copy(clockVector);
    }
    controls.update();renderer.setScissorTest(false);renderer.setViewport(0,0,stage.clientWidth,stage.clientHeight);renderer.render(scene,camera);
    const duration=currentAction?.getClip().duration||1,time=Math.min(currentAction?.time||0,duration);
    if(!$('#scrub').matches(':active'))$('#scrub').value=String(Math.round(time/duration*1000));
    $('#time-current').textContent=time.toFixed(2)+'s';
  }else{
    const {cols,rows}=gridLayout(),width=stage.clientWidth,height=stage.clientHeight;
    renderer.setScissorTest(false);renderer.clear();renderer.setScissorTest(true);
    cells.forEach((cell,i)=>{
      cell.mixer.update(dt);
      if(cell.entry.focus==='hand')presetCamera('handL',cell.camera,cell.model,false);
      const x=Math.round((i%cols)*width/cols),right=Math.round((i%cols+1)*width/cols);
      const top=Math.round(Math.floor(i/cols)*height/rows),bottom=Math.round((Math.floor(i/cols)+1)*height/rows);
      const w=right-x,h=bottom-top,y=height-bottom;
      cell.camera.aspect=w/h;cell.camera.updateProjectionMatrix();renderer.setViewport(x,y,w,h);renderer.setScissor(x,y,w,h);renderer.render(cell.scene,cell.camera);
    });
    renderer.setScissorTest(false);
  }
  state.frames++;
}

function assetURL(value,fallback){
  if(!value)return new URL(fallback,MANIFEST_URL).href;
  if(value.startsWith('assets/'))return new URL('../'+value,location.href).href;
  if(value.startsWith('../')||value.startsWith('/'))return new URL(value,location.href).href;
  return new URL(value,MANIFEST_URL).href;
}
async function boot(){
  if(location.protocol==='file:'){fail('Local file protocol');return;}
  try{
    const response=await fetch(MANIFEST_URL,{cache:'no-store'});if(response.ok){const data=await response.json();if(Array.isArray(data.clips)&&data.clips.length){manifest={...data,clips:data.clips.map(c=>({...FALLBACK.find(f=>f.id===c.id),...c,label:c.label||c.zh||c.id}))};}}
  }catch(error){console.warn('Using clip labels bundled with the page:',error);}
  renderClipList();
  try{
    renderer=new THREE.WebGLRenderer({canvas,antialias:true,powerPreference:'high-performance'});renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x252c2b);
    renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;
    renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    const pmrem=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment();env=pmrem.fromScene(room,.04).texture;room.dispose();pmrem.dispose();
    scene=createScene();camera=makeCamera();controls=new OrbitControls(camera,canvas);controls.enableDamping=true;controls.dampingFactor=.07;controls.maxPolarAngle=Math.PI*.87;
    controls.addEventListener('start',()=>{state.userCamera=true;});
    resizeObserver.observe(stage);resize();
    const loader=new GLTFLoader();const modelURL=new URL(assetURL(manifest.preview,'templar_anatomical_animated_preview.glb'));
    if(manifest.assetVersion)modelURL.searchParams.set('v',manifest.assetVersion);
    let timeout;const loading=loader.loadAsync(modelURL.href,e=>{$('#loading-detail').textContent=e.total?`正在载入模型与动作 · ${Math.round(e.loaded/e.total*100)}%`:`正在载入模型 · ${(e.loaded/1048576).toFixed(1)} MB`;});
    const gltf=await Promise.race([loading,new Promise((_,reject)=>{timeout=setTimeout(()=>reject(new Error('模型载入超过 120 秒，请检查本地服务')),120000);})]).finally(()=>clearTimeout(timeout));
    root=gltf.scene;animations=gltf.animations;scene.add(root);
    root.traverse(o=>{if(o.isMesh){o.castShadow=true;o.receiveShadow=true;o.frustumCulled=false;}});
    const uniqueBones=new Set(),meshes=[];root.traverse(o=>{if(o.isBone)uniqueBones.add(o.uuid);if(o.isSkinnedMesh){meshes.push(o);o.skeleton.bones.forEach(b=>uniqueBones.add(b.uuid));}});
    const missing=manifest.clips.filter(c=>!animations.find(a=>a.name===c.id));if(missing.length)throw new Error('模型缺少动画：'+missing.map(c=>c.id).join('、'));
    $('#count-bones').textContent=uniqueBones.size;$('#count-clips').textContent=String(animations.length).padStart(2,'0');$('#count-meshes').textContent=meshes.length;
    $('#asset-status').textContent=`${uniqueBones.size} 骨骼 · ${animations.length} 动作 · 已就绪`;
    mixer=new THREE.AnimationMixer(root);mixer.addEventListener('finished',()=>{if(!state.loop){state.playing=false;updateTransport();}});
    skeleton=new THREE.SkeletonHelper(root);skeleton.material.depthTest=false;skeleton.material.transparent=true;skeleton.material.opacity=.8;skeleton.renderOrder=10;skeleton.visible=state.skeleton;scene.add(skeleton);
    state.ready=true;$('#loading').hidden=true;
    ['#btn-play','#btn-replay','#scrub','#speed','#btn-loop'].forEach(s=>$(s).disabled=false);
    const requested=new URLSearchParams(location.search).get('clip');selectClip(manifest.clips.some(c=>c.id===requested)?requested:manifest.clips[0].id);
    const requestedView=new URLSearchParams(location.search).get('view');
    if(['three','front','side','handL','handR'].includes(requestedView))presetCamera(requestedView);
    if(new URLSearchParams(location.search).get('grid')==='1')setGrid(true);
    if(new URLSearchParams(location.search).get('skeleton')==='1')toggleSkeleton(true);
  }catch(error){fail(error);}
}
$('#btn-retry').addEventListener('click',()=>location.reload());
$('#btn-play').addEventListener('click',()=>setPlaying(!state.playing));
$('#btn-replay').addEventListener('click',()=>{if(currentAction){currentAction.reset().play();mixer.update(0);}cells.forEach(c=>{c.action?.reset().play();c.mixer.update(0);});setPlaying(true);});
$('#btn-loop').addEventListener('click',()=>{state.loop=!state.loop;const entry=manifest.clips.find(c=>c.id===state.clip);if(currentAction){applyLoop(currentAction,entry,state.loop);if(state.loop){currentAction.paused=false;if(currentAction.time>=currentAction.getClip().duration-.001)currentAction.reset().play();}}updateTransport();});
$('#btn-grid').addEventListener('click',()=>setGrid(!state.grid));
$('#btn-skeleton').addEventListener('click',()=>toggleSkeleton());
$('#speed').addEventListener('change',e=>state.speed=Number(e.target.value));
$('#scrub').addEventListener('input',e=>{if(!currentAction)return;const duration=currentAction.getClip().duration;currentAction.paused=false;currentAction.enabled=true;currentAction.time=Number(e.target.value)/1000*duration;mixer.update(0);state.playing=false;updateTransport();});
document.querySelectorAll('[data-camera]').forEach(b=>b.addEventListener('click',()=>presetCamera(b.dataset.camera)));
document.addEventListener('keydown',e=>{
  if(lightbox.open||e.target.closest('input,select,textarea,button,a,[contenteditable]'))return;
  if(e.code==='Space'){e.preventDefault();setPlaying(!state.playing);}else if(e.key.toLowerCase()==='s')toggleSkeleton();else if(e.key.toLowerCase()==='g')setGrid(!state.grid);
  else if(/^[1-8]$/.test(e.key)){const clip=manifest.clips[Number(e.key)-1];if(clip)selectClip(clip.id);}
});
canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();fail('显卡上下文已中断，请重新载入。');});
Object.defineProperty(window,'__anatomicalShowcase',{value:Object.freeze({
  getState:()=>({...state,time:currentAction?.time||0,duration:currentAction?.getClip().duration||0,
    clips:animations.map(c=>({name:c.name,duration:c.duration,tracks:c.tracks.length})),
    bones:Number($('#count-bones').textContent),meshes:Number($('#count-meshes').textContent),cells:cells.length}),
  setClip:(id)=>selectClip(id),setPlaying,setGrid,setSkeleton:toggleSkeleton,setCamera:presetCamera,
  scrub:(fraction)=>{if(currentAction){currentAction.enabled=true;currentAction.paused=false;currentAction.time=THREE.MathUtils.clamp(fraction,0,1)*currentAction.getClip().duration;mixer.update(0);state.playing=false;updateTransport();}},
}),writable:false});
requestAnimationFrame(animate);boot();
