"""Video source preparation for the app's own native player. No external player."""
import hashlib,subprocess,threading
from pathlib import Path
from media import STORE
from library import FFMPEG

class NativeVideo:
    def __init__(self):
        self.request=0;self.requested_id=None
        self.status={'active':False,'message':''}
        self.preparing=set();self.failures={};self.lock=threading.RLock()

    def open(self,row):
        source=row.get('videoPath')
        if not source or not Path(source).is_file():raise ValueError('No video file is available for this music.')
        with self.lock:self.request+=1;self.requested_id=row['id']
        return {'message':'Showing video. Sound stays on Sonos.'}

    def source(self,row,prepare=False):
        source=Path(row['videoPath'])
        if not source.is_file():return {'path':None,'message':'The video file is missing.'}
        if source.suffix.lower() in ('.mp4','.mov','.m4v'):return {'path':str(source),'message':''}
        key=hashlib.sha256((str(source)+str(source.stat().st_mtime_ns)).encode()).hexdigest()[:24]
        output=STORE/'video'/f'{key}.mp4'
        if output.exists():return {'path':str(output),'message':''}
        with self.lock:
            if key in self.failures:return {'path':None,'message':self.failures[key]}
            if prepare and key not in self.preparing:
                self.preparing.add(key)
                threading.Thread(target=self.remux,args=(source,output,key),daemon=True).start()
            message='Preparing this video for the built-in player…' if key in self.preparing else 'Show video to prepare this file.'
        return {'path':None,'message':message}

    def remux(self,source,output,key):
        temp=output.with_suffix('.partial.mp4')
        try:
            output.parent.mkdir(parents=True,exist_ok=True)
            # Repackage the existing picture; never decode/re-encode the long set.
            subprocess.run([FFMPEG,'-nostdin','-y','-v','error','-i',str(source),'-map','0:v:0','-an','-c:v','copy','-movflags','+faststart',str(temp)],check=True,timeout=600,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            temp.replace(output)
        except Exception:
            with self.lock:self.failures[key]='This video format cannot play in the built-in player.'
        finally:
            temp.unlink(missing_ok=True)
            with self.lock:self.preparing.discard(key)
