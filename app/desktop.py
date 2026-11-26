"""Native desktop client. All Tk operations stay on the GUI thread."""
import base64
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import uuid

BG='#071426'
PANEL='#10243b'
FG='#e1f4ff'
ACCENT='#77d9ff'


class Desktop:
    def __init__(self, root, runtime):
        self.root, self.runtime = root, runtime
        self.events = queue.Queue()
        self.messages = []
        self.job = None
        self.task = None
        self.pending = None
        self.generation = 0
        root.title('Cortana | Desktop')
        root.geometry('1160x760')
        root.minsize(820, 560)
        root.configure(bg=BG)
        style=ttk.Style(root)
        style.theme_use('clam')
        style.configure('TButton', background=PANEL, foreground=FG, padding=8)
        style.configure('TCheckbutton', background=BG, foreground=FG)
        style.configure('TCombobox', padding=5)
        header=tk.Frame(root,bg=BG)
        header.pack(fill='x',padx=24,pady=16)
        tk.Label(header,text='C O R T A N A',font=('Segoe UI',23,'bold'),fg=ACCENT,bg=BG).pack(side='left')
        self.status=tk.StringVar(value='Starting local assistant…')
        tk.Label(header,textvariable=self.status,fg=FG,bg=BG,wraplength=480).pack(side='right')
        body=tk.Frame(root,bg=BG)
        body.pack(fill='both',expand=True,padx=24,pady=(0,12))
        side=tk.Frame(body,bg=PANEL,width=260)
        side.pack(side='left',fill='y',padx=(0,16))
        side.pack_propagate(False)
        canvas=tk.Canvas(side,width=240,height=250,bg=PANEL,highlightthickness=0)
        canvas.pack(pady=12)
        for radius in (105,88,70,48):
            canvas.create_oval(120-radius,120-radius,120+radius,120+radius,outline='#235c85',width=2)
        canvas.create_oval(78,78,162,162,outline=ACCENT,width=6)
        canvas.create_text(120,235,text='LOCAL INTELLIGENCE',fill=ACCENT,font=('Segoe UI',10,'bold'))
        self.control=tk.StringVar(value='You have control')
        tk.Label(side,textvariable=self.control,bg=PANEL,fg=FG,wraplength=230).pack(pady=8)
        for text,command in [('Stop / Escape',self.stop),('AI model',self.models),('Settings',self.settings),('Phone pairing',self.pair),('Web interface (optional)',self.web)]:
            ttk.Button(side,text=text,command=command).pack(fill='x',padx=16,pady=4)
        chat=tk.Frame(body,bg=PANEL)
        chat.pack(side='left',fill='both',expand=True)
        self.transcript=tk.Text(chat,bg=PANEL,fg=FG,insertbackground=FG,wrap='word',relief='flat',font=('Segoe UI',12),padx=18,pady=16,state='disabled')
        self.transcript.pack(fill='both',expand=True)
        self.transcript.tag_configure('user',foreground=ACCENT,font=('Segoe UI',11,'bold'))
        self.transcript.tag_configure('assistant',foreground='#9bbcff',font=('Segoe UI',11,'bold'))
        self.transcript.tag_configure('notice',foreground='#ffcc88')
        composer=tk.Frame(chat,bg=BG)
        composer.pack(fill='x',padx=10,pady=10)
        self.entry=tk.Text(composer,height=3,bg='#19324e',fg=FG,insertbackground=FG,relief='flat',wrap='word',font=('Segoe UI',12))
        self.entry.pack(side='left',fill='x',expand=True)
        self.entry.bind('<Return>',self.enter)
        self.send_button=ttk.Button(composer,text='Send',command=self.send)
        self.send_button.pack(side='right',padx=8)
        options=tk.Frame(chat,bg=BG)
        options.pack(fill='x',padx=10,pady=(0,8))
        self.think=tk.BooleanVar()
        self.speak=tk.BooleanVar(value=True)
        ttk.Checkbutton(options,text='Deep thinking',variable=self.think).pack(side='left')
        ttk.Checkbutton(options,text='Speak replies',variable=self.speak).pack(side='left',padx=12)
        self.mic=ttk.Button(options,text='Record 5s',command=self.record)
        self.mic.pack(side='right')
        self.approval=tk.Frame(chat,bg='#243953')
        self.approval_text=tk.Label(self.approval,bg='#243953',fg=FG,wraplength=500,justify='left')
        self.approval_text.pack(fill='x',padx=10,pady=8)
        ttk.Button(self.approval,text='Approve',command=lambda:self.confirm(True)).pack(side='left',padx=10,pady=8)
        ttk.Button(self.approval,text='Reject',command=lambda:self.confirm(False)).pack(side='left',padx=10,pady=8)
        root.bind('<Escape>',lambda e:self.stop())
        for row in runtime.store.recent_messages(40):
            if row['role'] in ('user','assistant'):
                self.messages.append({'role':row['role'],'content':row['content']})
                self.append(row['role'],row['content'])
        self.entry.focus_set()
        self.tick()

    def append(self,role,text):
        self.transcript.configure(state='normal')
        self.transcript.insert('end',('\n'+role.upper()+'\n'),role)
        self.transcript.insert('end',str(text)+'\n')
        self.transcript.configure(state='disabled')
        self.transcript.see('end')

    def enter(self,event):
        if event.state & 1:return None
        self.send()
        return 'break'

    def worker(self,fn):
        threading.Thread(target=fn,daemon=True).start()

    def send(self):
        text=self.entry.get('1.0','end').strip()
        if not text or self.job or self.task or self.pending:return
        self.entry.delete('1.0','end')
        self.messages.append({'role':'user','content':text})
        self.append('user',text)
        key='desktop_'+uuid.uuid4().hex
        self.job=key
        generation=self.generation
        messages=list(self.messages[-20:])
        think,speak=self.think.get(),self.speak.get()
        self.send_button.configure(state='disabled')
        def run():
            try:
                with self.runtime.jobs.scope(key):
                    for event in self.runtime.chat_stream(messages,think,local=True):
                        self.events.put((generation,'event',event))
                if speak:
                    # Speak the final reply using the same local voice backend.
                    if event.get('type')=='done' and event.get('reply'):
                        import winsound
                        with self.runtime.jobs.scope(key+'_voice'):
                            result=self.runtime.voice.speak(event['reply'],0)
                            if result.get('audio'):
                                winsound.PlaySound(base64.b64decode(result['audio']),winsound.SND_MEMORY)
            except Exception as exc:self.events.put((generation,'error',str(exc)))
            finally:self.events.put((generation,'finished',key))
        self.worker(run)

    def stop(self):
        self.generation+=1
        if self.job:
            self.runtime.jobs.cancel(self.job)
            self.runtime.jobs.cancel(self.job+'_voice')
        if self.task:self.runtime.jobs.cancel(self.task)
        if self.pending:
            pid=self.pending
            self.pending=None
            self.worker(lambda:self.runtime.confirm(pid,False,True))
        self.approval.pack_forget()
        self.job=self.task=None
        self.send_button.configure(state='normal')
        self.append('notice','Stopped.')

    def confirm(self,approved):
        if not self.pending:return
        pid=self.pending
        self.pending=None
        self.approval.pack_forget()
        self.task='task_'+pid
        generation=self.generation
        def run():
            try:
                result=self.runtime.confirm(pid,approved,True)
                self.events.put((generation,'notice',result.get('say','Finished')))
            except Exception as exc:self.events.put((generation,'error',str(exc)))
            finally:self.events.put((generation,'task_finished',None))
        self.worker(run)

    def tick(self):
        self.status.set(str(self.runtime.status))
        self.control.set('Cortana has control — press Escape' if self.runtime.control_visible else 'You have control')
        try:
            while True:
                generation,kind,data=self.events.get_nowait()
                if generation!=self.generation:continue
                if kind=='event':
                    event=data
                    if event['type']=='done':
                        reply=event.get('reply','')
                        self.messages.append({'role':'assistant','content':event.get('raw') or reply})
                        self.append('assistant',reply)
                    elif event['type']=='screen':self.append('assistant',event.get('markdown',''))
                    elif event['type']=='confirm':
                        self.pending=event['id']
                        self.approval_text.configure(text=event.get('summary','')+'\n'+event.get('detail',''))
                        self.approval.pack(fill='x',padx=10,pady=6)
                elif kind=='finished':
                    self.job=None
                    self.send_button.configure(state='normal')
                elif kind=='task_finished':self.task=None
                elif kind=='models':self.show_models(data)
                elif kind=='recorded':
                    self.mic.configure(state='normal')
                    self.entry.insert('end',data)
                elif kind=='record_error':
                    self.mic.configure(state='normal')
                    self.append('notice',data)
                else:self.append('notice',data)
        except queue.Empty:pass
        self.root.after(100,self.tick)

    def models(self):
        generation=self.generation
        def run():
            try:self.events.put((generation,'models',self.runtime.models_info()))
            except Exception as exc:self.events.put((generation,'error',str(exc)))
        self.worker(run)

    def show_models(self,info):
        win=tk.Toplevel(self.root)
        win.title('Choose local AI')
        for model in info['models']:
            tag=model['tag']
            enabled=model.get('selectable',False)
            installed=model.get('installed',False)
            def choose(tag=tag,installed=installed):
                generation=self.generation
                def run():
                    try:
                        (self.runtime.use_model if installed else self.runtime.start_pull)(tag)
                    except Exception as exc:self.events.put((generation,'error',str(exc)))
                self.worker(run)
                win.destroy()
            ttk.Button(win,text=tag+(' — Use' if installed else ' — Download'),command=choose,state='normal' if enabled else 'disabled').pack(fill='x',padx=14,pady=4)

    def settings(self):
        win=tk.Toplevel(self.root)
        win.title('Cortana settings')
        for key,label,default in [('full_access','Full PC access (approval required)',False),('tools_enabled','Enable assistant tools',True),('native_notifications','Windows notifications',True)]:
            var=tk.BooleanVar(win,value=self.runtime.store.get(key,default))
            ttk.Checkbutton(win,text=label,variable=var,command=lambda k=key,v=var:self.runtime.store.set(k,v.get())).pack(anchor='w',padx=14,pady=8)

    def pair(self):
        from runtime import qr_matrix
        if not self.runtime.phone_url:
            messagebox.showinfo('Phone pairing','Phone connection is not ready yet.',parent=self.root)
            return
        win=tk.Toplevel(self.root)
        win.title('Private phone pairing')
        matrix=qr_matrix(self.runtime.phone_url)
        scale=max(1,280//len(matrix))
        size=scale*len(matrix)
        image=tk.PhotoImage(width=size,height=size)
        image.put('white',to=(0,0,size,size))
        for y,row in enumerate(matrix):
            for x,on in enumerate(row):
                if on:image.put('black',to=(x*scale,y*scale,(x+1)*scale,(y+1)*scale))
        label=tk.Label(win,image=image)
        label.image=image
        label.pack(padx=16,pady=16)
        tk.Label(win,text='Scan with your phone. Keep this code private.').pack(pady=10)

    def web(self):
        import webbrowser
        webbrowser.open(self.runtime.local_url)

    def record(self):
        self.mic.configure(state='disabled')
        generation=self.generation
        def run():
            try:
                import sounddevice as sd
                import io,wave
                audio=sd.rec(80000,samplerate=16000,channels=1,dtype='int16')
                sd.wait()
                out=io.BytesIO()
                with wave.open(out,'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(audio.tobytes())
                text=self.runtime.transcribe(out.getvalue())
                self.events.put((generation,'recorded',text))
            except Exception as exc:self.events.put((generation,'record_error',str(exc)))
        self.worker(run)
