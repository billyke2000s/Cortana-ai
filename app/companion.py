"""Local request cancellation, timing measurements and Windows reminders."""
import contextlib
import os
import re
import socket
import subprocess
import threading
import time

class Cancelled(RuntimeError):
    pass

class Jobs:
    def __init__(self):
        self.lock=threading.Lock();self.entries={};self.local=threading.local();self.metrics={}

    @staticmethod
    def key(value):
        if value is None:return None
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value):raise ValueError('Invalid request ID.')
        return value

    def entry(self,key):
        with self.lock:
            now=time.monotonic()
            self.entries={k:v for k,v in self.entries.items() if now-v['at']<3600}
            if key not in self.entries:
                if len(self.entries)>=1000:raise RuntimeError('Too many requests. Try again shortly.')
                self.entries[key]={'event':threading.Event(),'at':now,'sockets':set()}
            return self.entries[key]

    @contextlib.contextmanager
    def scope(self,key=None):
        key=self.key(key);old=getattr(self.local,'entry',None)
        self.local.entry=self.entry(key) if key else None
        try:
            self.check();yield
        finally:self.local.entry=old

    def check(self):
        entry=getattr(self.local,'entry',None)
        if entry and entry['event'].is_set():raise Cancelled('Request stopped.')

    def watch(self,response):
        entry=getattr(self.local,'entry',None)
        try:sock=response.fp.raw._sock
        except AttributeError:return
        if entry:
            with self.lock:entry['sockets'].add(sock)
            self.check()

    def cancel(self,key):
        entry=self.entry(self.key(key));entry['event'].set()
        with self.lock:sockets=list(entry['sockets'])
        for sock in sockets:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass

    def measure(self,name,started):
        with self.lock:self.metrics[name]=round((time.perf_counter()-started)*1000)

    def snapshot(self):
        with self.lock:return dict(self.metrics)

def notify(text,title='Cortana reminder'):
    if os.name!='nt':return False
    from runtime import HIDDEN
    # Input is data on stdin, never interpolated into PowerShell source.
    script='''[Console]::InputEncoding = New-Object System.Text.UTF8Encoding
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.Visible = $true
$n.BalloonTipTitle = [Environment]::GetEnvironmentVariable('CORTANA_TITLE')
$n.BalloonTipText = [Console]::In.ReadToEnd()
$n.ShowBalloonTip(8000)
Start-Sleep -Seconds 9
$n.Dispose()'''
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],input=str(text)[:200].encode('utf8'),capture_output=True,timeout=15,creationflags=HIDDEN,env={**os.environ,'CORTANA_TITLE':str(title)[:60]})
    return p.returncode==0
