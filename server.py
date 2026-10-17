"""Local, loopback-only Sonos control. Audio is served separately by media.py."""
import os,json,time,secrets,threading,socket,subprocess,concurrent.futures,urllib.parse,logging,signal,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from xml.sax.saxutils import escape
from sonos import soap,discover,topology,seconds,timestamp
from media import STORE
import library
from video import NativeVideo
STORE.mkdir(parents=True,exist_ok=True)
CONFIG=STORE/'settings.json';RUNTIME=STORE/'runtime.json'
DEFAULTS={'roots':[str(Path.home()/x) for x in ['Music']], 'selected':[], 'bookmarks':{}, 'known':[], 'leader':None}
config={**DEFAULTS,**(json.loads(CONFIG.read_text()) if CONFIG.exists() else {})}
lock=threading.RLock();commands=threading.Lock();preparations=threading.Lock();state={'connected':False,'rooms':[],'error':'Looking for speakers…'}
rows=[];busy='';devices=[];token=secrets.token_urlsafe(32);last_discovery=float("-inf");discovery_lock=threading.RLock()
preparation={'active':False}

def video_snapshot():
    d=leader();sampled=time.time()
    pos=soap(d['ip'],'AVTransport','GetPositionInfo',InstanceID=0)
    sampled=(sampled+time.time())/2
    transport=soap(d['ip'],'AVTransport','GetTransportInfo',InstanceID=0)
    route=urllib.parse.urlparse(pos.get('TrackURI','')).path
    identity=config.get('current',{}).get('id') if route==config.get('route') else None
    return {'id':identity,'position':seconds(pos.get('RelTime')),'playing':transport.get('CurrentTransportState')=='PLAYING','sampled':sampled}

video=NativeVideo()

def start_playback(identity,with_video=False):
    global preparation
    row=next((r for r in rows if r['id']==identity),None)
    if not row:raise ValueError('This file is no longer in your library. Refresh music.')
    if with_video and not row.get('videoPath'):raise ValueError('This music has no video file.')
    target=dict(leader())
    if not preparations.acquire(blocking=False):raise ValueError('Audio is already being prepared. Please wait for the progress below.')
    preparation={'active':True,'id':identity,'title':row['title'],'progress':0,'error':None}
    def work():
        global preparation
        try:
            play_file(identity,target)
            if with_video:video.open(row)
            preparation={**preparation,'active':False,'progress':100}
        except Exception as e:preparation={**preparation,'active':False,'error':str(e)}
        finally:preparations.release()
    threading.Thread(target=work,daemon=True).start()
    return {'message':'Preparing '+row['title']+'. Progress appears below.','preparing':True}

def save():
    with lock:
        tmp=CONFIG.with_suffix('.tmp');tmp.write_text(json.dumps(config,indent=2));tmp.replace(CONFIG)

def remember_rooms():
    profiles=config.setdefault('places',{})
    ids=[d['id'] for d in devices] or config['selected']
    if ids:
        key=config.get('place') or sorted(ids)[0]
        profiles[key]={'rooms':ids,'selected':list(config['selected']),'leader':config['leader']}

def use_household(found):
    # Remember the choice for each place. Reconnecting never changes playback or grouping.
    remember_rooms()
    ids={d['id'] for d in found}
    profiles=config.setdefault('places',{})
    match=max(profiles, key=lambda k:len(ids & set(profiles[k]['rooms'])),default=None)
    profile=profiles.get(match,{})
    if not ids & set(profile.get('rooms',[])):profile={};match=None
    selected=[i for i in profile.get('selected',[]) if i in ids]
    if not selected:
        first=found[0]
        selected=[d['id'] for d in found if d['coordinator']==first['coordinator']]
    config['selected']=selected
    config['leader']=profile.get('leader') if profile.get('leader') in selected else next(d['coordinator'] for d in found if d['id'] in selected)
    config['place']=match or sorted(ids)[0]

def refresh_devices(force=False):
    global devices,last_discovery
    with discovery_lock:
        candidates=list(config['known'])
        def probe(ips):
            # Stale addresses must not hold up discovery on a different network.
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                futures=[pool.submit(topology,ip) for ip in dict.fromkeys(ips)]
                for f in concurrent.futures.as_completed(futures):
                    try:
                        result=f.result()
                        if result:return result
                    except Exception:pass
            return []
        if force or not candidates:
            last_discovery=time.monotonic()
            found=probe(discover()) or probe(candidates)
        else:
            found=probe(candidates)
            if not found and time.monotonic()-last_discovery>8:
                last_discovery=time.monotonic();found=probe(discover())
        if not found:
            devices=[]
            raise RuntimeError('No speakers found. Join the same Wi-Fi as your Sonos, then try again.')
        use_household(found)
        devices=found;config['known']=[d['ip'] for d in found]
        remember_rooms();save()

def leader():
    selected=[d for d in devices if d['id'] in config['selected']]
    d=next((d for d in selected if d['id']==config['leader']),selected[0] if selected else None)
    if not d:raise ValueError('Choose at least one available speaker.')
    return next((r for r in devices if r['id']==d['coordinator']),d)

def read_room(d):
    result=dict(d)
    try:
        ip=d['ip'];result['volume']=int(soap(ip,'RenderingControl','GetVolume',InstanceID=0,Channel='Master')['CurrentVolume'])
        result['bass']=int(soap(ip,'RenderingControl','GetBass',InstanceID=0)['CurrentBass'])
        result['treble']=int(soap(ip,'RenderingControl','GetTreble',InstanceID=0)['CurrentTreble'])
        result['loudness']=soap(ip,'RenderingControl','GetLoudness',InstanceID=0,Channel='Master')['CurrentLoudness']=='1'
        result['online']=True;result['calibrated']=False;result['trueplay']=False
        try:
            cal=soap(ip,'RenderingControl','GetRoomCalibrationStatus',InstanceID=0)
            result['calibrated']=cal.get('RoomCalibrationAvailable')=='1';result['trueplay']=cal.get('RoomCalibrationEnabled')=='1'
        except Exception:pass
    except Exception:result['online']=False
    return result

def poll():
    global state,busy,last_discovery
    while True:
        try:
            if not devices:refresh_devices(force=True)
            else:refresh_devices()
            d=leader();ip=d['ip']
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                fs=[pool.submit(soap,ip,'AVTransport','GetTransportInfo',InstanceID=0),pool.submit(soap,ip,'AVTransport','GetPositionInfo',InstanceID=0),pool.submit(soap,ip,'GroupRenderingControl','GetGroupVolume',InstanceID=0),pool.submit(soap,ip,'GroupRenderingControl','GetGroupMute',InstanceID=0)]
                room_states=list(pool.map(read_room,devices))
                transport,pos,vol,mute=[f.result() for f in fs]
            route=urllib.parse.urlparse(pos.get('TrackURI','')).path
            current=config.get('current',{}) if route==config.get('route') else {}
            title=current.get('title')
            if not title:
                try:
                    from xml.etree import ElementTree as E
                    title=next(x.text for x in E.fromstring(pos['TrackMetaData']).iter() if x.tag.endswith('}title'))
                except Exception:title='Choose something to play'
            selected=[r for r in room_states if r['id'] in config['selected']]
            group_members=[r for r in room_states if r['coordinator']==d['id']]
            state={'connected':True,'error':None,'rooms':room_states,'selected':config['selected'],'grouped':bool(selected) and len(selected)==len(config['selected']) and all(r['coordinator']==d['id'] for r in selected),'groupCount':len(group_members),'groupNames':[r['name'] for r in group_members],'leader':d['id'],'title':title,'currentId':current.get('id'),'hasVideo':any(r['id']==current.get('id') and r.get('videoPath') for r in rows),'position':seconds(pos.get('RelTime')),'duration':seconds(pos.get('TrackDuration')),'playing':transport.get('CurrentTransportState')=='PLAYING','volume':int(vol['CurrentVolume']),'muted':mute.get('CurrentMute')=='1','bookmarks':config['bookmarks'].get(current.get('id'),[]),'updated':time.time()}
        except Exception as e:
            state={**state,'connected':False,'rooms':[],'selected':[],'error':str(e),'updated':time.time()}
            if time.monotonic()-last_discovery>15:
                try:refresh_devices(force=True)
                except Exception:pass
        time.sleep(2)

def group(ids):
    if not ids or not set(ids)<={d['id'] for d in devices}:raise ValueError('Choose available speakers.')
    selected=[d for d in devices if d['id'] in ids]
    old=leader()
    coord=old if old['id'] in ids else selected[0]
    if coord['coordinator']!=coord['id']:
        soap(coord['ip'],'AVTransport','BecomeCoordinatorOfStandaloneGroup',InstanceID=0)
    for d in selected:
        if d['id']!=coord['id'] and d['coordinator']!=coord['id']:
            soap(d['ip'],'AVTransport','SetAVTransportURI',InstanceID=0,CurrentURI='x-rincon:'+coord['id'],CurrentURIMetaData='')
    # Uncheck a room to remove it from this group, while leaving other groups alone.
    for d in devices:
        if d['id'] not in ids and d['coordinator']==coord['id']:
            soap(d['ip'],'AVTransport','BecomeCoordinatorOfStandaloneGroup',InstanceID=0)
    config['selected']=ids;config['leader']=coord['id'];remember_rooms();save();refresh_devices()
    actual=[d for d in devices if d['id'] in ids]
    if any(d['coordinator']!=coord['id'] for d in actual):raise RuntimeError('Grouping is still changing. Check speakers and retry.')
    return {'message':f'{len(ids)} speakers grouped.'}

def play_file(identity,target=None):
    global busy
    row=next((r for r in rows if r['id']==identity),None)
    if not row:raise ValueError('This file is no longer in your library. Refresh music.')
    busy='Preparing audio…'
    try:
        def progress(value):
            global preparation
            preparation={**preparation,'progress':value}
        route=library.prepare(row,progress);d=leader()
        if target and (d['id'],d['ip'])!=(target['id'],target['ip']):raise ValueError('Your speakers changed during preparation. Choose the music again.')
        s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        s.connect((d['ip'],1400));local=s.getsockname()[0];s.close()
        uri=f'http://{local}:8775{route}'
        metadata='<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"><item id="0" parentID="0" restricted="true"><dc:title>'+escape(row['title'])+'</dc:title><upnp:class>object.item.audioItem.musicTrack</upnp:class><res protocolInfo="http-get:*:audio/mp4:*">'+escape(uri)+'</res></item></DIDL-Lite>'
        soap(d['ip'],'AVTransport','SetAVTransportURI',InstanceID=0,CurrentURI=uri,CurrentURIMetaData=metadata)
        soap(d['ip'],'AVTransport','Play',InstanceID=0,Speed=1)
        config['current']=library.public(row);config['route']=route;save()
        for attempt in range(12):
            info=soap(d['ip'],'AVTransport','GetTransportInfo',InstanceID=0)
            pos=soap(d['ip'],'AVTransport','GetPositionInfo',InstanceID=0)
            if info.get('CurrentTransportState')=='PLAYING' and seconds(pos.get('RelTime'))>0:break
            time.sleep(.5)
        else:raise RuntimeError('Audio is ready, but Sonos did not start. Check the speakers, then try Play again.')
        return {'message':'Playing '+row['title']}
    finally:busy=''

def action(a):
    global rows,busy
    name=a['action']
    if name=='scan':
        busy='Finding your music…'
        try:rows=library.scan(config['roots']);return {'count':len(rows)}
        finally:busy=''
    if name=='folder':
        p=Path(a['path']).expanduser().resolve()
        if not p.is_dir():raise ValueError('Choose a folder that exists.')
        if str(p) not in config['roots']:config['roots'].append(str(p));save()
        rows=library.scan(config['roots']);return {'count':len(rows)}
    if name=='reconnect':
        refresh_devices(force=True)
        return {'message':'Connected to '+leader()['name']+'.'}
    if name=='group':
        with discovery_lock:return group(a['ids'])
    if name=='playFile':return start_playback(a['id'],bool(a.get('video')))
    if name=='openVideo':
        identity=video_snapshot()['id']
        row=next((r for r in rows if r['id']==identity),None)
        if not row:raise ValueError('Play a local video on Sonos first.')
        return video.open(row)
    if name=='nativeVideoStatus':
        video.status={k:v for k,v in a.items() if k in ('active','visible','ready','id','message','muted','volume','position','rate','loads','sampled','enabledAudioTracks','showMilliseconds','frameMilliseconds')}
        return {'ok':True}
    if name=='videoOffset':
        config['videoOffset']=max(-5,min(5,float(a['value'])));save()
        return {'ok':True}
    d=leader();ip=d['ip']
    if name in ('play','pause','stop','next','previous'):
        # Local files form a predictable library playlist; Sonos services keep their own queue.
        if name in ('next','previous') and state.get('currentId'):
            index=next((i for i,r in enumerate(rows) if r['id']==state['currentId']),-1)
            if index<0:raise ValueError('Refresh your music library first.')
            return start_playback(rows[(index+(1 if name=='next' else -1))%len(rows)]['id'])
        args={'InstanceID':0}
        if name=='play':args['Speed']=1
        soap(ip,'AVTransport',name.capitalize(),**args)
    elif name=='volume':
        value=max(0,min(100,int(a['value'])))
        if a.get('id'):
            room=next((r for r in devices if r['id']==a['id']),None)
            if not room:raise ValueError('Speaker unavailable.')
            soap(room['ip'],'RenderingControl','SetVolume',InstanceID=0,Channel='Master',DesiredVolume=value)
        else:
            soap(ip,'GroupRenderingControl','SnapshotGroupVolume',InstanceID=0)
            soap(ip,'GroupRenderingControl','SetGroupVolume',InstanceID=0,DesiredVolume=value)
    elif name=='mute':soap(ip,'GroupRenderingControl','SetGroupMute',InstanceID=0,DesiredMute=int(bool(a['value'])))
    elif name=='seek':
        pos=soap(ip,'AVTransport','GetPositionInfo',InstanceID=0);duration=seconds(pos.get('TrackDuration'))
        if not duration:raise ValueError('This stream cannot seek. Choose a local music file.')
        target=max(0,min(duration-1,int(a['seconds'])))
        soap(ip,'AVTransport','Seek',InstanceID=0,Unit='REL_TIME',Target=timestamp(target))
    elif name=='bookmark':
        identity=state.get('currentId')
        if not identity:raise ValueError('Play a local file to save a moment.')
        pos=seconds(soap(ip,'AVTransport','GetPositionInfo',InstanceID=0)['RelTime'])
        marks=config['bookmarks'].setdefault(identity,[])
        marks.append({'time':pos,'name':str(a.get('name') or timestamp(pos))[:60]});save()
    elif name=='removeBookmark':
        marks=config['bookmarks'].get(state.get('currentId'),[])
        config['bookmarks'][state.get('currentId')]=[m for m in marks if m['time']!=a['time']];save()
    elif name=='tune':
        target=next((r for r in devices if r['id']==a['id']),None)
        if not target:raise ValueError('Speaker unavailable.')
        field=a['field'];value=a['value'];rip=target['ip']
        if field in ('bass','treble'):soap(rip,'RenderingControl','Set'+field.capitalize(),InstanceID=0,**{'Desired'+field.capitalize():max(-10,min(10,int(value)))})
        elif field=='loudness':soap(rip,'RenderingControl','SetLoudness',InstanceID=0,Channel='Master',DesiredLoudness=int(bool(value)))
        elif field=='trueplay':
            available=soap(rip,'RenderingControl','GetRoomCalibrationStatus',InstanceID=0)['RoomCalibrationAvailable']=='1'
            if not available:raise ValueError('Set up Trueplay in the Sonos phone app first.')
            soap(rip,'RenderingControl','SetRoomCalibrationStatus',InstanceID=0,RoomCalibrationEnabled=int(bool(value)))
        else:raise ValueError('Unknown sound control.')
    elif name=='preset':
        presets={'balanced':(0,0,True),'warm':(2,-1,True),'voice':(-2,2,False)}
        if a['preset'] not in presets:raise ValueError('Unknown preset.')
        bass,treble,loud=presets[a['preset']];failures=[]
        for r in devices:
            if r['id'] not in config['selected']:continue
            try:
                soap(r['ip'],'RenderingControl','SetBass',InstanceID=0,DesiredBass=bass)
                soap(r['ip'],'RenderingControl','SetTreble',InstanceID=0,DesiredTreble=treble)
                soap(r['ip'],'RenderingControl','SetLoudness',InstanceID=0,Channel='Master',DesiredLoudness=int(loud))
            except Exception:failures.append(r['name'])
        if failures:raise RuntimeError('Some speakers did not update: '+', '.join(failures))
    else:raise ValueError('Unknown control.')
    return {'ok':True}

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(message)s')

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send_json(self,data,status=200):
        raw=json.dumps(data).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def allowed(self):
        if self.headers.get('Host') not in ('127.0.0.1:8776','localhost:8776'):return False
        origin=self.headers.get('Origin')
        if origin and origin not in ('http://127.0.0.1:8776','http://localhost:8776'):return False
        return secrets.compare_digest(self.headers.get('X-Roomtone-Token',''),token)
    def do_GET(self):
        path=urllib.parse.urlparse(self.path)
        if path.path in ('/','/app.js','/style.css'):
            p=Path(__file__).parent/'web'/({'/':'index.html'}.get(path.path,path.path[1:]))
            if not p.exists():self.send_error(404);return
            raw=p.read_bytes();self.send_response(200);self.send_header('Content-Type',{'html':'text/html','js':'application/javascript','css':'text/css','jpg':'image/jpeg'}[p.suffix[1:]])
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
        if not self.allowed():self.send_json({'error':'Open Roomtone to connect.'},403);return
        if path.path=='/api/state':self.send_json({**state,'busy':busy,'preparation':preparation,'video':video.status,'videoOffset':config.get('videoOffset',0),'libraryCount':len(rows),'roots':config['roots']})
        elif path.path=='/api/video':
            try:
                snapshot=video_snapshot()
                row=next((r for r in rows if r['id']==snapshot['id'] and r.get('videoPath')),None)
                source=video.source(row,prepare=urllib.parse.parse_qs(path.query).get('prepare')==['1']) if row else {'path':None}
                self.send_json({**snapshot,**source,'id':row['id'] if row else None,'title':row['title'] if row else '', 'offset':config.get('videoOffset',0),'request':video.request,'requestedId':video.requested_id})
            except Exception:self.send_json({'error':'Waiting for Sonos…'},503)
        elif path.path=='/api/library':
            q=urllib.parse.parse_qs(path.query).get('q',[''])[0]
            items=[library.public(r) for r in library.lexical(rows,q)[:100]]
            logging.info('library-search count=%s',len(items))
            self.send_json({'items':items,'engine':'local'})
        else:self.send_error(404)
    def do_POST(self):
        if not self.allowed():self.send_json({'error':'Not authorized.'},403);return
        try:
            n=int(self.headers.get('Content-Length',0))
            if n>16384:raise ValueError('Request too large.')
            a=json.loads(self.rfile.read(n))
            started=time.monotonic()
            operation=str(a.get('action','unknown'))
            if operation!='nativeVideoStatus':logging.info('request-start operation=%s',operation)
            if self.path=='/api/action':
                with commands:result=action(a)
            else:self.send_error(404);return
            self.send_json(result)
            if operation!='nativeVideoStatus':logging.info('request-done operation=%s seconds=%.3f engine=%s',operation,time.monotonic()-started,result.get('engine','local'))
        except (BrokenPipeError,ConnectionResetError):logging.warning('request-disconnected')
        except Exception as e:
            logging.warning('request-error type=%s',type(e).__name__)
            self.send_json({'error':str(e)},400)

if __name__=='__main__':
    def shutdown(signum,frame):
        sys.exit(0)
    signal.signal(signal.SIGTERM,shutdown)
    signal.signal(signal.SIGINT,shutdown)
    rows=library.scan(config['roots'])
    http=ThreadingHTTPServer(('127.0.0.1',8776),Handler)
    runtime_tmp=RUNTIME.with_suffix('.tmp');runtime_tmp.write_text(json.dumps({'token':token,'port':8776}));runtime_tmp.chmod(0o600);runtime_tmp.replace(RUNTIME)
    threading.Thread(target=poll,daemon=True).start()
    http.serve_forever()
