"""Companion release regression checks; no network or native voice required."""
import json
import sqlite3
import tarfile
import tempfile
import threading
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
        for path in ['/neural.py','/lips.py','/companion.py','/voice-profile/reference.wav','/voice-profile/voice_profile.json']:
            self.assertEqual(self.request('GET',path)[0],404)

    def test_negative_keyword_burst_never_runs_whisper(self):
        with patch.object(self.rt.neural,'detect',return_value=False),patch.object(self.rt,'transcribe') as transcribe:
            data=json.loads(self.request('POST','/api/transcribe',{'wake':True,'audio':base.base64.b64encode(b'placeholder').decode()})[2])
            self.assertFalse(data['wake']);transcribe.assert_not_called()

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
        with patch.object(companion,'notify',side_effect=lambda text:calls.append(text) or False):
            rt.notification_tick(now=0,wait=True);self.assertEqual(len(calls),1)
            rt.notification_tick(now=30,wait=True);self.assertEqual(len(calls),1)    # not every 2 seconds
            rt.notification_tick(now=61,wait=True);self.assertEqual(len(calls),2)
            rt.notification_tick(now=150,wait=True);self.assertEqual(len(calls),2)   # second wait is 2 minutes
            rt.notification_tick(now=200,wait=True);self.assertEqual(len(calls),3)
            rt.notification_tick(now=10**6,wait=True);self.assertEqual(len(calls),3)  # given up after 3 tries
        self.assertEqual(rt.store.pending_notifications(),[]);self.assertEqual(rt.store.due_alerts()[0]['id'],tid)   # in-app alert still fires

    def test_balloon_does_not_block_the_loop(self):
        rt=self.make_runtime();rt.store.add_item('timer','Tea',time.time()-5);release=threading.Event()
        def slow(text):release.wait(5);return True
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
