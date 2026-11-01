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
        with patch.object(self.rt,'ollama_stream',chunks):
            events=self.request('POST','/api/chat-stream',{'messages':[{'role':'user','content':'Add a task'}],'request_id':'stopped_tool'})[2].decode()
        self.assertIn('error',events);self.assertFalse(any(i['text']=='Should not exist' for i in self.rt.store.items()))
