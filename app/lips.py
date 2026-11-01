"""CPU audio-aligned mouth poses via Rhubarb's phonetic recognizer."""
import json
import os
import subprocess
import tempfile
from runtime import DATA,HIDDEN,download,extract
RELEASE='https://github.com/DanielSWolf/rhubarb-lip-sync/releases/download/v1.14.0/'
CHECKSUM={'Windows':'62fa416a8d5e382a3828ee4bef358ce520d0b4cabdeaea75a7ac266d098d1fe3','Linux':'a9a9074862cff47b2d59b8bf399a678a3b0b74f9452ad6ad94cb292913dd8667'}
VISEMES={'A':21,'B':19,'C':4,'D':2,'E':3,'F':8,'G':18,'H':14,'X':0}

def cues(result):
    output=[]
    for c in result.get('mouthCues',[]):
        start,end=float(c['start']),float(c['end'])
        if start<0 or end<start or c['value'] not in VISEMES:raise ValueError('Invalid mouth alignment.')
        output.append({'time':start,'duration':end-start,'id':VISEMES[c['value']]})
    return output

class Lips:
    def __init__(self):self.exe=None;self.status='Audio alignment not prepared.'

    def prepare(self,report):
        platform='Windows' if os.name=='nt' else 'Linux';root=DATA/'rhubarb'
        try:
            name='rhubarb.exe' if os.name=='nt' else 'rhubarb'
            self.exe=next(root.rglob(name),None) if root.exists() else None   # already installed: skip re-hashing and re-unpacking the 87 MB zip
            if self.exe:
                self.status='Local audio alignment ready.';return
            target=DATA/'rhubarb.zip'
            download(RELEASE+f'Rhubarb-Lip-Sync-1.14.0-{platform}.zip',target,report,CHECKSUM[platform])
            extract(target,root);self.exe=next(root.rglob(name))
            if os.name!='nt':self.exe.chmod(0o755)
            self.status='Local audio alignment ready.'
        except Exception:self.exe=None;self.status='Audio alignment unavailable; using audio envelope.'

    def align(self,audio,jobs):
        if not self.exe:return []
        jobs.check()
        try:
            with tempfile.TemporaryDirectory(dir=DATA) as tmp:
                path=os.path.join(tmp,'speech.wav')
                with open(path,'wb') as f:f.write(audio)
                result=subprocess.run([str(self.exe),'-f','json','-r','phonetic','--threads','2',path],capture_output=True,timeout=20,creationflags=HIDDEN)
                jobs.check()
                return cues(json.loads(result.stdout)) if result.returncode==0 else []
        except (subprocess.TimeoutExpired,ValueError,OSError):return []
