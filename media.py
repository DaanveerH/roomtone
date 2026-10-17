"""Only serves registered audio files, with byte ranges for Sonos seeking."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re, json, os
STORE = Path(os.environ.get('ROOMTONE_DATA_DIR', Path.home() / 'Library/Application Support/Roomtone'))
REGISTRY = STORE / 'media.json'
class MediaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_HEAD(self): self.serve(False)
    def do_GET(self): self.serve(True)
    def serve(self, body):
        try:
            registry = json.loads(REGISTRY.read_text())
            entry = registry.get(self.path.split('?')[0])
            if not entry: self.send_error(404); return
            path = Path(entry); size = path.stat().st_size
            start, end, code = 0, size - 1, 200
            value = self.headers.get('Range')
            if value:
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
                if not match or not any(match.groups()): self.send_error(416); return
                a,b=match.groups()
                if a: start=int(a); end=min(int(b),size-1) if b else size-1
                else: start=max(0,size-int(b))
                if start>end or start>=size:
                    self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.end_headers(); return
                code=206
            self.send_response(code)
            self.send_header('Content-Type', 'audio/mpeg' if path.suffix=='.mp3' else 'audio/mp4')
            self.send_header('Accept-Ranges','bytes'); self.send_header('Content-Length',str(end-start+1))
            if code==206: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            if body:
                with path.open('rb') as f:
                    f.seek(start); remaining=end-start+1
                    while remaining:
                        data=f.read(min(262144,remaining))
                        if not data:break
                        self.wfile.write(data);remaining-=len(data)
        except (BrokenPipeError,ConnectionResetError): pass
        except (OSError,ValueError): self.send_error(404)
if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',8775),MediaHandler).serve_forever()
