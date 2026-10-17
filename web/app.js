'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let token=location.hash.slice(1)||sessionStorage.getItem('roomtone-token')||'';
sessionStorage.setItem('roomtone-token',token);history.replaceState(null,'',location.pathname);
let state={}, editing=new Set(), selection=null, libraryItems=[], noticeTimer, queryVersion=0, pinned=false, actionCount=0;
const paths={play:'M8 5v14l11-7z',pause:'M7 5h3v14H7z M14 5h3v14h-3z',previous:'M6 5v14 M18 5L8 12l10 7z',next:'M18 5v14 M6 5l10 7-10 7z',volume:'M4 9v6h4l5 4V5L8 9z M17 8c3 2 3 6 0 8',mute:'M4 9v6h4l5 4V5L8 9z M17 9l5 6 M22 9l-5 6'};
function icon(n){return `<svg viewBox="0 0 24 24" fill="${['play','pause'].includes(n)?'currentColor':'none'}" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[n]}"></path></svg>`}
function clock(n){n=Math.max(0,Math.floor(n||0));return n>=3600?`${Math.floor(n/3600)}:${String(Math.floor(n/60)%60).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`:`${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`}
function fill(el){let p=(+el.value-+el.min)/(+el.max-+el.min||1)*100;el.style.setProperty('--fill',p+'%')}
function notice(message,error=false){$('#notice').textContent=message;$('#notice').className='notice visible'+(error?' error':'');clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$('#notice').className='notice',error?7000:3500)}
let recoveryPromise=null, recoveryResolve=null;
window.reconnectControl=newToken=>{
  token=newToken;sessionStorage.setItem('roomtone-token',token);
  if(recoveryResolve)recoveryResolve(true);
  recoveryResolve=null;recoveryPromise=null;
  refresh();
};
function recoverConnection(){
  if(recoveryPromise)return recoveryPromise;
  recoveryPromise=new Promise(resolve=>{
    recoveryResolve=resolve;
    if(window.webkit?.messageHandlers.native)window.webkit.messageHandlers.native.postMessage({action:'reconnect'});
    setTimeout(()=>{if(recoveryResolve===resolve){recoveryResolve=null;recoveryPromise=null;resolve(false)}},10000);
    if(!window.webkit?.messageHandlers.native)setTimeout(()=>resolve(true),500);
  });
  return recoveryPromise;
}
async function api(path,data){
  const retryable=!data;
  for(let attempt=0;attempt<2;attempt++){
    let res;
    try{
      res=await fetch(path,{method:data?'POST':'GET',headers:{'X-Roomtone-Token':token,...(data?{'Content-Type':'application/json'}:{})},...(data?{body:JSON.stringify(data)}:{})});
    }catch(e){
      const recovered=await recoverConnection();
      if(retryable&&attempt===0&&recovered)continue;
      throw new Error(retryable?'Cannot connect yet. Try Find speakers again.':'The connection was interrupted. Check playback before trying that control again.');
    }
    if(res.status===403&&attempt===0&&await recoverConnection())continue;
    const result=await res.json();if(!res.ok)throw new Error(result.error||'Could not connect.');return result;
  }
  throw new Error('Connection is recovering. Please try again.');
}
async function command(action,extra={}){actionCount++;try{const r=await api('/api/action',{action,...extra});if(r.message)notice(r.message);return r}catch(e){notice(e.message,true);throw e}finally{actionCount--;setTimeout(refresh,350)}}
function run(action,extra){return command(action,extra).catch(()=>{})}
function setupSlider(el,callback,display){el.addEventListener('pointerdown',()=>editing.add(el));el.addEventListener('input',()=>{editing.add(el);fill(el);if(display)display(el.value)});el.addEventListener('change',async()=>{try{await callback(+el.value)}catch{}finally{editing.delete(el)}});el.addEventListener('pointercancel',()=>editing.delete(el));el.addEventListener('blur',()=>editing.delete(el));fill(el)}
function setSlider(el,value,max){if(editing.has(el))return;if(max!==undefined)el.max=Math.max(1,max);el.value=value;fill(el)}
function tab(name){$$('nav button').forEach(b=>b.classList.toggle('active',b.dataset.tab===name));$$('.tab').forEach(s=>s.classList.toggle('active',s.id===name));if(name==='music')loadLibrary();if(name==='speakers')renderRooms(true);$('main').scrollTop=0}
$$('nav button').forEach(b=>b.onclick=()=>tab(b.dataset.tab));
$('#previous').innerHTML=icon('previous');$('#next').innerHTML=icon('next');$('#play').innerHTML=icon('play');$('#mute').innerHTML=icon('volume');
setupSlider($('#volume'),value=>command('volume',{value}),v=>$('#volumeValue').innerHTML=v+'<small>%</small>');
setupSlider($('#seek'),seconds=>command('seek',{seconds}),v=>$('#elapsed').textContent=clock(+v));
$('#mute').onclick=()=>run('mute',{value:!state.muted});$('#volumePlus').onclick=()=>run('volume',{value:Math.min(100,(state.volume||0)+2)});
$('#play').onclick=()=>run(state.playing?'pause':'play');$('#previous').onclick=()=>run('previous');$('#next').onclick=()=>run('next');$('#back').onclick=()=>run('seek',{seconds:Math.max(0,(state.position||0)-15)});$('#forward').onclick=()=>run('seek',{seconds:(state.position||0)+15});
$('#jumpGo').onclick=()=>{const value=$('#jump').value.trim();if(!/^\d+(:[0-5]\d){1,2}$/.test(value)){notice('Enter a time like 24:30 or 1:04:30.',true);return}const parts=value.split(':').map(Number);run('seek',{seconds:parts.reduce((a,b)=>a*60+b,0)})};$('#jump').onkeydown=e=>{if(e.key==='Enter')$('#jumpGo').click()};
$('#bookmark').onclick=()=>run('bookmark');
let finding=false, findingError='';
async function reconnect(){
  if(finding)return;finding=true;findingError='';render();
  try{await command('reconnect');selection=null;await refresh()}
  catch(e){findingError=e.message}
  finally{finding=false;render()}
}
$('#connection').onclick=$('#reconnect').onclick=$('#findSpeakers').onclick=reconnect;
$('#chooseRooms').onclick=$('#soundRooms').onclick=()=>tab('speakers');
$('#closeRooms').onclick=()=>{selection=null;tab('playing')};
$('#browseMusic').onclick=()=>{tab('music');$('#query').focus()};
$('#group').onclick=async()=>{const ids=selection||state.selected||[];try{await command('group',{ids});selection=null;tab('playing');setTimeout(refresh,1000)}catch{}};
$$('[data-preset]').forEach(b=>b.onclick=async()=>{try{await command('preset',{preset:b.dataset.preset});notice(b.textContent+' sound applied.')}catch{}});
$('#trueplayHelp').onclick=()=>{const url='https://support.sonos.com/article/tune-your-sonos-speakers-with-trueplay';if(window.webkit?.messageHandlers.native)window.webkit.messageHandlers.native.postMessage({action:'openURL',url});else window.open(url,'_blank','noopener')};
$('#pin').onclick=()=>{pinned=!pinned;$('#pin').classList.toggle('selected',pinned);$('#pin').textContent=pinned?'On top ✓':'Keep on top';window.webkit?.messageHandlers.native.postMessage({action:'pin',value:pinned})};
$('#addFolder').onclick=()=>{if(window.webkit?.messageHandlers.native)window.webkit.messageHandlers.native.postMessage({action:'folder'});else notice('Open the Mac app to choose a folder.')};
window.addMusicFolder=path=>command('folder',{path}).then(()=>loadLibrary()).catch(()=>{});
$('#rescan').onclick=async()=>{try{notice('Finding music…');const r=await command('scan');notice(`${r.count} music files found.`);loadLibrary()}catch{}};
let queryTimer;
$('#query').oninput=()=>{++queryVersion;clearTimeout(queryTimer);queryTimer=setTimeout(loadLibrary,160)};
$('#searchForm').onsubmit=e=>{e.preventDefault();clearTimeout(queryTimer);loadLibrary()};
async function loadLibrary(){const version=++queryVersion;try{const r=await api('/api/library?q='+encodeURIComponent($('#query').value));if(version!==queryVersion)return;libraryItems=r.items;renderLibrary();$('#searchInfo').textContent=`${r.items.length} matches · on this Mac`}catch(e){if(version===queryVersion)notice(e.message,true)}}
async function playItem(item,withVideo=false){
  if(state.preparation?.active)return;
  if(withVideo&&item.id===state.currentId){showVideo();tab('playing');return}
  try{const result=await command('playFile',{id:item.id,video:withVideo});if(result.preparing)state.preparation={active:true,id:item.id,title:item.title,progress:0};tab('playing');render()}catch{}
}
function renderLibrary(){
  const list=$('#library');list.replaceChildren();
  if(!libraryItems.length){const p=document.createElement('p');p.className='empty';p.textContent='No matches yet. Try another name or add a music folder.';list.append(p)}
  for(const item of libraryItems){
    const row=document.createElement('div');row.className='song-row';
    const b=document.createElement('button');b.className='song'+(item.id===state.currentId?' current':'');
    b.innerHTML='<span class="record"></span><span><span class="song-name"></span><span class="song-meta"></span></span><span class="arrow">▶</span>';
    b.querySelector('.song-name').textContent=item.title;b.querySelector('.song-meta').textContent=item.folder+' · '+item.format;
    b.setAttribute('aria-label','Play '+item.title);b.disabled=!!state.preparation?.active;b.onclick=()=>playItem(item);row.append(b);
    if(item.hasVideo){const v=document.createElement('button');v.className='video-choice';v.textContent='Play with video';v.setAttribute('aria-label','Play '+item.title+' with synced silent video');v.disabled=!!state.preparation?.active;v.onclick=()=>playItem(item,true);row.append(v)}
    list.append(row);
  }
}
let nativeVideo=null;
function nativeVideoAction(action){
  if(window.webkit?.messageHandlers.native)window.webkit.messageHandlers.native.postMessage({action});
  else notice('Open Roomtone on your Mac to show video.');
}
function showVideo(){nativeVideoAction('showVideo')}
function renderVideo(){
  const v=nativeVideo||state.video||{};
  $('#openVideo').textContent=v.active?'Hide video · ⇧⌘V':'Show video · ⇧⌘V';
  $('#openVideo').setAttribute('aria-pressed',String(!!v.active));
  $('#videoControls').hidden=!v.active;
  $('#videoStatus').textContent=v.message||'Sound stays on Sonos.';
}
window.setVideoLayout=visible=>{document.body.classList.toggle('video-mode',visible)};
$('#hideVideo').onclick=()=>nativeVideoAction('hideVideo');
window.nativeVideoChanged=value=>{nativeVideo=value;renderVideo()};
$('#openVideo').onclick=()=>nativeVideoAction('toggleVideo');
$('#videoOffset').onchange=()=>{const value=Number($('#videoOffset').value);if(Number.isFinite(value))run('videoOffset',{value})};
let roomSignature='';
function renderRooms(force=false){
  if(!$('#speakers').classList.contains('active'))return;
  const rooms=state.connected?(state.rooms||[]):[];
  const signature=JSON.stringify([rooms,selection,state.selected]);
  if(!force&&signature===roomSignature)return;
  if([...editing].some(e=>$('#rooms').contains(e)))return;
  // Keep focused sound controls stable during background updates.
  if(!force&&$$('#rooms details').some(d=>d.contains(document.activeElement)))return;
  roomSignature=signature;
  const open=new Set($$('#rooms details[open]').map(d=>d.dataset.id));
  const box=$('#rooms');box.replaceChildren();
  if(!rooms.length){const p=document.createElement('p');p.className='empty';p.textContent='Your rooms will appear here when Sonos is nearby.';box.append(p)}
  for(const r of rooms){
    const row=document.createElement('div');row.className='room';
    const chosen=(selection||state.selected||[]).includes(r.id);
    const name=r.name+(rooms.filter(d=>d.name===r.name).length>1?' · '+(rooms.indexOf(r)+1):'');
    row.innerHTML='<button class="room-choice"><span class="speaker-mark" aria-hidden="true">▥</span><span class="room-label"><strong></strong><small></small></span><span class="room-check" aria-hidden="true"></span></button><details><summary>Volume & sound</summary><div class="room-volume"><input type="range" min="0" max="100"><output></output></div></details>';
    const choice=row.querySelector('.room-choice');choice.classList.toggle('selected',chosen);choice.setAttribute('aria-pressed',String(chosen));choice.setAttribute('aria-label',name);choice.disabled=!r.online;
    row.querySelector('strong').textContent=name;
    row.querySelector('small').textContent=!r.online?'Unavailable':r.coordinator===state.leader?'Connected':'Available';
    row.querySelector('.room-check').textContent=chosen?'✓':'+';
    choice.onclick=()=>{selection=selection||[...(state.selected||[])];selection=chosen?selection.filter(x=>x!==r.id):[...new Set([...selection,r.id])];renderRooms(true)};
    const output=row.querySelector('output');output.textContent=(r.volume??'—')+'%';
    const slider=row.querySelector('input[type=range]');slider.setAttribute('aria-label',name+' volume');slider.value=r.volume||0;slider.disabled=!r.online;
    setupSlider(slider,value=>command('volume',{id:r.id,value}),v=>output.textContent=v+'%');
    const details=row.querySelector('details');details.dataset.id=r.id;details.open=open.has(r.id);
    for(const field of ['bass','treble']){
      const div=document.createElement('div');div.className='eq';div.innerHTML='<label></label><input type="range" min="-10" max="10"><output></output>';
      div.querySelector('label').textContent=field[0].toUpperCase()+field.slice(1);
      const input=div.querySelector('input');input.setAttribute('aria-label',name+' '+field);input.value=r[field]||0;input.disabled=!r.online;div.querySelector('output').textContent=r[field]||0;
      setupSlider(input,value=>command('tune',{id:r.id,field,value}),v=>div.querySelector('output').textContent=v);details.append(div);
    }
    for(const [field,title] of [['loudness','Fuller sound at low volume'],['trueplay','Use saved room tuning']]){
      const label=document.createElement('label');label.className='check';label.textContent=title;
      const input=document.createElement('input');input.type='checkbox';input.checked=!!r[field];input.disabled=!r.online||(field==='trueplay'&&!r.calibrated);input.onchange=()=>run('tune',{id:r.id,field,value:input.checked});label.append(input);details.append(label);
    }
    box.append(row);
  }
  const chosen=selection||state.selected||[];
  $('#group').disabled=!state.connected||!chosen.length;
  $('#group').textContent=chosen.length>1?'Listen in '+chosen.length+' rooms':'Use this room';
  const calibrated=rooms.filter(r=>chosen.includes(r.id)&&r.calibrated).length;
  $('#trueplayInfo').textContent=calibrated?'Saved room tuning is available. Open the room’s sound controls to use it.':'Measure your room in the Sonos phone app. You can use saved tuning here afterwards.';
}
function render(){
const connected=state.connected;
const prep=state.preparation||{};
$('#preparation').hidden=!prep.active&&!prep.error;
$('#preparationTitle').textContent=prep.error?'Playback needs attention':'Preparing '+(prep.title||'audio');
$('#preparationProgress').hidden=!prep.active;$('#preparationProgress').value=prep.progress||0;
$('#preparationCopy').textContent=prep.error||(prep.progress>=100?'Starting your speakers…':`${prep.progress||0}% · The first play can take a few minutes. Next time will be faster.`);
$$('.song-row button').forEach(b=>b.disabled=!!prep.active||!connected);
$('#openVideo').hidden=!state.hasVideo;$('#openVideo').disabled=!connected||!!prep.active;
renderVideo();
if(document.activeElement!==$('#videoOffset'))$('#videoOffset').value=state.videoOffset||0;

$('#connection').classList.toggle('online',connected);
$('#connection span').textContent=finding?'Finding…':connected?'Connected':'Reconnect';
$('#connection').disabled=finding;
$('#connectionHelp').hidden=!!connected&&!finding;
$('#connectionTitle').textContent=finding?'Finding nearby Sonos…':'Let’s connect';
$('#connectionCopy').textContent=finding?'Checking the speakers on this Wi-Fi.':findingError||'Join the same Wi-Fi as your Sonos. We’ll connect automatically.';
for(const id of ['reconnect','findSpeakers']){$('#'+id).disabled=finding;$('#'+id).textContent=finding?'Finding speakers…':id==='reconnect'?'Find speakers again':'Find speakers'}
const names=[...new Set(state.groupNames||[])];
$('#roomName').textContent=connected?(names.length===1?names[0]:names.length+' rooms'):'Choose your rooms';
$('#groupLabel').textContent=connected?(names.length>1?names.join(' + '):'Connected · change rooms'):'Connect on this Wi-Fi';
if(selection&&selection.length&&!selection.some(id=>(state.rooms||[]).some(r=>r.id===id)))selection=null;
if(!editing.has($('#volume')))$('#volumeValue').innerHTML=(connected?state.volume:'—')+'<small>%</small>';setSlider($('#volume'),state.volume||0);$('#volume').disabled=!connected;$('#mute').innerHTML=icon(state.muted?'mute':'volume');$('#mute').setAttribute('aria-label',state.muted?'Unmute group':'Mute group');$('#play').innerHTML=icon(state.playing?'pause':'play');$('#play').setAttribute('aria-label',state.playing?'Pause':'Play');$('#playState').textContent=!connected?'READY WHEN YOU ARE':state.playing?'NOW PLAYING':'ON YOUR SONOS';$('#title').textContent=(connected?state.title||'A little music?':'A little music?');setSlider($('#seek'),state.position||0,state.duration||1);$('#seek').disabled=!connected||!state.duration;if(!editing.has($('#seek')))$('#elapsed').textContent=clock(state.position);$('#duration').textContent=clock(state.duration);for(const id of ['play','previous','next','back','forward','jumpGo','mute','volumePlus'])$('#'+id).disabled=!connected;for(const id of ['previous','next'])$('#'+id).disabled=!connected||!!prep.active;$('#bookmark').disabled=!connected||!state.currentId;$('#statusLine').textContent=state.busy||(connected?'Ready · '+state.libraryCount+' music files':'Looking for your Sonos');$$('[data-preset]').forEach(b=>b.disabled=!connected);$('#group').disabled=!connected||!(selection||state.selected||[]).length;const marks=$('#bookmarks');const signature=JSON.stringify(state.bookmarks||[]);if(marks.dataset.signature!==signature){marks.dataset.signature=signature;marks.replaceChildren();for(const m of state.bookmarks||[]){const b=document.createElement('button');b.textContent=m.name;b.title='Play from '+clock(m.time)+' · Option-click to remove';b.onclick=e=>e.altKey?run('removeBookmark',{time:m.time}):run('seek',{seconds:m.time});marks.append(b)}}renderRooms()}
let refreshing=false;async function refresh(){if(refreshing)return;refreshing=true;try{state=await api('/api/state');if(state.updated&&Date.now()/1000-state.updated>15){state.connected=false;state.error='Checking your speakers…'}render()}catch(e){state.connected=false;state.error='Connecting to your controls…';render()}finally{refreshing=false}}
document.addEventListener('keydown',e=>{if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.metaKey||e.ctrlKey||e.altKey||!state.connected)return;const actions={'v':()=>$('#openVideo').click(),' ':()=>$('#play').click(),ArrowLeft:()=>$('#back').click(),ArrowRight:()=>$('#forward').click(),ArrowUp:()=>run('volume',{value:Math.min(100,state.volume+2)}),ArrowDown:()=>run('volume',{value:Math.max(0,state.volume-2)})};if(actions[e.key]){e.preventDefault();actions[e.key]()}});
setInterval(refresh,1800);refresh();
