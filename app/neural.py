"""CPU ZipVoice reference speech and a small local keyword spotter."""
import io
import json
import os
import threading
import wave
from runtime import DATA,RESOURCES,download,extract

BASE='https://github.com/k2-fsa/sherpa-onnx/releases/download/'
ZIP_NAME='sherpa-onnx-zipvoice-distill-int8-zh-en-emilia'
KWS_NAME='sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01'
HASHES={
 ZIP_NAME+'.tar.bz2':'77219c8b40f4ee8d73a7f902305ff6c1128ef9b54461c41b4ca6ed890b6c2803',
 'vocos_24khz.onnx':'bcb3b970e384161c4d634f0bb9e999ff1c471b34c9bc0b1049a5014065ed3cc0',
 'lexicon-en-us.txt':'8b67ae549a465eee78f92ecb74644ad90c3c58ce65f19c68baf85878a10ef73a',
 KWS_NAME+'.tar.bz2':'f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a'}
# Half the logical cores (a 12-core/24-thread CPU gets 8), never fewer than 2 or more than 8.
THREADS=max(2,min(8,(os.cpu_count() or 4)//2))
WARM_UP='Systems online.'

def pcm(audio):
    import numpy as np
    with wave.open(io.BytesIO(audio)) as w:
        if w.getsampwidth()!=2 or w.getnchannels()!=1 or not 8000<=w.getframerate()<=48000 or w.getnframes()>w.getframerate()*31:raise ValueError('Use mono 16-bit WAV audio.')
        return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2').astype('float32')/32768,w.getframerate()

class Neural:
    def __init__(self,report):
        self.report=report;self.tts=self.kws=None
        self.tts_lock=threading.Lock();self.kws_lock=threading.Lock()
        self.wake_status='Keyword detector not prepared.'

    def asset(self,name,group):
        target=DATA/'neural'/name
        download(BASE+group+'/'+name,target,self.report,HASHES[name]);return target

    def unpacked(self,name,group):
        """Download and unpack an archive once; later launches reuse the folder (a marker proves the unpack finished)."""
        folder=DATA/'neural'/name;marker=folder/'.unpacked'
        if not marker.exists():
            extract(self.asset(name+'.tar.bz2',group),DATA/'neural');marker.write_text(HASHES[name+'.tar.bz2'])
        return folder

    def prepare_voice(self):
        import sherpa_onnx as s
        if self.tts:return
        m=self.unpacked(ZIP_NAME,'tts-models')
        vocoder=self.asset('vocos_24khz.onnx','vocoder-models');english=self.asset('lexicon-en-us.txt','tts-models')
        config=s.OfflineTtsConfig(model=s.OfflineTtsModelConfig(zipvoice=s.OfflineTtsZipvoiceModelConfig(
            tokens=str(m/'tokens.txt'),encoder=str(m/'encoder.int8.onnx'),decoder=str(m/'decoder.int8.onnx'),
            vocoder=str(vocoder),lexicon=str(m/'lexicon.txt')+','+str(english)),num_threads=THREADS,provider='cpu'))
        if not config.validate():raise RuntimeError('Reference voice files are incomplete.')
        self.tts=s.OfflineTts(config);profile=RESOURCES/'voice-profile'
        self.profile=json.loads((profile/'voice_profile.json').read_text())
        self.reference,self.reference_rate=pcm((profile/'reference.wav').read_bytes())

    def warm_up(self):
        """The first generation after loading is several times slower; pay that cost at startup, not on the first reply."""
        import sherpa_onnx as s
        with self.tts_lock:
            self.prepare_voice()
            config=s.GenerationConfig();config.reference_audio=self.reference
            config.reference_sample_rate=self.reference_rate;config.reference_text=self.profile['reference_text'];config.num_steps=8
            self.tts.generate(WARM_UP,config)

    def speak(self,text,rate,jobs):
        import numpy as np
        import sherpa_onnx as s
        with self.tts_lock:
            jobs.check();self.prepare_voice();jobs.check()
            config=s.GenerationConfig();config.reference_audio=self.reference
            config.reference_sample_rate=self.reference_rate;config.reference_text=self.profile['reference_text']
            config.num_steps=8;config.speed={-1:.87,0:1.,1:1.13}.get(rate,1.)
            entry=getattr(jobs.local,'entry',None)
            result=self.tts.generate(text,config,callback=lambda samples,progress:0 if entry and entry['event'].is_set() else 1)
            jobs.check()
            if not len(result.samples):raise RuntimeError('Reference voice returned no audio.')
            output=io.BytesIO()
            with wave.open(output,'wb') as w:
                w.setnchannels(1);w.setsampwidth(2);w.setframerate(result.sample_rate)
                w.writeframes((np.clip(result.samples,-1,1)*32767).astype('<i2').tobytes())
            return output.getvalue()

    def prepare_wake(self):
        import sherpa_onnx as s
        with self.kws_lock:
            if self.kws:return
            m=self.unpacked(KWS_NAME,'kws-models')
            keywords=DATA/'neural'/'cortana-keywords.txt'
            keywords.write_text('▁HE Y ▁C OR T AN A :2.0 #0.35 @HEY_CORTANA\n▁C OR T AN A :1.5 #0.45 @CORTANA\n',encoding='utf8')
            self.kws=s.KeywordSpotter(tokens=str(m/'tokens.txt'),encoder=str(next(m.glob('encoder*.int8.onnx'))),
              decoder=str(next(m.glob('decoder*.int8.onnx'))),joiner=str(next(m.glob('joiner*.int8.onnx'))),
              keywords_file=str(keywords),num_threads=2,keywords_threshold=.35)
            self.wake_status='Small local Hey Cortana detector ready.'

    def detect(self,audio):
        import numpy as np
        if self.kws is None:return None
        samples,rate=pcm(audio)
        with self.kws_lock:
            stream=self.kws.create_stream()
            stream.accept_waveform(rate,np.concatenate([samples,np.zeros(int(rate*.5),dtype='float32')]))
            stream.input_finished()
            while self.kws.is_ready(stream):
                self.kws.decode_stream(stream)
                if self.kws.get_result(stream):return True
        return False
