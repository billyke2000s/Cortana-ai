"""One-file entry point: local assistant, speech, browser and phone QR."""
import sys,os,threading,queue,time,json,webbrowser,traceback
from pathlib import Path
from runtime import Runtime,DATA,qr_matrix
from server import AppServer
def crash_logging():
    """The windowed exe has no console, so a crash left no trace. Python errors in any thread and native crashes
    (faulthandler) now go to DATA/crash.log, newest at the end."""
    import faulthandler
    DATA.mkdir(parents=True,exist_ok=True)
    log=open(DATA/'crash.log','a',encoding='utf8',buffering=1)
    log.write(f"--- Cortana started {time.strftime('%Y-%m-%d %H:%M:%S')} (pid {os.getpid()})\n")
    faulthandler.enable(log,all_threads=True)
    def write(kind,exc_type,exc,tb):
        log.write(f"{time.strftime('%H:%M:%S')} {kind}:\n"+''.join(traceback.format_exception(exc_type,exc,tb))+'\n')
    sys.excepthook=lambda t,e,tb:write('unhandled error',t,e,tb)
    threading.excepthook=lambda a:write(f'error in thread {a.thread.name if a.thread else "?"}',a.exc_type,a.exc_value,a.exc_traceback)
    return log,write

def clean_old_unpacks():
    """Each run of the one-file exe unpacks into %TEMP%\\_MEIxxxx and deletes it on exit; if a helper still held a file,
    Windows refused ('Failed to remove temporary directory') and the copy stayed behind. Remove earlier Cortana copies
    (identified by Cortana's own files) so they don't pile up. Other apps' _MEI folders are never touched."""
    import shutil,tempfile
    mine=getattr(sys,'_MEIPASS',None)
    if not mine:return
    for d in Path(tempfile.gettempdir()).glob('_MEI*'):
        try:
            if str(d)!=mine and (d/'voice-profile'/'voice_profile.json').exists() and (d/'assets'/'cortana.glb').exists() and time.time()-d.stat().st_mtime>600:
                shutil.rmtree(d,ignore_errors=True)
        except OSError:pass

def main():
    import argparse
    if sys.stdout is None:sys.stdout=open(os.devnull,'w')   # the windowed exe has no console; --headless prints status lines
    if sys.stderr is None:sys.stderr=open(os.devnull,'w')
    crash_log,log_error=crash_logging()
    threading.Thread(target=clean_old_unpacks,daemon=True).start()
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0);parser.add_argument('--headless',action='store_true');parser.add_argument('--no-tunnel',action='store_true');parser.add_argument('--no-open',action='store_true');args=parser.parse_args()
    events=queue.Queue();runtime=Runtime(events.put)
    runtime.ask_model=not args.headless   # first launch: let the user pick the model (headless/tests keep the automatic pick)
    # Tailscale needs the same local port every launch so the phone address keeps working.
    port=args.port or (int(runtime.store.get('port',47817)) if runtime.store.get('phone_access','cloudflare')=='tailscale' else 0)
    server=AppServer(('127.0.0.1',port),runtime)
    runtime.local_url=f'http://127.0.0.1:{server.server_address[1]}'
    threading.Thread(target=server.serve_forever,daemon=True).start()
    (DATA/'launch-state.json').write_text(json.dumps({'url':runtime.local_url,'pid':os.getpid()}))
    def startup():
        try:
            threading.Thread(target=runtime.voice.prepare,daemon=True).start()   # voice downloads/warms up alongside the AI
            def auxiliaries():
                runtime.lips.prepare(runtime.update)
            threading.Thread(target=auxiliaries,daemon=True).start()
            runtime.ensure_ai()
            if runtime.closing.is_set():return
            runtime.ensure_stt()
            if runtime.closing.is_set():return
            if not args.no_tunnel:runtime.start_tunnel()
            else:runtime.update('Ready on this PC. Phone connection disabled for this run.')
        except Exception as e:
            runtime.error=str(e);runtime.update('Setup needs attention: '+str(e));(DATA/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
    threading.Thread(target=startup,daemon=True).start()
    threading.Thread(target=runtime.background_loop,daemon=True).start()   # calendar reminders
    if not args.no_open:webbrowser.open(runtime.local_url)
    if args.headless:
        print('CORTANA_LOCAL_URL='+runtime.local_url,flush=True)
        try:
            while True:
                try:print(events.get(timeout=1),flush=True)
                except queue.Empty:pass
        except KeyboardInterrupt:pass
        finally:runtime.close();server.shutdown();server.server_close()
        return
    import tkinter as tk
    window=tk.Tk();window.report_callback_exception=lambda t,e,tb:log_error('error in the launcher window',t,e,tb);window.title('Cortana');window.geometry('460x730');window.minsize(400,680);window.configure(bg='#041228')
    tk.Label(window,text='CORTANA',font=('Segoe UI',27,'bold'),fg='#9fe2ff',bg='#041228').pack(pady=(22,3))
    tk.Label(window,text='YOUR PC IS THE CORE. YOUR PHONE IS THE DISPLAY.',font=('Segoe UI',9),fg='#a9c6e6',bg='#041228').pack()
    status=tk.StringVar(value='Starting your assistant...')
    tk.Label(window,textvariable=status,wraplength=390,font=('Segoe UI',11),fg='#e8f4ff',bg='#041228',height=3).pack(padx=20,pady=10)
    canvas=tk.Canvas(window,width=280,height=280,bg='#082044',highlightthickness=0);canvas.pack(pady=8);canvas.create_text(140,140,text='Preparing your phone QR...',fill='#a9c6e6',font=('Segoe UI',12),width=230)
    tk.Label(window,text='Scan with your phone camera.\nKeep this app open while using Cortana.',font=('Segoe UI',11),fg='#d6eaff',bg='#041228').pack(pady=10)
    tk.Button(window,text='Open Cortana on this PC',command=lambda:webbrowser.open(runtime.local_url),font=('Segoe UI',11),bg='#16436c',fg='white',relief='flat',padx=20,pady=9).pack(pady=5)
    tk.Label(window,text='Phone access uses a private HTTPS link (Cloudflare or Tailscale).\nThe QR code grants access: keep it private.\nAI, speech and memory stay on this PC.',font=('Segoe UI',9),fg='#96b2cf',bg='#041228').pack(pady=12)
    rendered=None
    def poll():
        nonlocal rendered
        try:
            while True:status.set(events.get_nowait())
        except queue.Empty:pass
        if runtime.phone_url and runtime.phone_url!=rendered:
            rendered=runtime.phone_url;matrix=qr_matrix(rendered);n=len(matrix);scale=max(1,260//n);size=n*scale
            image=tk.PhotoImage(width=size,height=size);image.put('white',to=(0,0,size,size))
            for y,row in enumerate(matrix):
                for x,on in enumerate(row):
                    if on:image.put('#041228',to=(x*scale,y*scale,(x+1)*scale,(y+1)*scale))
            canvas.delete('all');canvas.create_image(140,140,image=image);canvas.qr_image=image
        if not runtime.phone_url and rendered:
            rendered=None;canvas.delete('all');canvas.create_text(140,140,text='Phone disconnected.\nRestart Cortana to reconnect.',fill='#a9c6e6',width=230)
        window.after(250,poll)
    def close():window.destroy();runtime.close();server.shutdown();server.server_close()
    window.protocol('WM_DELETE_WINDOW',close);poll();window.mainloop()
if __name__=='__main__':
    try:main()
    except Exception:
        DATA.mkdir(parents=True,exist_ok=True);(DATA/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
        try:
            from tkinter import messagebox
            messagebox.showerror('Cortana could not start','See startup-error.log in '+str(DATA))
        except Exception:pass
