import os,atexit
import unittest,tempfile,threading,urllib.request,urllib.error,json,subprocess,time
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
_data=tempfile.TemporaryDirectory()
os.environ['ROOMTONE_DATA_DIR']=_data.name
atexit.register(_data.cleanup)
import media,library,sonos
import video

class AudioServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();root=Path(self.tmp.name)
        self.audio=root/'audio.m4a';self.audio.write_bytes(bytes(range(256))*8)
        registry=root/'media.json';registry.write_text(json.dumps({'/test.m4a':str(self.audio)}))
        self.patch=patch.object(media,'REGISTRY',registry);self.patch.start()
        self.server=ThreadingHTTPServer(('127.0.0.1',0),media.MediaHandler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.patch.stop();self.tmp.cleanup()
    def request(self,path='/test.m4a',headers=None,method='GET'):
        return urllib.request.urlopen(urllib.request.Request(self.url+path,headers=headers or {},method=method))
    def test_ranges_seek_exact_audio_bytes(self):
        with self.request(headers={'Range':'bytes=100-119'}) as r:
            self.assertEqual(r.status,206);self.assertEqual(r.read(),self.audio.read_bytes()[100:120]);self.assertEqual(r.headers['Content-Range'],'bytes 100-119/2048')
    def test_suffix_range(self):
        with self.request(headers={'Range':'bytes=-12'}) as r:self.assertEqual(r.read(),self.audio.read_bytes()[-12:])
    def test_head_does_not_send_audio(self):
        with self.request(method='HEAD') as r:self.assertEqual(r.read(),b'');self.assertEqual(r.headers['Content-Length'],'2048')
    def test_invalid_range_rejected(self):
        for value in ['bytes=2048-','bytes=10-2','bytes=-','bytes=1-2,3-4']:
            with self.assertRaises(urllib.error.HTTPError) as e:self.request(headers={'Range':value})
            self.assertEqual(e.exception.code,416)
    def test_unregistered_files_not_exposed(self):
        for path in ['/../settings.json','/media.json','/etc/passwd']:
            with self.assertRaises(urllib.error.HTTPError) as e:self.request(path)
            self.assertEqual(e.exception.code,404)

class LibraryTests(unittest.TestCase):
    def test_only_selected_folders_and_audio_preferred(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'Example Artist.mp4').touch();(root/'Example Artist.m4a').touch();(root/'notes.txt').touch();(root/'Screen Recording Test.mov').touch()
            rows=library.scan([temp]);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['format'],'M4A');self.assertNotIn('path',library.public(rows[0]))
            self.assertTrue(library.public(rows[0])['hasVideo']);self.assertNotIn('videoPath',library.public(rows[0]))
    def test_search_typo_accents_word_order_and_exact_first(self):
        rows=[{'id':'1','title':'Example Artist - Summer Festival 2023','folder':'Music'},
              {'id':'2','title':'Example Artist - Summers Festival 2022','folder':'Music'},
              {'id':'3','title':'Café del Mar','folder':'Music'}]
        self.assertEqual([r['id'] for r in library.lexical(rows,'2023 summer artist')],['1'])
        self.assertEqual([r['id'] for r in library.lexical(rows,'summer festval')],['1','2'])
        self.assertEqual([r['id'] for r in library.lexical(rows,'cafe')],['3'])
        self.assertEqual(library.lexical(rows,'xit'),[])
    def test_opus_conversion_reports_progress_and_reuses_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'summer.ogg'
            subprocess.run([library.FFMPEG,'-v','error','-f','lavfi','-i','sine=frequency=440:duration=2','-c:a','libopus',str(source)],check=True)
            row={'path':str(source),'title':'test'};progress=[]
            with patch.object(library,'STORE',root),patch.object(library,'REGISTRY',root/'media.json'):
                route=library.prepare(row,progress.append)
                self.assertEqual(progress[-1],100);self.assertTrue((root/'audio'/route[1:]).is_file())
                with patch.object(library.subprocess,'Popen') as convert:self.assertEqual(library.prepare(row),route);convert.assert_not_called()
            probe=json.loads(subprocess.check_output([library.FFPROBE,'-v','error','-show_entries','stream=codec_name,sample_rate,channels','-of','json',str(root/'audio'/route[1:])]))
            self.assertEqual(probe['streams'][0],{'codec_name':'aac','sample_rate':'44100','channels':2})
    def test_regular_search_accepts_prefixes_and_requires_meaningful_terms(self):
        rows=[{'id':'1','title':'Example Artist - Winter Festival 2023','folder':'Music'},
              {'id':'2','title':'Other Artist - Night Session','folder':'Music'}]
        self.assertEqual([r['id'] for r in library.lexical(rows,'artist winter')],['1'])
        self.assertEqual(library.lexical(rows,'artist in desert'),[])
        self.assertEqual(library.lexical(rows,'zzzzzz'),[])
    def test_time_conversion(self):
        self.assertEqual(sonos.seconds('2:14:28'),8068);self.assertEqual(sonos.timestamp(8068),'02:14:28');self.assertEqual(sonos.seconds('NOT_IMPLEMENTED'),0)


class ControlTests(unittest.TestCase):
    def setUp(self):
        import server
        self.server=server
        self.room={'id':'a','ip':'192.0.2.2','coordinator':'a','name':'Test'}
    def test_seek_clamps_and_live_radio_rejects(self):
        with patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'soap',side_effect=[{'TrackDuration':'00:01:00'},{}]) as call:
            self.server.action({'action':'seek','seconds':900})
            self.assertEqual(call.call_args.kwargs['Target'],'00:00:59')
        with patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'soap',return_value={'TrackDuration':'NOT_IMPLEMENTED'}):
            with self.assertRaisesRegex(ValueError,'cannot seek'):self.server.action({'action':'seek','seconds':10})
    def test_next_previous_use_local_library(self):
        with patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'rows',[{'id':'a'},{'id':'b'}]),patch.object(self.server,'state',{'currentId':'a'}),patch.object(self.server,'start_playback',return_value={}) as play:
            self.server.action({'action':'next'});play.assert_called_with('b')
            self.server.action({'action':'previous'});play.assert_called_with('b')
    def test_preparation_returns_immediately_and_rejects_duplicate(self):
        entered=threading.Event();finish=threading.Event();row={'id':'a','title':'Summer'}
        def prepare(*args):entered.set();finish.wait(2)
        with patch.object(self.server,'preparations',threading.Lock()),patch.object(self.server,'rows',[row]),patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'play_file',side_effect=prepare),patch.object(self.server,'preparation',{'active':False}):
            result=self.server.start_playback('a');self.assertTrue(result['preparing']);self.assertTrue(entered.wait(1))
            with self.assertRaisesRegex(ValueError,'already being prepared'):self.server.start_playback('a')
            finish.set()
            self.assertTrue(self.server.preparations.acquire(timeout=2));self.server.preparations.release()
            self.assertFalse(self.server.preparation['active'])
    def test_preparation_failure_is_visible_and_unlocks_retry(self):
        with patch.object(self.server,'preparations',threading.Lock()),patch.object(self.server,'rows',[{'id':'a','title':'Summer'}]),patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'play_file',side_effect=ValueError('File unavailable')),patch.object(self.server,'preparation',{'active':False}):
            self.server.start_playback('a')
            self.assertTrue(self.server.preparations.acquire(timeout=2));self.server.preparations.release()
            self.assertEqual(self.server.preparation['error'],'File unavailable');self.assertFalse(self.server.preparation['active'])
    def test_preparation_does_not_move_audio_to_a_different_speaker(self):
        with patch.object(self.server,'rows',[{'id':'a','title':'Summer'}]),patch.object(self.server.library,'prepare',return_value='/audio.m4a'),patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'soap') as soap:
            with self.assertRaisesRegex(ValueError,'speakers changed'):self.server.play_file('a',{'id':'other','ip':'198.51.100.2'})
            soap.assert_not_called()
    def test_trueplay_cannot_fake_calibration(self):
        with patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'devices',[self.room]),patch.object(self.server,'soap',return_value={'RoomCalibrationAvailable':'0'}) as call:
            with self.assertRaisesRegex(ValueError,'phone app'):self.server.action({'action':'tune','id':'a','field':'trueplay','value':True})
            self.assertEqual(call.call_count,1)
    def test_volume_clamped(self):
        with patch.object(self.server,'leader',return_value=self.room),patch.object(self.server,'soap',return_value={}) as call:
            self.server.action({'action':'volume','value':999});self.assertEqual(call.call_args.kwargs['DesiredVolume'],100)

class VideoTests(unittest.TestCase):
    def test_missing_video_does_not_request_window(self):
        controller=video.NativeVideo()
        with self.assertRaisesRegex(ValueError,'No video'):controller.open({'id':'audio'})
        self.assertEqual(controller.request,0)
    def test_native_mp4_is_reused_without_conversion(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'Summer.mp4';source.touch()
            controller=video.NativeVideo();row={'id':'summer','videoPath':str(source)}
            with patch.object(video.subprocess,'run') as convert:
                self.assertEqual(controller.source(row)['path'],str(source))
                controller.open(row);self.assertEqual(controller.requested_id,'summer');self.assertEqual(controller.request,1)
                convert.assert_not_called()
    def test_mkv_prepares_once_without_reencoding_or_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'video.mkv'
            subprocess.run([library.FFMPEG,'-v','error','-f','lavfi','-i','color=c=black:s=64x64:d=1','-f','lavfi','-i','sine=duration=1','-c:v','libx264','-c:a','aac','-shortest',str(source)],check=True)
            controller=video.NativeVideo();row={'id':'test','videoPath':str(source)}
            with patch.object(video,'STORE',root):
                self.assertIsNone(controller.source(row)['path']);self.assertFalse(controller.preparing)
                controller.source(row,prepare=True)
                deadline=time.monotonic()+5
                while controller.preparing and time.monotonic()<deadline:time.sleep(.05)
                output=controller.source(row)['path'];self.assertIsNotNone(output)
                with patch.object(video.subprocess,'run') as convert:
                    self.assertEqual(controller.source(row,prepare=True)['path'],output);convert.assert_not_called()
            probe=json.loads(subprocess.check_output([library.FFPROBE,'-v','error','-show_entries','stream=codec_type,codec_name','-of','json',output]))
            self.assertEqual(probe['streams'],[{'codec_name':'h264','codec_type':'video'}])
    def test_native_status_does_not_control_sonos(self):
        import server
        with patch.object(server,'video',video.NativeVideo()),patch.object(server,'soap') as soap:
            server.action({'action':'nativeVideoStatus','active':False,'ready':True,'muted':True,'loads':1,'unexpected':'omit'})
            self.assertTrue(server.video.status['ready']);self.assertNotIn('unexpected',server.video.status);soap.assert_not_called()

class ReconnectionTests(unittest.TestCase):
    def setUp(self):
        import server
        self.s=server
        self.office=[{'id':'office','name':'Office','ip':'192.0.2.52','coordinator':'office'}]
        self.home=[{'id':'home','name':'Bedroom','ip':'198.51.100.156','coordinator':'home'}]
        self.config={'known':['192.0.2.52'],'selected':['office'],'leader':'office','places':{}}
    def test_home_replaces_office_selection_without_playback_commands(self):
        with patch.object(self.s,'config',self.config),patch.object(self.s,'devices',self.office),patch.object(self.s,'soap') as soap:
            self.s.use_household(self.home)
            self.assertEqual(self.config['selected'],['home'])
            self.assertEqual(self.config['leader'],'home')
            self.assertEqual(self.config['places']['office']['selected'],['office'])
            soap.assert_not_called()
    def test_returning_to_a_place_restores_its_room_choice(self):
        office=self.office+[{'id':'office2','name':'Office 2','ip':'192.0.2.42','coordinator':'office'}]
        self.config['selected']=['office2'];self.config['leader']='office2'
        with patch.object(self.s,'config',self.config),patch.object(self.s,'devices',office):
            self.s.use_household(self.home)
            self.s.devices=self.home
            self.s.use_household(office)
            self.assertEqual(self.config['selected'],['office2'])
    def test_new_place_follows_existing_group(self):
        home=self.home+[{'id':'kitchen','name':'Kitchen','ip':'198.51.100.8','coordinator':'home'}]
        with patch.object(self.s,'config',self.config),patch.object(self.s,'devices',self.office):
            self.s.use_household(home)
            self.assertEqual(set(self.config['selected']),{'home','kitchen'})
    def test_failed_cached_addresses_trigger_live_discovery(self):
        def topology(ip):
            if ip=='198.51.100.156':return self.home
            raise TimeoutError()
        with patch.object(self.s,'config',self.config),patch.object(self.s,'devices',self.office),patch.object(self.s,'last_discovery',float('-inf')),patch.object(self.s,'save'),patch.object(self.s,'discover',return_value=['198.51.100.156']) as discover,patch.object(self.s,'topology',side_effect=topology):
            self.s.refresh_devices()
            discover.assert_called_once()
            self.assertEqual(self.s.leader()['name'],'Bedroom')
            self.assertEqual(self.config['known'],['198.51.100.156'])
    def test_no_speakers_clears_stale_devices(self):
        with patch.object(self.s,'config',self.config),patch.object(self.s,'devices',self.office),patch.object(self.s,'discover',return_value=[]),patch.object(self.s,'topology',side_effect=TimeoutError()):
            with self.assertRaisesRegex(RuntimeError,'same Wi-Fi'):self.s.refresh_devices(force=True)
            self.assertEqual(self.s.devices,[])
    def test_missing_optional_tuning_does_not_hide_online_room(self):
        def soap(ip,service,action,**kw):
            if action=='GetRoomCalibrationStatus':raise RuntimeError('unsupported')
            return {'GetVolume':{'CurrentVolume':'20'},'GetBass':{'CurrentBass':'0'},'GetTreble':{'CurrentTreble':'0'},'GetLoudness':{'CurrentLoudness':'1'}}[action]
        with patch.object(self.s,'soap',side_effect=soap):
            room=self.s.read_room(self.home[0])
            self.assertTrue(room['online']);self.assertFalse(room['calibrated'])

class DistributionTests(unittest.TestCase):
    def test_build_metadata_does_not_install_background_service(self):
        import install
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=root/'Roomtone.app';(app/'Contents').mkdir(parents=True)
            install.write_metadata(app,root/'home')
            self.assertTrue((app/'Contents/Info.plist').exists())
            self.assertFalse((root/'home').exists())

    def test_first_install_creates_support_and_registered_helper(self):
        import install,plistlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'new user';app=home/'Applications/Roomtone.app'
            (app/'Contents').mkdir(parents=True)
            install.write_metadata(app,home,True)
            job=plistlib.loads((home/'Library/LaunchAgents'/f'{install.LABEL}.plist').read_bytes())
            self.assertEqual(job['ProgramArguments'],['/usr/bin/python3',str(app/'Contents/Resources/service/media.py')])
            self.assertTrue((home/'Library/Application Support/Roomtone').is_dir())
            self.assertTrue(job['KeepAlive'])

    def test_controller_rejects_missing_token_and_foreign_origins(self):
        import server
        from types import SimpleNamespace
        cases=[
            ({'Host':'127.0.0.1:8776'},False),
            ({'Host':'127.0.0.1:8776','X-Roomtone-Token':'test-only'},True),
            ({'Host':'other.example:8776','X-Roomtone-Token':'test-only'},False),
            ({'Host':'127.0.0.1:8776','X-Roomtone-Token':'test-only','Origin':'https://other.example'},False),
            ({'Host':'127.0.0.1:8776','X-Roomtone-Token':'wrong'},False),
        ]
        with patch.object(server,'token','test-only'):
            for headers,expected in cases:
                self.assertEqual(server.Handler.allowed(SimpleNamespace(headers=headers)),expected)

if __name__=='__main__':unittest.main()
