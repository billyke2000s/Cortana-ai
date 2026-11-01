"""Companion release regression checks; no network or native voice required."""
import json
import sqlite3
import tarfile
import tempfile
import threading
import zipfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import test_offline as base
import companion
import lips

class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();path=Path(self.tmp.name)/'old.db'
        db=sqlite3.connect(path);db.executescript(base.store.SCHEMA)
        db.execute("INSERT INTO facts(text,created) VALUES('My home is York',1)");db.commit();db.close()
        self.s=base.store.Store(path)
    def tearDown(self):self.s.close();self.tmp.cleanup()

    def test_upgrade_preserves_data_and_notification_channels(self):
        self.assertEqual(self.s.facts()[0]['text'],'My home is York')
        tid=self.s.add_item('timer','Tea',time.time()-10)
        self.assertEqual(self.s.pending_notifications()[0]['id'],tid)
        self.s.mark_notified(tid,self.s.item(tid)['due'])
        self.assertEqual(self.s.pending_notifications(),[]);self.assertEqual(len(self.s.due_alerts()),1)

    def test_snooze_rearms_and_rejects_stale_notification(self):
        tid=self.s.add_item('timer','Tea',time.time()-10);old=self.s.item(tid)['due']
        self.s.acknowledge(tid);self.s.snooze(tid,10);self.s.mark_notified(tid,old)
        item=self.s.item(tid)
        self.assertEqual((item['done'],item['announced'],item['notified']),(0,0,0))
        self.assertGreater(item['due'],time.time()+590)
        for bad in [0,-1,1441,float('nan'),float('inf')]:
            with self.assertRaises(ValueError):self.s.snooze(tid,bad)

    def test_relevance_recovers_old_memory_in_budget(self):
        for i in range(50):self.s.add_fact('Favourite game number '+str(i))
        facts=self.s.relevant_facts('What is my home town?')
        self.assertEqual(facts[0]['text'],'My home is York')
        self.assertLessEqual(sum(len(f['text'])+2 for f in facts),1800);self.assertLessEqual(len(facts),12)

    def test_edit_and_conflict_review(self):
        fid=self.s.add_fact('My home is Leeds');self.assertEqual(len(self.s.fact_conflicts()),1)
        self.s.edit_fact(fid,'My office is Leeds');self.assertEqual(self.s.fact_conflicts(),[])
        with self.assertRaises(ValueError):self.s.edit_fact(fid,' ')
        with self.assertRaises(ValueError):self.s.edit_fact(999,'A fact')

    def test_recap_budget_and_clear_race(self):
        for i in range(80):self.s.log_message('user' if i%2==0 else 'assistant',str(i)+' '+('long sentence '*80))
        self.assertLessEqual(len(self.s.conversation_summary()),800)
        old=self.s.conversation_version();self.s.clear_messages();self.s.log_exchange('Stale','Reply',old)
        self.assertEqual(self.s.conversation_summary(),'');self.assertEqual(self.s.recent_messages(),[])

class CancellationTests(unittest.TestCase):
    def test_cancelled_queue_never_enters_native_work(self):
        jobs=companion.Jobs();jobs.cancel('client_turn')
        with self.assertRaises(companion.Cancelled):
            with jobs.scope('client_turn'):self.fail('Cancelled work started')
        with jobs.scope('different_turn'):jobs.check()

    def test_thread_local_isolation(self):
        jobs=companion.Jobs();jobs.cancel('one');result=[]
        def work():
            with jobs.scope('two'):jobs.check();result.append(True)
        t=threading.Thread(target=work);t.start();t.join();self.assertEqual(result,[True])

    def test_ids_and_telemetry(self):
        jobs=companion.Jobs()
        for value in ['',{},'../secret','x'*101]:
            with self.assertRaises(ValueError):jobs.key(value)
        jobs.measure('tts_ms',time.perf_counter()-.05);self.assertGreaterEqual(jobs.snapshot()['tts_ms'],45)

    def test_tar_rejects_traversal_and_links(self):
        for name,link in [('../escape',False),('link',True)]:
            with tempfile.TemporaryDirectory() as tmp:
                archive=Path(tmp)/'bad.tar.bz2'
                with tarfile.open(archive,'w:bz2') as t:
                    info=tarfile.TarInfo(name)
                    if link:info.type=tarfile.SYMTYPE;info.linkname='/tmp/outside'
                    t.addfile(info)
                with self.assertRaises(RuntimeError):base.runtime.extract(archive,Path(tmp)/'out')

    def test_mouth_cues_include_closed_lips_and_silence(self):
        result=lips.cues({'mouthCues':[{'start':0,'end':.1,'value':'A'},{'start':.1,'end':.4,'value':'D'},{'start':.4,'end':.5,'value':'X'}]})
        self.assertEqual([c['id'] for c in result],[21,2,0]);self.assertAlmostEqual(result[1]['duration'],.3)

class CompanionApiTests(unittest.TestCase):
    request=base.ApiTests.request
    @classmethod
    def setUpClass(cls):
        cls.rt=base.runtime.Runtime();cls.rt.store.close();cls.rt.store=base.store.Store(':memory:')
        cls.rt.voice.speak=base.silent_voice;cls.rt.ai_ready=True
        cls.rt.tag_exists={m['tag']:True for m in base.hardware.CATALOG};cls.rt.tunnel_host='phone.example'
        cls.srv=base.server.AppServer(('127.0.0.1',0),cls.rt);cls.port=cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever,daemon=True).start()
    @classmethod
    def tearDownClass(cls):cls.srv.shutdown();cls.srv.server_close();cls.rt.store.close()

    def test_preferences_roundtrip_and_invalid_choices(self):
        with patch.object(self.rt.voice,'switch') as switch:
            self.assertEqual(self.request('POST','/api/settings',{'expression_mode':'expressive','setup_complete':True,'native_notifications':False,'voice_engine':'zipvoice'})[0],200)
            switch.assert_called_with('zipvoice',None)
        s=json.loads(self.request('GET','/api/settings')[2]);self.assertEqual(s['expression_mode'],'expressive')
        self.assertTrue(s['setup_complete']);self.assertFalse(s['native_notifications'])
        for body in [{'expression_mode':'wild'},{'setup_complete':'yes'},{'native_notifications':1},{'voice_engine':'cloud'}]:
            self.assertEqual(self.request('POST','/api/settings',body)[0],400)

    def test_cancelled_speech_rejected_other_turn_works(self):
        self.request('POST','/api/cancel',{'request_id':'cancelled'})
        self.assertEqual(self.request('POST','/api/speech',{'text':'Do not generate','request_id':'cancelled'})[0],503)
        self.assertEqual(self.request('POST','/api/speech',{'text':'Hello','request_id':'next'})[0],200)

    def test_saved_conversation_and_memory_edit(self):
        fid=self.rt.store.add_fact('Favourite colour blue')
        self.assertEqual(self.request('POST','/api/memory',{'action':'edit','id':fid,'text':'Favourite colour cyan'})[0],200)
        self.rt.store.log_message('user','A saved turn')
        self.assertEqual(json.loads(self.request('GET','/api/conversation')[2])['messages'][-1]['content'],'A saved turn')

    def test_new_routes_keep_origin_auth_and_private_assets(self):
        for path,body in [('/api/cancel',{'request_id':'x'}),('/api/metrics',{'playback_ms':100})]:
            self.assertEqual(self.request('POST',path,body,{'Origin':'https://evil.example'})[0],403)
            self.assertEqual(self.request('POST',path,body,host='phone.example')[0],403)
        self.assertEqual(self.request('GET','/api/conversation',host='phone.example')[0],403)
        for path in ['/neural.py','/lips.py','/companion.py','/proactive.py','/work.py','/voice-profile/reference.wav','/voice-profile/voice_profile.json']:
            self.assertEqual(self.request('GET',path)[0],404)

    def test_whisper_decides_every_wake_burst(self):
        # 1.5 dropped a burst whenever the small keyword detector said no, and it said no to clear "Hey Cortana"s (D-037).
        with patch.object(self.rt.neural,'detect',return_value=False),patch.object(self.rt,'transcribe',return_value='Hey Cortana, what time is it?') as transcribe:
            for interrupt in (False,True):
                data=json.loads(self.request('POST','/api/transcribe',{'wake':True,'interrupt':interrupt,'audio':base.base64.b64encode(b'placeholder').decode()})[2])
                self.assertEqual((data['wake'],data['rest']),(True,'what time is it?'))
            self.assertEqual(transcribe.call_count,2)

    def test_server_cancellation_prevents_tool_side_effect(self):
        def chunks(payload):
            self.rt.jobs.cancel('stopped_tool')
            yield {'message':{'tool_calls':[{'function':{'name':'add_task','arguments':{'text':'Should not exist'}}}]}}
        original_model=self.rt.model
        with patch.object(self.rt,'ollama_stream',chunks):
            events=self.request('POST','/api/chat-stream',{'messages':[{'role':'user','content':'Add a task'}],'request_id':'stopped_tool'})[2].decode()
        self.assertEqual(self.rt.model,original_model)
        self.assertIn('error',events);self.assertFalse(any(i['text']=='Should not exist' for i in self.rt.store.items()))

class VoiceSpeedAndReminderTests(unittest.TestCase):
    """1.6 step 1: unpack voice files once, never-blocking reminder balloons with backoff, no recap gap."""
    def test_voice_archive_unpacks_once(self):
        import neural
        with tempfile.TemporaryDirectory() as tmp,patch.object(neural,'DATA',Path(tmp)),\
             patch.object(neural,'download') as download,patch.object(neural,'extract') as extract:
            n=neural.Neural(lambda m:None)
            def fake_extract(archive,directory):(Path(directory)/neural.ZIP_NAME).mkdir(parents=True,exist_ok=True)
            extract.side_effect=fake_extract
            folder=n.unpacked(neural.ZIP_NAME,'tts-models')
            self.assertEqual(extract.call_count,1);self.assertTrue((folder/'.unpacked').exists())
            n.unpacked(neural.ZIP_NAME,'tts-models')   # next launch: no re-hash of the 109 MB archive, no re-unpack
            self.assertEqual(extract.call_count,1);self.assertEqual(download.call_count,1)

    def test_voice_threads_are_bounded(self):
        import neural
        self.assertTrue(2<=neural.THREADS<=8)

    def test_installed_lip_sync_skips_download(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(lips,'DATA',Path(tmp)),patch.object(lips,'download') as download:
            exe=Path(tmp)/'rhubarb'/'Rhubarb-Lip-Sync-1.14.0'/('rhubarb.exe' if lips.os.name=='nt' else 'rhubarb')
            exe.parent.mkdir(parents=True);exe.write_bytes(b'')
            l=lips.Lips();l.prepare(lambda m:None)
            download.assert_not_called();self.assertEqual(l.exe,exe);self.assertEqual(l.status,'Local audio alignment ready.')

    def make_runtime(self):
        rt=object.__new__(base.runtime.Runtime)
        rt.store=base.store.Store(':memory:');rt.closing=threading.Event();self.addCleanup(rt.store.close)
        return rt

    def test_failed_balloon_backs_off_then_gives_up(self):
        rt=self.make_runtime();tid=rt.store.add_item('reminder','Call home',time.time()-5);calls=[]
        with patch.object(companion,'notify',side_effect=lambda text,title='':calls.append(text) or False):
            rt.notification_tick(now=0,wait=True);self.assertEqual(len(calls),1)
            rt.notification_tick(now=30,wait=True);self.assertEqual(len(calls),1)    # not every 2 seconds
            rt.notification_tick(now=61,wait=True);self.assertEqual(len(calls),2)
            rt.notification_tick(now=150,wait=True);self.assertEqual(len(calls),2)   # second wait is 2 minutes
            rt.notification_tick(now=200,wait=True);self.assertEqual(len(calls),3)
            rt.notification_tick(now=10**6,wait=True);self.assertEqual(len(calls),3)  # given up after 3 tries
        self.assertEqual(rt.store.pending_notifications(),[]);self.assertEqual(rt.store.due_alerts()[0]['id'],tid)   # in-app alert still fires

    def test_balloon_does_not_block_the_loop(self):
        rt=self.make_runtime();rt.store.add_item('timer','Tea',time.time()-5);release=threading.Event()
        def slow(text,title=''):release.wait(5);return True
        with patch.object(companion,'notify',side_effect=slow):
            started=time.monotonic();rt.notification_tick(now=0);rt.notification_tick(now=1)
            self.assertLess(time.monotonic()-started,1)   # the old loop waited ~9 s per balloon
            release.set()
            for _ in range(50):
                if not rt.store.pending_notifications():break
                time.sleep(.05)
        self.assertEqual(rt.store.pending_notifications(),[])

    def test_recap_starts_where_sent_history_ends(self):
        s=base.store.Store(':memory:');self.addCleanup(s.close)
        for i in range(20):s.log_message('user' if i%2==0 else 'assistant',f'msg{i}')
        # The model sees the 15 newest earlier messages (msg5..msg19); the recap must cover msg4 and older, with no gap or overlap.
        recap=s.conversation_summary().split('\n')
        self.assertEqual(recap[-1],'user: msg4');self.assertNotIn('msg5',s.conversation_summary())

class BrainTests(unittest.TestCase):
    """1.6 step 2: deep thinking and a context size that fits the graphics card."""
    def test_context_fits_graphics_card(self):
        h=base.hardware;nine=next(m for m in h.CATALOG if m['tag']=='qwen3.5:9b');four=next(m for m in h.CATALOG if m['tag']=='qwen3.5:4b')
        self.assertEqual(h.context_for(nine,{'vram_gb':8}),6144)      # 9B already spills on 8 GB: no bigger cache
        self.assertEqual(h.context_for(nine,{'vram_gb':12}),16384)
        self.assertEqual(h.context_for(four,{'vram_gb':6}),16384);self.assertEqual(h.context_for(four,{'vram_gb':4}),6144)
        self.assertEqual(h.context_for(nine,{'vram_gb':None}),6144)   # processor only
        moe=next(m for m in h.CATALOG if m['moe']);self.assertEqual(h.context_for(moe,{'vram_gb':48}),6144)

    def test_deep_thought_phrases(self):
        w=base.runtime.wants_deep_thought
        for yes in ['Think carefully about which laptop to buy','take your time and compare them','Can you think it through?']:self.assertTrue(w(yes),yes)
        for no in ['What do you think of this?','Set a timer','I think so']:self.assertFalse(w(no),no)

class BrainApiTests(unittest.TestCase):
    request=base.ApiTests.request
    setUpClass=classmethod(CompanionApiTests.setUpClass.__func__)
    tearDownClass=classmethod(CompanionApiTests.tearDownClass.__func__)

    def stream(self,body):
        status,_,raw=self.request('POST','/api/chat-stream',body)
        return status,[json.loads(l) for l in raw.decode().splitlines() if l.strip()] if status==200 else raw

    def test_think_flag_reaches_ollama_and_reasoning_is_never_spoken(self):
        base.fake_ollama.CHAT_REQUESTS.clear()
        status,events=self.stream({'messages':[{'role':'user','content':'Hello there'}],'think':True})
        self.assertEqual(status,200);req=base.fake_ollama.CHAT_REQUESTS[-1]
        self.assertIs(req['think'],True);self.assertGreater(req['options']['num_predict'],1200)
        self.assertEqual(events[0],{'type':'tool','name':'think','label':'THINKING IT THROUGH'})
        spoken=' '.join(e['text'] for e in events if e['type']=='sentence')
        self.assertNotIn('weigh the options',spoken);self.assertEqual(events[-1]['type'],'done')

    def test_normal_turn_does_not_think_and_bad_flag_rejected(self):
        base.fake_ollama.CHAT_REQUESTS.clear()
        self.stream({'messages':[{'role':'user','content':'Hello there'}]})
        req=base.fake_ollama.CHAT_REQUESTS[-1];self.assertIs(req['think'],False);self.assertEqual(req['options']['num_predict'],1200)
        self.assertEqual(self.request('POST','/api/chat-stream',{'messages':[{'role':'user','content':'Hi'}],'think':'yes'})[0],400)

    def test_context_mode_setting(self):
        self.assertEqual(self.request('POST','/api/settings',{'context_mode':'huge'})[0],400)
        self.assertEqual(self.request('POST','/api/settings',{'context_mode':'standard'})[0],200)
        s=json.loads(self.request('GET','/api/settings')[2]);self.assertEqual((s['context_mode'],s['context']),('standard',6144))
        self.rt.store.set('context_mode','auto')

class ProactiveTests(unittest.TestCase):
    """1.6 step 3: she notices new documents, finished downloads and briefing time on her own."""
    def setUp(self):
        import proactive;self.p=proactive
        self.s=base.store.Store(':memory:');self.addCleanup(self.s.close)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.dir=Path(self.tmp.name)

    def notices(self):return [i['text'] for i in self.s.due_alerts() if i['kind']=='notice']

    def test_new_document_is_read_and_mentioned_once(self):
        (self.dir/'old.txt').write_text('Old notes about the garden.')
        self.s.set('doc_folders',[str(self.dir)])
        self.p.watch_folders_tick(self.s);self.assertEqual(self.notices(),[])   # first run: existing files are known
        (self.dir/'plan.md').write_text('Project plan: launch in March.')
        self.p.watch_folders_tick(self.s)
        self.assertEqual(self.notices(),['New document ready: plan.md. Ask me to summarise it.'])
        self.assertIn('plan.md',[d['name'] for d in self.s.documents()])
        self.p.watch_folders_tick(self.s);self.assertEqual(len(self.notices()),1)
        self.assertEqual(self.s.items(),[])   # notices never clutter Objectives or the briefing list

    def test_many_new_documents_are_grouped_and_switch_off(self):
        self.s.set('doc_folders',[str(self.dir)]);self.p.watch_folders_tick(self.s)
        for i in range(6):(self.dir/f'n{i}.txt').write_text(f'Note number {i} with text.')
        self.s.set('watch_folders',False);self.p.watch_folders_tick(self.s);self.assertEqual(self.notices(),[])
        self.s.set('watch_folders',True);self.p.watch_folders_tick(self.s)
        n=self.notices();self.assertEqual(len(n),4);self.assertEqual(n[-1],'3 more new documents are ready in your folders.')

    def test_finished_downloads_only_when_enabled_and_settled(self):
        (self.dir/'before.zip').write_bytes(b'x')
        self.p.watch_downloads_tick(self.s,folder=self.dir);self.assertIsNone(self.s.get('downloads_seen',None))   # off by default
        self.s.set('watch_downloads',True);self.p.watch_downloads_tick(self.s,folder=self.dir)   # remembers what was there
        (self.dir/'game.exe').write_bytes(b'x');(self.dir/'movie.mkv.crdownload').write_bytes(b'x')
        now=time.time()
        self.p.watch_downloads_tick(self.s,now=now,folder=self.dir);self.assertEqual(self.notices(),[])   # still settling
        self.p.watch_downloads_tick(self.s,now=now+60,folder=self.dir)
        self.assertEqual(self.notices(),['Download finished: game.exe.'])

    def test_daily_briefing_once_inside_window(self):
        from datetime import datetime
        self.s.set('briefing_time','07:30');at=datetime.now().replace(hour=7,minute=30,second=0,microsecond=0).timestamp()
        self.assertFalse(self.p.briefing_tick(self.s,at-60))
        self.assertTrue(self.p.briefing_tick(self.s,at+120));self.assertFalse(self.p.briefing_tick(self.s,at+600))
        self.assertEqual([i['kind'] for i in self.s.due_alerts()],['briefing'])
        self.s.set('briefing_last','');self.assertFalse(self.p.briefing_tick(self.s,at+4*3600))   # PC was off all morning: skip

    def test_acknowledged_notice_is_done(self):
        nid=self.s.add_notice('Download finished: a.zip.');self.s.acknowledge(nid)
        self.assertEqual(self.s.item(nid)['done'],1);self.assertEqual(self.s.due_alerts(),[])
        with self.assertRaises(ValueError):self.s.add_notice('x','timer')

class ProactiveSettingsTests(unittest.TestCase):
    request=base.ApiTests.request
    setUpClass=classmethod(CompanionApiTests.setUpClass.__func__)
    tearDownClass=classmethod(CompanionApiTests.tearDownClass.__func__)
    def test_settings_roundtrip_and_validation(self):
        self.assertEqual(self.request('POST','/api/settings',{'briefing_time':'07:30','watch_downloads':True,'watch_folders':False})[0],200)
        s=json.loads(self.request('GET','/api/settings')[2])
        self.assertEqual((s['briefing_time'],s['watch_downloads'],s['watch_folders']),('07:30',True,False))
        for bad in [{'briefing_time':'7:30'},{'briefing_time':'25:00'},{'briefing_time':730},{'watch_downloads':'yes'}]:
            self.assertEqual(self.request('POST','/api/settings',bad)[0],400,bad)
        self.assertEqual(self.request('POST','/api/settings',{'briefing_time':''})[0],200)

class WorkAbilityTests(unittest.TestCase):
    """1.6 steps 4-5: ask-before-doing gate and work abilities (no network, no real user folders)."""
    def setUp(self):
        import work;self.w=work
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.dir=Path(self.tmp.name)
        patcher=patch.dict(base.os.environ,{'CORTANA_OUTPUT_DIR':str(self.dir/'out')});patcher.start();self.addCleanup(patcher.stop)
        self.s=base.store.Store(':memory:');self.addCleanup(self.s.close)

    def test_document_is_a_valid_docx_and_never_overwrites(self):
        r1=self.w.create_file({'name':'Plan: Q3/Q4','kind':'document','content':'# Plan\n## Goals\n- **Ship** it\nA <b>paragraph</b> & more.'})
        r2=self.w.create_file({'name':'Plan: Q3/Q4','kind':'document','content':'Second'})
        self.assertEqual((r1['file'],r2['file']),('Plan Q3 Q4.docx','Plan Q3 Q4 (2).docx'))
        with zipfile.ZipFile(r1['path']) as z:self.assertIn('word/document.xml',z.namelist())
        text,_=base.files.extract_text('a.docx',Path(r1['path']).read_bytes())
        for part in ['Plan','Goals','Ship it','A <b>paragraph</b> & more.']:self.assertIn(part,text)

    def test_spreadsheet_webpage_and_bad_input(self):
        r=self.w.create_file({'name':'Costs','kind':'spreadsheet','content':'Item,Cost\nTea,2.50\nCake,3'})
        self.assertEqual(Path(r['path']).read_bytes(),'\ufeffItem,Cost\r\nTea,2.50\r\nCake,3\r\n'.encode())
        page=Path(self.w.create_file({'name':'x','kind':'webpage','content':'# Hi\n<script>alert(1)</script>'})['path']).read_text()
        self.assertNotIn('<script>alert',page);self.assertIn('&lt;script&gt;',page)
        for bad in [{'kind':'exe','content':'x'},{'kind':'text','content':' '},{'kind':'spreadsheet','content':'just words'},{'kind':'text','content':'x'*20001}]:
            with self.assertRaises(ValueError):self.w.create_file(bad)
        self.assertEqual(self.w.clean_name('..\\..\\Windows\\evil.bat','text'),'Windows evil.txt');self.assertEqual(self.w.clean_name('CON','text'),'_CON.txt')

    def test_calculate_is_exact_and_safe(self):
        c=lambda e:self.w.calculate(e)['result']
        self.assertEqual(c('15% of 80'),12);self.assertEqual(c('(1200*0.2)+45'),285);self.assertEqual(c('1,250 × 3'),3750);self.assertEqual(c('0.1+0.2'),0.3)
        for bad in ["__import__('os').system('calc')",'open("x")','2**10000','1/0','a+1','(lambda:1)()']:
            with self.assertRaises((ValueError,SyntaxError),msg=bad):self.w.calculate(bad)

    def test_analyse_table_totals(self):
        text='Month,Sales,Note\nJan,"£1,200",ok\nFeb,800,(late)\nMar,(100),x\n'+'\n'.join(f'Day {i},1,filler text here' for i in range(200))
        self.s.add_document('sales.csv',text,base.files.chunks(text))   # long enough to be stored in several pieces
        r=self.w.analyse_table(self.s,{'document':'sales'})
        self.assertGreater(len(base.files.chunks(text)),1)
        self.assertEqual(r['rows'],203);col=r['numeric_columns'][0]
        self.assertEqual((col['column'],col['total'],col['min'],col['max']),('Sales',2100,-100,1200))

    def test_organise_moves_only_and_reports_duplicates(self):
        dl=self.dir/'Downloads';dl.mkdir();(dl/'Images').mkdir();(dl/'Images'/'a.png').write_bytes(b'old')
        for name,data in [('a.png',b'img'),('b.png',b'img'),('setup.exe',b'exe'),('notes.pdf',b'pdf'),('x.crdownload',b'..'),('link.lnk',b'l')]:(dl/name).write_bytes(data)
        with patch.object(self.w,'known_folder',lambda name:dl):
            plan=self.w.preview_organise({'folder':'downloads'})
            self.assertIn('Move 4 loose files',plan['summary']);self.assertIn('a.png = b.png',plan['detail'])
            self.assertTrue((dl/'a.png').exists())   # a preview never changes anything
            r=self.w.organise({'folder':'downloads'})
        self.assertEqual((dl/'Images'/'a.png').read_bytes(),b'old')   # never overwritten
        self.assertTrue((dl/'Images'/'a (2).png').exists() and (dl/'Installers'/'setup.exe').exists() and (dl/'Documents'/'notes.pdf').exists())
        self.assertTrue((dl/'x.crdownload').exists() and (dl/'link.lnk').exists());self.assertTrue(r['identical_copies'])
        with self.assertRaises(ValueError):self.w.preview_organise({'folder':'C:\\Windows'})

    def test_email_draft_needs_content_and_valid_address(self):
        with self.assertRaises(ValueError):self.w.preview_email({'to':'not an address','subject':'Hi','body':'x'})
        with self.assertRaises(ValueError):self.w.preview_email({'subject':'','body':''})
        with patch.object(self.w.webbrowser,'open',return_value=True) as opened:
            self.w.draft_email({'to':'a@b.co','subject':'Hi & bye','body':'Line 1\nLine 2'})
        url=opened.call_args[0][0];self.assertTrue(url.startswith('mailto:a@b.co?subject=Hi%20%26%20bye&body=Line%201%0D%0ALine%202'))

    def test_pc_health_reports_drives(self):
        r=self.w.pc_health();self.assertTrue(r['drives']);self.assertIn('free_gb',r['drives'][0])

    def test_gating_and_approval_rule(self):
        t=base.tools;core=len(t.TOOLS);names=lambda q,c=6144:{x['function']['name'] for x in t.tools_for(q,c)}
        self.assertEqual(len(t.tools_for('Set a timer for pasta')),core)    # ordinary turns: budget unchanged
        for plain in ['How do I build a table in Python?','Tell me a joke.','What is my dog called?','Remember that my favourite colour is cyan.']:
            self.assertEqual(len(t.tools_for(plain)),core,plain)   # the release-check questions see exactly the 1.5 tools
        self.assertIn('organise_files',names('can you tidy my downloads'));self.assertIn('pc_health',names('why is my pc so slow'))
        self.assertIn('calculate',names('what is 17% of 230'));self.assertIn('create_file',names('turn this into a word document'))
        self.assertEqual(len(t.tools_for('hello',16384)),core+len(t.WORK_TOOLS))
        for name in t.CONFIRM:
            self.assertEqual(t.run(name,{'name':'x','kind':'text','content':'x','folder':'downloads','subject':'s','body':'b'},self.s)[0]['error'],'This needs the user to approve it first.')
        self.assertFalse((self.dir/'out').exists())

class ConfirmApiTests(unittest.TestCase):
    request=base.ApiTests.request
    setUpClass=classmethod(CompanionApiTests.setUpClass.__func__)
    tearDownClass=classmethod(CompanionApiTests.tearDownClass.__func__)
    stream=BrainApiTests.stream
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.out=Path(self.tmp.name)/'out'
        patcher=patch.dict(base.os.environ,{'CORTANA_OUTPUT_DIR':str(self.out)});patcher.start();self.addCleanup(patcher.stop)

    def test_file_is_created_only_after_approval_and_only_once(self):
        status,events=self.stream({'messages':[{'role':'user','content':'Please save a document of my plan'}]})
        self.assertEqual(status,200);ask=[e for e in events if e['type']=='confirm']
        self.assertEqual(len(ask),1);self.assertEqual(ask[0]['summary'],'Create Plan.docx in Documents\\Cortana')
        self.assertFalse(self.out.exists())   # nothing written while waiting
        self.assertIn('Approve',' '.join(e['text'] for e in events if e['type']=='sentence'))
        status,_,raw=self.request('POST','/api/confirm',{'id':ask[0]['id'],'approve':True});r=json.loads(raw)
        self.assertEqual(status,200);self.assertTrue(r['ok']);self.assertTrue((self.out/'Plan.docx').exists())
        self.assertIn('Plan.docx',r['say'])
        self.assertEqual(self.request('POST','/api/confirm',{'id':ask[0]['id'],'approve':True})[0],400)   # one use only

    def test_cancel_changes_nothing_and_guards(self):
        _,events=self.stream({'messages':[{'role':'user','content':'Please save a document of my plan'}]})
        pid=[e for e in events if e['type']=='confirm'][0]['id']
        r=json.loads(self.request('POST','/api/confirm',{'id':pid,'approve':False})[2]);self.assertIn('Cancelled',r['say'])
        self.assertFalse(self.out.exists())
        self.assertEqual(self.request('POST','/api/confirm',{'id':'made-up','approve':True})[0],400)
        self.assertEqual(self.request('POST','/api/confirm',{'id':pid,'approve':'yes'})[0],400)
        self.assertEqual(self.request('POST','/api/confirm',{'id':pid,'approve':True},{'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/api/confirm',{'id':pid,'approve':True},host='phone.example')[0],403)

    def test_held_action_expires(self):
        pid=self.rt.hold('create_file',{'name':'Old','kind':'text','content':'x'})
        self.rt.pending[pid]['at']-=self.rt.PENDING_SECONDS+1
        self.assertEqual(self.request('POST','/api/confirm',{'id':pid,'approve':True})[0],400);self.assertFalse(self.out.exists())

class PictureTests(unittest.TestCase):
    request=base.ApiTests.request
    setUpClass=classmethod(CompanionApiTests.setUpClass.__func__)
    tearDownClass=classmethod(CompanionApiTests.tearDownClass.__func__)
    stream=BrainApiTests.stream
    PNG=base.base64.b64encode(b'\x89PNG\r\n\x1a\n'+b'\0'*64).decode()

    def test_picture_goes_to_the_model_for_this_question_only(self):
        base.fake_ollama.CHAT_REQUESTS.clear()
        status,events=self.stream({'messages':[{'role':'user','content':'What is in this picture?'}],'images':[self.PNG]})
        self.assertEqual(status,200);msgs=base.fake_ollama.CHAT_REQUESTS[-1]['messages']
        self.assertEqual(msgs[-1]['images'],[self.PNG]);self.assertNotIn('images',msgs[0])
        saved=self.rt.store.recent_messages(2);self.assertNotIn(self.PNG,json.dumps(saved))   # never stored

    def test_pictures_are_checked(self):
        msg=[{'role':'user','content':'Look'}]
        for bad in [[self.PNG]*3,['not base64!'],[base.base64.b64encode(b'MZ executable').decode()],'x']:
            self.assertEqual(self.request('POST','/api/chat-stream',{'messages':msg,'images':bad})[0],400)
        self.assertEqual(self.request('POST','/api/chat-stream',{'messages':msg,'pad':'x'*70000})[0],400)   # only pictures may be big

class TimerGuardTests(unittest.TestCase):
    """D-036: a plainly requested timer is set in code, so a model that only *says* it set one can't fake it."""
    def test_timer_requests_are_parsed(self):
        t=base.runtime.timer_request
        self.assertEqual(t('Set a timer for 10 minutes for the pasta.'),{'minutes':10,'label':'pasta'})
        self.assertEqual(t('set a 10 minute timer'),{'minutes':10,'label':''})
        self.assertEqual(t('Timer for 90 seconds'),{'minutes':1.5,'label':''})
        self.assertEqual(t('start a timer for an hour and 15 minutes for my bread'),{'minutes':75,'label':'bread'})
        self.assertEqual(t('half an hour timer please'),{'minutes':30,'label':''})
        for no in ['How long is left on my timer?','Cancel the pasta timer','Set a timer','Remind me in 10 minutes','set a timer for 30 hours',
                   'add 5 minutes to the timer']:
            self.assertIsNone(t(no),no)

    def test_model_that_never_calls_the_tool_still_sets_exactly_one_timer(self):
        rt=base.runtime.Runtime();rt.store.close();rt.store=base.store.Store(':memory:');rt.ai_ready=True
        self.addCleanup(rt.store.close)
        def lazy_model(payload):   # the 9B failure seen in CI: claims success, calls nothing
            self.assertNotIn('set_timer',[t['function']['name'] for t in payload.get('tools',[])])
            yield {'message':{'content':'Got it, Chief. Setting a 10-minute timer for the pasta.'}}
        with patch.object(rt,'ollama_stream',lazy_model):
            events=list(rt.chat_stream([{'role':'user','content':'Set a timer for 10 minutes for the pasta.'}]))
        self.assertIn({'type':'tool','name':'set_timer','label':'SETTING TIMER'},events)
        timers=[i for i in rt.store.items() if i['kind']=='timer'];self.assertEqual(len(timers),1)
        self.assertEqual(timers[0]['text'],'pasta');self.assertAlmostEqual(timers[0]['due']-time.time(),600,delta=5)

class ActionGuardTests(unittest.TestCase):
    """D-036 continued: clear reminders are set in code, and an action she only *said* she did gets one retry."""
    def test_reminder_requests_are_parsed(self):
        r=base.runtime.reminder_request
        self.assertEqual(r('Remind me to call mum at 6pm.'),{'text':'call mum','at':'18:00'})
        self.assertEqual(r('remind me in 20 minutes to check the oven'),{'text':'check the oven','in_minutes':20})
        self.assertEqual(r('Remind me at 18:30 to take the bins out'),{'text':'take the bins out','at':'18:30'})
        self.assertEqual(r('remind me to stretch in an hour'),{'text':'stretch','in_minutes':60})
        self.assertEqual(r('Remind me about the dentist at 12am'),{'text':'the dentist','at':'00:00'})
        tomorrow=r('remind me to pay rent tomorrow at 9am');self.assertEqual(tomorrow['text'],'pay rent');self.assertTrue(tomorrow['at'].endswith(' 09:00'))
        for no in ['Remind me to call mum at 6','remind me on Friday at 3pm to call','What did you remind me about?','Cancel the reminder to call mum',
                   'remind me at 6pm','Set a reminder']:
            self.assertIsNone(r(no),no)

    def make_runtime(self):
        rt=base.runtime.Runtime();rt.store.close();rt.store=base.store.Store(':memory:');rt.ai_ready=True;self.addCleanup(rt.store.close)
        return rt

    def test_clear_reminder_is_set_once_even_if_the_model_only_talks(self):
        rt=self.make_runtime()
        def talker(payload):
            self.assertNotIn('set_reminder',[t['function']['name'] for t in payload.get('tools',[])])
            yield {'message':{'content':"Got it! I'll set a reminder for you to call Mum at 6pm."}}
        with patch.object(rt,'ollama_stream',talker):list(rt.chat_stream([{'role':'user','content':'Remind me to call mum at 6pm.'}]))
        rem=[i for i in rt.store.items() if i['kind']=='reminder'];self.assertEqual(len(rem),1);self.assertEqual(rem[0]['text'],'call mum')

    def test_claimed_but_not_done_gets_one_retry(self):
        rt=self.make_runtime();calls=[]
        def model(payload):
            calls.append([m['content'] for m in payload['messages'] if m['role']=='user'][-1])
            if len(calls)==1:yield {'message':{'content':"Got it, I'll remember that."}}             # claims, calls nothing
            elif len(calls)==2:yield {'message':{'content':'','tool_calls':[{'function':{'name':'remember','arguments':{'fact':"The user's favourite colour is cyan"}}}]}}
            else:yield {'message':{'content':'Done.'}}
        with patch.object(rt,'ollama_stream',model):events=list(rt.chat_stream([{'role':'user','content':'Remember that my favourite colour is cyan.'}]))
        self.assertEqual(len(calls),3);self.assertIn('App check',calls[1])
        self.assertEqual([f['text'] for f in rt.store.facts()],["The user's favourite colour is cyan"])
        self.assertIn({'type':'refresh','what':'memory'},events)

    def test_questions_and_stubborn_models_are_not_retried_forever(self):
        rt=self.make_runtime();calls=[]
        def model(payload):calls.append(1);yield {'message':{'content':'Your dog is called Max.'}}
        with patch.object(rt,'ollama_stream',model):list(rt.chat_stream([{'role':'user','content':"Do you remember my dog's name?"}]))
        self.assertEqual(len(calls),1)   # a question, not a request: no retry
        calls.clear()
        with patch.object(rt,'ollama_stream',model):list(rt.chat_stream([{'role':'user','content':'Add milk to my list'}]))
        self.assertEqual(len(calls),2)   # exactly one retry, then she stops
