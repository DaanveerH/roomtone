import os,json,hashlib,subprocess,difflib,re,time,tempfile,unicodedata,shutil
from pathlib import Path
from media import STORE,REGISTRY
EXTENSIONS={'.mp3','.m4a','.aac','.flac','.wav','.aiff','.aif','.ogg','.mp4','.mov','.mkv','.webm'}
def media_tool(name):
    path=shutil.which(name, path=os.environ.get('PATH','')+':/opt/homebrew/bin:/usr/local/bin')
    if not path:raise RuntimeError('Install FFmpeg with: brew install ffmpeg')
    return path

FFMPEG=media_tool('ffmpeg')
FFPROBE=media_tool('ffprobe')
VIDEO_EXTENSIONS={'.mp4','.mov','.mkv','.webm'}

def scan(roots):
    files={};videos={}
    for root in roots:
        for base,dirs,names in os.walk(Path(root).expanduser()):
            dirs[:]=[d for d in dirs if not d.startswith('.') and d not in ('node_modules','Library','site-scrape')]
            for name in names:
                p=Path(base)/name
                if p.suffix.lower() not in EXTENSIONS or name.lower().startswith(('screen recording', 'screenrecording', 'zoom_')):continue
                title=p.stem
                identity=hashlib.sha256(str(p).encode()).hexdigest()[:20]
                key=title.lower()
                if p.suffix.lower() in VIDEO_EXTENSIONS:videos[(str(p.parent),key)]=str(p)
                row={'id':identity,'title':title,'path':str(p),'folder':p.parent.name,'format':p.suffix[1:].upper()}
                if key not in files or p.suffix.lower() in ('.m4a','.mp3'):files[key]=row
    for key,row in files.items():row['videoPath']=videos.get((str(Path(row['path']).parent),key))
    return sorted(files.values(),key=lambda r:r['title'].lower())

def public(row):return {**{k:v for k,v in row.items() if k not in ('path','videoPath')},'hasVideo':bool(row.get('videoPath'))}

def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKD',text.casefold()) if not unicodedata.combining(c))

def lexical(rows,q):
    if not q.strip():return rows
    stop={'the','at','in','on','by','of','a','an','and','please'}
    terms=[t for t in re.findall(r'\w+',normalized(q)) if t not in stop]
    if not terms:return []
    def score(row):
        name=normalized(row['title']+' '+row['folder'])
        words=re.findall(r'\w+',name)
        scores=[]
        for term in terms:
            if term in words:scores.append(1.2)
            elif any(w.startswith(term) for w in words):scores.append(1.0)
            elif len(term)>=4:scores.append(max((difflib.SequenceMatcher(None,term,w).ratio() for w in words),default=0))
            else:scores.append(0)
        return sum(scores) if all(v>=.78 for v in scores) else 0
    ranked=[(score(r),r) for r in rows]
    return [r for value,r in sorted(ranked,key=lambda pair:pair[0],reverse=True) if value>0]

def prepare(row,progress=lambda value:None):
    src=Path(row['path'])
    fingerprint=hashlib.sha256((str(src)+str(src.stat().st_mtime_ns)).encode()).hexdigest()[:24]
    out=STORE/'audio'/f'{fingerprint}.m4a';out.parent.mkdir(parents=True,exist_ok=True)
    if not out.exists():
        probe=json.loads(subprocess.check_output([FFPROBE,'-v','error','-select_streams','a:0','-show_entries','stream=codec_name,sample_rate,channels:format=duration','-of','json',str(src)],timeout=20))
        if not probe.get('streams'):raise ValueError('This file has no audio track.')
        stream=probe['streams'][0];copy=stream.get('codec_name')=='aac' and int(stream.get('sample_rate',0))<=48000 and int(stream.get('channels',2))<=2
        duration=float(probe.get('format',{}).get('duration') or 0)
        temp=out.with_suffix('.partial.m4a')
        args=['-c:a','copy'] if copy else ['-c:a','aac','-b:a','256k','-ar','44100','-ac','2']
        try:
            with tempfile.TemporaryFile() as report:
                proc=subprocess.Popen([FFMPEG,'-nostdin','-y','-v','error','-i',str(src),'-map','0:a:0','-vn',*args,'-progress','pipe:1','-movflags','+faststart',str(temp)],stdout=report,stderr=subprocess.DEVNULL)
                started=time.monotonic()
                try:
                    while proc.poll() is None:
                        if time.monotonic()-started>1800:raise RuntimeError('Audio preparation took too long. Please try again.')
                        matches=re.findall(rb'out_time_us=(\d+)',os.pread(report.fileno(),os.fstat(report.fileno()).st_size,0))
                        if matches and duration:progress(min(99,int(int(matches[-1])/10000/duration)))
                        time.sleep(.3)
                    if proc.returncode:raise RuntimeError('Could not prepare this audio file. Try another file.')
                finally:
                    if proc.poll() is None:proc.kill()
                    proc.wait()
            temp.replace(out)
        finally:
            temp.unlink(missing_ok=True)
    progress(100)
    route=f'/{out.name}'
    registry=json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    registry[route]=str(out);tmp=REGISTRY.with_suffix('.tmp');tmp.write_text(json.dumps(registry));tmp.replace(REGISTRY)
    return route
