import * as THREE from 'three';
import { GLTFLoader } from './vendor/GLTFLoader.js';

const mount=document.querySelector('#cortana-sprite');
const note=document.querySelector('#modelNote');
const scene=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(30,1,.01,10);
let renderer,model,rig={},state='idle',full=false,disposed=false;
const bones=new Map(),morphs=[];
const motion=matchMedia('(prefers-reduced-motion: reduce)');
let nextBlink=performance.now()/1000+2.8,blinkStart=-10;
let pointer={x:0,y:0},gaze={x:0,y:0};
let mouth={jaw:0,wide:0,round:0,close:0,fv:0,tongue:0};
let speech=null;
// Character performance is independent of the speech mouth poses.
let stateSince=0,arrivedAt=0,nextIdle=0,idleGesture=null,ackAt=-100;
let nextLook=0,eyeLook={x:0,y:0},eyeTarget={x:0,y:0};
let expression={smile:.06,brow:.025,squint:0,smirk:0,tilt:0,pitch:0,yaw:0};
let characterStrength=1,performanceStyle='warm',lastPointer=0;
const lights=[];
const vec=new THREE.Vector3(),q=new THREE.Quaternion();
function bell(t,start,duration){const u=(t-start)/duration;return u>0&&u<1?Math.sin(Math.PI*u)**2:0;}
function changeState(s){
 if(state===s)return;
 const now=performance.now()/1000;
 if(s==='listening'||(state==='speaking'&&s==='idle')){ackAt=now;nextBlink=Math.min(nextBlink,now+.15);}
 state=s;stateSince=now;idleGesture=null;
}

function framing(){
 camera.position.set(0,full?.85:1.39,full?3.05:.94);
 camera.lookAt(0,full?.78:1.35,0);
}
function resize(){
 if(!renderer)return;
 const {width,height}=mount.getBoundingClientRect();
 renderer.setSize(width,height,false);camera.aspect=width/height;camera.updateProjectionMatrix();
}
function rotate(name,axis,angle){
 const b=bones.get(name);if(!b||!rig[name])return;
 vec.fromArray(rig[name][axis]);q.setFromAxisAngle(vec,angle);b.node.quaternion.multiply(q);
}
function translate(name,axis,amount){
 const b=bones.get(name);if(!b||!rig[name])return;
 b.node.position.addScaledVector(vec.fromArray(rig[name][axis]),amount);
}
function shape(name,value){for(const m of morphs){const i=m.morphTargetDictionary[name];if(i!==undefined)m.morphTargetInfluences[i]=value;}}

// SAPI's 22 viseme IDs mapped to this rig's controls. These are authored poses,
// not the missing original game's facial animations.
export function poseFor(id){
 const p={jaw:0,wide:0,round:0,close:0,fv:0,tongue:0};
 if(id===0)return p;
 if(id===21){p.close=1;return p;} // P B M
 if(id===18){p.jaw=.10;p.fv=1;return p;} // F V
 if(id===17){p.jaw=.22;p.tongue=1;return p;} // TH
 if([4,6,11].includes(id)){p.jaw=.32;p.wide=.65;}
 else if([3,9].includes(id)){p.jaw=.55;p.round=.65;}
 else if([7,8,10].includes(id)){p.jaw=.24;p.round=.9;}
 else if([1,2].includes(id)){p.jaw=.85;p.wide=.08;}
 else if(id===5){p.jaw=.32;p.round=.28;}
 else if([13,14,16].includes(id)){p.jaw=.18;p.round=.12;}
 else {p.jaw=.22;p.wide=.12;}
 if(id===14)p.tongue=.6;
 return p;
}
function targetPose(){
 if(!speech)return poseFor(0);
 const t=speech.clock();
 if(t<0)return poseFor(0);
 const cues=speech.cues;
 let i=speech.index;
 while(i+1<cues.length&&cues[i+1].time<=t)i++;
 speech.index=i;
 const cue=cues[i];
 if(!cue||t<cue.time||t>speech.duration)return poseFor(0);
 const p=poseFor(cue.id),next=cues[i+1];
 if(next){
  const anticipation=Math.min(.065,Math.max(.015,(next.time-cue.time)*.3));
  const blend=THREE.MathUtils.smoothstep(t,next.time-anticipation,next.time);
  const n=poseFor(next.id);
  for(const k in p)p[k]=THREE.MathUtils.lerp(p[k],n[k],blend);
 }
 return p;
}
let last=performance.now();
function frame(now){
 if(disposed)return;
 requestAnimationFrame(frame);
 if(matchMedia('(pointer: coarse)').matches&&now-last<1000/30)return;
 const dt=Math.min(.05,(now-last)/1000);last=now;
 if(!model||document.hidden)return;
 const t=now/1000;
 const strength=motion.matches?0:characterStrength;
 for(const b of bones.values()){b.node.quaternion.copy(b.rotation);b.node.position.copy(b.position);}
 for(const m of morphs)m.morphTargetInfluences.fill(0);
 rotate('bip_upperArm_L','y',.60);rotate('bip_upperArm_R','y',-.60);
 if(t>=nextBlink){blinkStart=t;nextBlink=t+3.1+Math.random()*3.8;}
 const bt=t-blinkStart;
 const blink=bt<.075?bt/.075:bt<.20?1-(bt-.075)/.125:0;
 shape('Eyes-Blink',Math.max(0,Math.min(1,blink)));
 // Occasional eye shifts precede the much slower head response.
 if(t>=nextLook){eyeTarget={x:(Math.random()-.5)*.25,y:(Math.random()-.5)*.12};nextLook=t+2+Math.random()*3;}
 eyeLook.x=THREE.MathUtils.damp(eyeLook.x,eyeTarget.x,13,dt);eyeLook.y=THREE.MathUtils.damp(eyeLook.y,eyeTarget.y,13,dt);
 const recent=t-lastPointer<3;
 let attentionX=recent?pointer.x:0,attentionY=recent?pointer.y:0;
 if(state==='thinking'){attentionX=-.45;attentionY=-.2;}
 gaze.x=THREE.MathUtils.damp(gaze.x,attentionX,1.8,dt);gaze.y=THREE.MathUtils.damp(gaze.y,attentionY,1.8,dt);
 if(state==='idle'&&t>=nextIdle){
  idleGesture={kind:Math.floor(Math.random()*3),start:t,duration:2.5+Math.random()*1.5};
  nextIdle=t+7+Math.random()*7;
 }
 const idleAmount=idleGesture?bell(t,idleGesture.start,idleGesture.duration):0;
 const speakingTime=speech?Math.max(0,speech.clock()):0;
 const phraseGesture=speech?bell(speakingTime,0,1.2)+.65*bell(speakingTime,2.7,1.1)+.5*bell(speakingTime,5.4,1.0):0;
 const ack=bell(t,ackAt,.85);
 const targets={
  smile:speech?(performanceStyle==='playful'?.12:.065):state==='listening'?.10:.075+(idleGesture?.kind===0?idleAmount*.12:0),
  brow:state==='listening'?.15:state==='thinking'?.11:.035+phraseGesture*.12,
  squint:performanceStyle==='playful'&&speech?.08:idleGesture?.kind===0?idleAmount*.06:0,
  smirk:performanceStyle==='playful'&&speech?phraseGesture*.13:0,
  tilt:state==='listening'?.045:state==='thinking'?-.025:(idleGesture?.kind===1?idleAmount*.035:0),
  pitch:ack*.025-phraseGesture*.013,
  yaw:idleGesture?.kind===2?idleAmount*.035:0
 };
 for(const k in expression)expression[k]=THREE.MathUtils.damp(expression[k],targets[k],k==='smile'?2.5:3.2,dt);
 if(!motion.matches){
  rotate('bip_head','z',(gaze.x*.065+Math.sin(t*.43)*.006+expression.yaw)*strength);
  rotate('bip_head','x',(gaze.y*.025+Math.sin(t*.61)*.005+expression.pitch)*strength);
  rotate('bip_head','y',(Math.sin(t*.31)*.006+expression.tilt)*strength);
  rotate('bip_neck','z',gaze.x*.012*strength);
  rotate('bip_spine_3','x',Math.sin(t*1.1)*.0025*strength);
  rotate('bip_spine_3','y',Math.sin(t*.37)*.003*strength);
  model.position.y=Math.sin(t*.8)*.0012*strength;
 }
 shape('Eyebrows-Up',expression.brow*characterStrength);
 shape('Eyebrows-Worried',state==='thinking'?.035:0);
 shape('Eyes-Squint',expression.squint*characterStrength);
 // Keep emotional mouth controls small while speaking so visemes stay readable.
 shape('Mouth-Smile',expression.smile*characterStrength);
 shape('Mouth-Smirk-L',expression.smirk*characterStrength);
 const p=targetPose();
 for(const k in mouth)mouth[k]=THREE.MathUtils.damp(mouth[k],p[k],k==='close'?35:24,dt);
 rotate('Jaw','x',mouth.jaw*.20);
 shape('Mouth-EE',mouth.wide*.8);shape('Mouth-OO',mouth.round*.75);
 translate('Lips Lower','z',mouth.close*.0025+mouth.fv*.0016);
 translate('Lips Upper','z',-mouth.close*.001);
 translate('Lips Lower','y',mouth.fv*.0012);
 translate('Tongue_2','y',-mouth.tongue*.0015);
 for(const name of ['Eye_L','Eye_R']){
  rotate(name,'z',(gaze.x*.025+eyeLook.x*.035)*strength);
  rotate(name,'x',(gaze.y*.014+eyeLook.y*.025)*strength);
 }
 const arrival=motion.matches?1:THREE.MathUtils.smoothstep(t-arrivedAt,0,1.6);
 mount.style.opacity=String(arrival);
 const energy=state==='listening'?1.14:state==='speaking'?1.05+mouth.jaw*.08:1;
 for(const l of lights)l.node.intensity=THREE.MathUtils.damp(l.node.intensity,l.base*energy,4,dt);
 renderer.render(scene,camera);
}
window.CortanaAvatar={ready:false,setState:changeState,setFull(v){full=v;framing();},
 setCharacter(value){characterStrength=THREE.MathUtils.clamp(Number(value)||1,.5,1.4);},
 startSpeech(cues,clock,duration,style='warm'){performanceStyle=style;speech={cues,index:0,clock,duration};},
 stopSpeech(){speech=null;},
 extendSpeech(duration){if(speech)speech.duration=duration;},   // streamed replies add audio as they go
 inspect(){return {ready:!!model,bones:bones.size,morphMeshes:morphs.length,speaking:!!speech,pose:{...mouth},calls:renderer?.info.render.calls,triangles:renderer?.info.render.triangles};}
};
try{
 renderer=new THREE.WebGLRenderer({alpha:true,antialias:true,powerPreference:'low-power'});
 renderer.setPixelRatio(Math.min(devicePixelRatio,1.75));
 renderer.setClearColor(0,0);renderer.outputColorSpace=THREE.SRGBColorSpace;
 renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;
 renderer.domElement.setAttribute('aria-label','Animated 3D Cortana hologram');
 mount.replaceChildren(renderer.domElement);mount.classList.add('model3d');
 // If the GPU resets the WebGL context, re-upload textures and recompile materials when it comes back.
 renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();console.warn('[Cortana avatar] graphics context lost');},false);
 renderer.domElement.addEventListener('webglcontextrestored',()=>{console.warn('[Cortana avatar] graphics context restored');
  model?.traverse(o=>{if(o.isMesh)for(const mat of [].concat(o.material)){for(const k of ['map','normalMap','emissiveMap'])if(mat[k])mat[k].needsUpdate=true;mat.needsUpdate=true;}});},false);
 scene.add(new THREE.HemisphereLight(0xbdeaff,0x143555,2.0));
 const light=new THREE.DirectionalLight(0xd8f3ff,2.3);light.position.set(-1,2,3);scene.add(light);
 const rim=new THREE.DirectionalLight(0x328eff,2.5);rim.position.set(1,2,-2);scene.add(rim);
 lights.push({node:light,base:2.3},{node:rim,base:2.5});
 framing();resize();new ResizeObserver(resize).observe(mount);
 // Textures are WebP images inside the GLB. If one fails to decode, three.js silently renders the mesh
 // untextured (flat face, solid blocky hair). Check every textured material and reload once if any are missing.
 const missingTextures=g=>{const want=new Set();for(const m of g.parser.json.materials||[])if(m.pbrMetallicRoughness?.baseColorTexture)want.add(m.name);
  const bad=new Set(want);g.scene.traverse(o=>{if(o.isMesh)for(const mat of [].concat(o.material))if(mat.map?.image?.width)bad.delete(mat.name);});return [...bad];};
 async function loadModel(){
  for(let attempt=1;;attempt++){
   const g=await new GLTFLoader().loadAsync('./assets/cortana.glb'+(attempt>1?'?retry='+attempt:''));
   const missing=missingTextures(g);
   if(!missing.length)return g;
   console.warn('[Cortana avatar] textures missing on load '+attempt+':',missing.join(', '));
   if(attempt>=3){console.error('[Cortana avatar] showing model with missing textures after 3 attempts');return g;}
  }
 }
 const [gltf,rigData]=await Promise.all([loadModel(),fetch('./assets/rig.json').then(r=>{if(!r.ok)throw Error('Rig unavailable');return r.json();})]);
 rig=rigData;model=gltf.scene;
 model.traverse(o=>{
  if(o.isBone)bones.set(o.name,{node:o,rotation:o.quaternion.clone(),position:o.position.clone()});
  if(!o.isMesh)return;
  o.frustumCulled=false;
  if(o.morphTargetDictionary)morphs.push(o);
  for(const mat of (Array.isArray(o.material)?o.material:[o.material])){
   mat.color.multiply(new THREE.Color(.36,.72,1));
   mat.emissive.set(0x167cda);mat.emissiveIntensity=.10;
   if(/hair/i.test(mat.name)){mat.transparent=false;mat.alphaTest=.45;mat.side=THREE.DoubleSide;mat.color.setRGB(.15,.35,.62);}
   if(/^Eye/.test(mat.name)){mat.color.setRGB(.35,.8,1);mat.emissive.setRGB(.1,.35,.55);mat.emissiveIntensity=.25;mat.roughness=.3;}
   mat.needsUpdate=true;
  }
 });
 scene.add(model);note.textContent='';note.hidden=true;
 window.CortanaAvatar.ready=true;
 document.dispatchEvent(new CustomEvent('cortana:avatar-ready'));
 arrivedAt=performance.now()/1000;nextIdle=arrivedAt+4;stateSince=arrivedAt;
 mount.classList.add('materialising');
 setTimeout(()=>mount.classList.remove('materialising'),1800);
 requestAnimationFrame(frame);
}catch(e){console.error(e);note.textContent='3D character not loaded. Put cortana.glb in app/assets (see app/assets/README.md), then restart.';}

// Register before the asynchronous model load completes.
document.addEventListener('pointermove',e=>{const b=mount.getBoundingClientRect();if(e.clientX<b.left-100||e.clientX>b.right+100||e.clientY<b.top-100||e.clientY>b.bottom+100)return;lastPointer=performance.now()/1000;pointer.x=THREE.MathUtils.clamp((e.clientX-b.left)/b.width-.5,-.65,.65);pointer.y=THREE.MathUtils.clamp((e.clientY-b.top)/b.height-.5,-.6,.6);},{passive:true});
document.addEventListener('pointerleave',()=>{pointer.x=pointer.y=0;lastPointer=0;});
addEventListener('pagehide',e=>{if(e.persisted)return;disposed=true;renderer?.dispose();});
// Coming back via Back/Forward restores the page from memory: make sure the animation loop is running.
addEventListener('pageshow',e=>{if(!e.persisted)return;if(disposed){location.reload();return;}last=performance.now();resize();});
