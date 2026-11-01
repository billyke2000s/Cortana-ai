"""Bounded file operations and generated deliverables inside owner-approved folders."""
import csv
import hashlib
import io
import json
import math
import os
import shutil
import statistics
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from xml.sax.saxutils import escape
from runtime import DATA, HIDDEN

MAX_BYTES=12*1024*1024
TEXT_TYPES={'.txt','.md','.csv','.json','.py','.js','.html','.css','.xml','.yaml','.yml','.toml','.log','.svg'}

class Workspace:
    def __init__(self,runtime):
        self.runtime=runtime;self.store=runtime.store
        self.home=DATA/'workspace';self.home.mkdir(parents=True,exist_ok=True)
        self.journal=DATA/'file-history';self.journal.mkdir(exist_ok=True)

    def roots(self):
        return {'Workspace':self.home,**{r['name']:Path(r['path']) for r in self.store.get('work_roots',[])}}

    def path(self,value='',existing=False):
        value=str(value or self.store.get('active_file','')).strip()
        roots=self.roots()
        if not value:return self.home
        if ':' in value and value.split(':',1)[0] in roots:
            root,rel=value.split(':',1);candidate=roots[root]/rel.lstrip('/\\')
        else:
            p=Path(value);candidate=p if p.is_absolute() else self.home/p
        candidate=candidate.resolve()
        if candidate.is_relative_to(DATA.resolve()) and not candidate.is_relative_to(self.home.resolve()):
            raise ValueError('Cortana internal data is outside file-management access.')
        if any(':' in part or '\x00' in part for part in candidate.parts[1:]):raise ValueError('Invalid filename.')
        if not any(candidate.is_relative_to(root.resolve()) for root in roots.values()):
            raise ValueError('That path is outside the approved folders. Add its folder in Abilities on the PC.')
        if existing and not candidate.exists():raise ValueError('That file or folder does not exist.')
        return candidate

    def label(self,path):
        path=Path(path).resolve()
        for name,root in self.roots().items():
            if path.is_relative_to(root.resolve()):return name+':'+path.relative_to(root.resolve()).as_posix()
        raise ValueError('Path is outside the approved folders.')

    def artifact(self,path):
        path=self.path(str(path),True)
        if not path.is_file() or path.stat().st_size>32*1024*1024:raise ValueError('Output must be a file under 32 MB.')
        aid=self.store.agent_artifact(str(path),path.name,path.stat().st_size)
        self.store.set('active_file',str(path))
        return {'id':aid,'name':path.name,'path':self.label(path),'bytes':path.stat().st_size,'download':'/api/artifacts/'+aid,'verified':True}

    def checkpoint(self,kind,paths):
        jid=uuid.uuid4().hex;folder=self.journal/jid;folder.mkdir()
        entries=[]
        for i,path in enumerate(dict.fromkeys(paths)):
            path=self.path(str(path));exists=path.exists()
            if exists and (not path.is_file() or path.stat().st_size>MAX_BYTES):raise ValueError('Changes support individual files under 12 MB.')
            backup=folder/str(i)
            if exists:shutil.copy2(path,backup)
            entries.append({'path':str(path),'existed':exists,'backup':str(backup),'after':None})
        record={'id':jid,'kind':kind,'entries':entries,'created':time.time()}
        (folder/'change.json').write_text(json.dumps(record),encoding='utf8')
        return record

    def finish(self,record):
        for e in record['entries']:
            p=Path(e['path']);e['after']=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
        (self.journal/record['id']/'change.json').write_text(json.dumps(record),encoding='utf8')
        return record['id']

    def undo(self,change_id):
        if not str(change_id).isalnum():raise ValueError('Invalid change ID.')
        meta=self.journal/str(change_id)/'change.json'
        if not meta.exists():raise ValueError('That change is unavailable.')
        record=json.loads(meta.read_text())
        if record.get('undone'):raise ValueError('That change is already undone.')
        for e in record['entries']:
            p=self.path(e['path']);current=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            if current!=e['after']:raise ValueError('A file changed again since this action. Undo would overwrite newer work.')
        for e in reversed(record['entries']):
            p=self.path(e['path'])
            if e['existed']:p.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(e['backup'],p)
            elif p.exists():p.unlink()
        record['undone']=True;meta.write_text(json.dumps(record));return {'undone':change_id,'verified':True}

    def files(self,args):
        action=args.get('action','list');path=self.path(args.get('path',''),action in ('read','list','move','copy','trash','duplicates','organise'))
        self.runtime.jobs.check()
        if action=='roots':return {'folders':list(self.roots()),'active_file':self.label(self.path())}
        if action=='list':
            if not path.is_dir():return {'file':self.artifact(path)}
            return {'folder':self.label(path),'entries':[{'name':p.name,'path':self.label(p),'directory':p.is_dir(),'bytes':p.stat().st_size if p.is_file() else None} for p in sorted(path.iterdir(),key=lambda p:p.name.lower())[:150] if self._inside(p)]}
        if action=='read':
            if not path.is_file() or path.stat().st_size>MAX_BYTES:raise ValueError('Choose a file under 12 MB.')
            self.store.set('active_file',str(path))
            if path.suffix.lower() in TEXT_TYPES:return {'path':self.label(path),'text':path.read_text(encoding='utf8',errors='replace')[:14000]}
            import files
            text,pages=files.extract_text(path.name,path.read_bytes());return {'path':self.label(path),'text':text[:14000],'pages':pages}
        if action=='mkdir':path.mkdir(parents=True,exist_ok=True);return {'folder':self.label(path),'verified':path.is_dir()}
        if action in ('write','append'):
            if path.suffix.lower() not in TEXT_TYPES:raise ValueError('Use create_document or spreadsheet for binary office files.')
            text=str(args.get('text',''))
            if len(text.encode('utf8'))>MAX_BYTES:raise ValueError('Text exceeds 12 MB.')
            old=path.read_text(encoding='utf8') if action=='append' and path.exists() else ''
            record=self.checkpoint(action,[path]);path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temp.write_text(old+text,encoding='utf8');temp.replace(path)
            return {'artifact':self.artifact(path),'undo':self.finish(record),'verified':path.read_text(encoding='utf8')==old+text}
        if action in ('move','copy'):
            if not path.is_file():raise ValueError('Move or copy an individual file, not an entire folder.')
            target=self.path(args.get('destination',''))
            if target==path:raise ValueError('Source and destination are the same.')
            record=self.checkpoint(action,[path,target]);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target)
            if action=='move':path.unlink()
            return {'artifact':self.artifact(target),'undo':self.finish(record),'verified':True}
        if action=='trash':
            record=self.checkpoint(action,[path]);path.unlink();return {'removed':self.label(path),'undo':self.finish(record),'verified':not path.exists()}
        if action=='undo':return self.undo(args.get('change_id',''))
        if action=='duplicates':
            groups={};checked=0
            for p in self._walk(path):
                if p.stat().st_size>MAX_BYTES:continue
                key=(p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest());groups.setdefault(key,[]).append(self.label(p));checked+=1
            return {'checked':checked,'duplicates':[g for g in groups.values() if len(g)>1][:40],'note':'Nothing was removed.'}
        if action=='organise':
            plan=[]
            for p in self._walk(path,recursive=False):
                target=path/(p.suffix.lower().lstrip('.') or 'no-extension')/p.name
                if not target.exists():plan.append({'from':self.label(p),'to':self.label(target)})
            return {'proposed_moves':plan[:100],'note':'Use move for each selected file; every move has undo.'}
        raise ValueError('Unknown file action.')

    def _inside(self,p):
        try:self.path(str(p));return True
        except (ValueError,OSError):return False

    def _walk(self,root,recursive=True):
        count=0
        for p in root.rglob('*') if recursive else root.iterdir():
            self.runtime.jobs.check()
            if p.is_file() and self._inside(p):yield p;count+=1
            if count>=1000:break

    def document(self,args):
        fmt=args.get('format','docx');path=self.path(args.get('path') or ('report.'+fmt))
        if fmt not in ('docx','pdf') or path.suffix.lower()!='.'+fmt:raise ValueError('Choose docx or pdf and a matching filename.')
        title=str(args.get('title') or 'Report')[:200];sections=args.get('sections') or []
        if not isinstance(sections,list) or len(sections)>100:raise ValueError('Use at most 100 document sections.')
        record=self.checkpoint('document',[path]);path.parent.mkdir(parents=True,exist_ok=True)
        if fmt=='docx':
            from docx import Document
            doc=Document();doc.add_heading(title,0)
            for item in sections:
                if item.get('heading'):doc.add_heading(str(item['heading'])[:300],1)
                for line in str(item.get('text','')).split('\n'):doc.add_paragraph(line[:10000])
                for bullet in (item.get('bullets') or [])[:100]:doc.add_paragraph(str(bullet)[:2000],style='List Bullet')
                rows=item.get('table') or []
                if rows:
                    width=max(len(row) for row in rows);table=doc.add_table(rows=0,cols=min(20,width));table.style='Light Shading Accent 1'
                    for row in rows[:300]:
                        cells=table.add_row().cells
                        for i,value in enumerate(row[:20]):cells[i].text=str(value)[:1000]
            doc.save(path);Document(path)
        else:
            from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,ListFlowable,ListItem,Table,TableStyle
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib import colors
            styles=getSampleStyleSheet();flow=[Paragraph(escape(title),styles['Title']),Spacer(1,16)]
            for item in sections:
                if item.get('heading'):flow.append(Paragraph(escape(str(item['heading'])[:300]),styles['Heading2']))
                for line in str(item.get('text','')).split('\n'):flow.extend([Paragraph(escape(line[:10000]),styles['BodyText']),Spacer(1,6)])
                if item.get('bullets'):flow.append(ListFlowable([ListItem(Paragraph(escape(str(v)[:2000]),styles['BodyText'])) for v in item['bullets'][:100]],bulletType='bullet'))
                if item.get('table'):
                    rows=[[Paragraph(escape(str(v)[:1000]),styles['BodyText']) for v in row[:10]] for row in item['table'][:300]]
                    table=Table(rows,repeatRows=1,hAlign='LEFT');table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#cce8f5')),('GRID',(0,0),(-1,-1),.3,colors.grey)]));flow.append(table)
            SimpleDocTemplate(str(path),title=title).build(flow)
            from pypdf import PdfReader
            if not len(PdfReader(path).pages):raise RuntimeError('The PDF has no pages.')
        return {'artifact':self.artifact(path),'undo':self.finish(record),'verified':True}

    def spreadsheet(self,args):
        action=args.get('action','read');path=self.path(args.get('path') or 'workbook.xlsx',action not in ('write','chart'))
        if action=='write':
            rows=args.get('rows') or []
            if not isinstance(rows,list) or len(rows)>10000 or any(not isinstance(row,list) or len(row)>100 for row in rows):raise ValueError('Use at most 10,000 rows and 100 columns.')
            record=self.checkpoint('spreadsheet',[path]);path.parent.mkdir(parents=True,exist_ok=True)
            if path.suffix.lower()=='.csv':
                with path.open('w',newline='',encoding='utf8-sig') as f:csv.writer(f).writerows(rows)
            elif path.suffix.lower()=='.xlsx':
                from openpyxl import Workbook,load_workbook
                from openpyxl.styles import Font,PatternFill
                wb=Workbook();ws=wb.active;ws.title=str(args.get('sheet') or 'Sheet1')[:31]
                for row in rows:ws.append(row)
                if rows:
                    for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='16436C')
                ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
                for column in ws.columns:
                    ws.column_dimensions[column[0].column_letter].width=min(55,max(12,max(len(str(c.value or '')) for c in column[:100])+2))
                wb.save(path);load_workbook(path,read_only=True).close()
            else:raise ValueError('Write an xlsx or csv file.')
            return {'artifact':self.artifact(path),'undo':self.finish(record),'rows':len(rows),'verified':True}
        rows=self._rows(path,args.get('sheet'))
        if action=='read':return {'path':self.label(path),'rows':rows[:100],'total_rows':len(rows),'note':'Formula results may be stale until recalculated in Excel.'}
        if action=='analyse':
            column=int(args.get('column',0));numbers=[]
            for row in rows[1:] if args.get('headers',True) else rows:
                try:
                    number=float(str(row[column]).replace(',',''))
                    if math.isfinite(number):numbers.append(number)
                except (IndexError,ValueError,TypeError):pass
            if not numbers:raise ValueError('That column has no numeric values.')
            return {'count':len(numbers),'sum':sum(numbers),'average':statistics.mean(numbers),'median':statistics.median(numbers),'min':min(numbers),'max':max(numbers),'verified':True}
        if action=='compare':
            other=self.path(args.get('other',''),True);second=self._rows(other,args.get('other_sheet'))
            a={json.dumps(r,default=str) for r in rows};b={json.dumps(r,default=str) for r in second}
            return {'only_in_first':[json.loads(v) for v in sorted(a-b)[:100]],'only_in_second':[json.loads(v) for v in sorted(b-a)[:100]],'matching_rows':len(a&b),'verified':True}
        if action=='chart':
            from openpyxl import load_workbook
            from openpyxl.chart import BarChart,LineChart,Reference
            if path.suffix.lower()!='.xlsx':raise ValueError('Charts are added to xlsx files.')
            record=self.checkpoint('chart',[path]);wb=load_workbook(path);ws=wb[args.get('sheet') or wb.sheetnames[0]]
            chart=LineChart() if args.get('kind')=='line' else BarChart();chart.title=str(args.get('title') or 'Chart')[:150]
            value=int(args.get('column',1))+1;label=int(args.get('label_column',0))+1
            if not 1<=value<=ws.max_column or not 1<=label<=ws.max_column:raise ValueError('Choose existing label/value columns.')
            chart.add_data(Reference(ws,min_col=value,min_row=1,max_row=min(ws.max_row,1000)),titles_from_data=True)
            chart.set_categories(Reference(ws,min_col=label,min_row=2,max_row=min(ws.max_row,1000)));ws.add_chart(chart,'H2');wb.save(path)
            return {'artifact':self.artifact(path),'undo':self.finish(record),'verified':True}
        raise ValueError('Unknown spreadsheet action.')

    def _rows(self,path,sheet=None):
        if path.stat().st_size>MAX_BYTES:raise ValueError('Spreadsheet exceeds 12 MB.')
        if path.suffix.lower()=='.csv':
            with path.open(newline='',encoding='utf8-sig') as f:return [r for i,r in enumerate(csv.reader(f)) if i<10000]
        if path.suffix.lower()=='.xlsx':
            from openpyxl import load_workbook
            wb=load_workbook(path,read_only=True,data_only=False)
            try:return [list(r) for r in wb[sheet or wb.sheetnames[0]].iter_rows(max_row=10000,max_col=100,values_only=True)]
            finally:wb.close()
        raise ValueError('Choose a csv or xlsx file.')

    def code(self,args):
        docker=shutil.which('docker')
        if not docker:raise RuntimeError('Code execution needs Docker Desktop running on the PC. The app never runs generated code directly on Windows.')
        code=str(args.get('code',''))
        if not code.strip() or len(code)>50000:raise ValueError('Provide Python code under 50,000 characters.')
        self.runtime.jobs.check();name='cortana-'+uuid.uuid4().hex[:16]
        with tempfile.TemporaryDirectory(dir=DATA) as tmp:
            root=Path(tmp);source=root/'input';source.mkdir();(source/'code.py').write_text(code,encoding='utf8')
            for value in (args.get('inputs') or [])[:10]:
                p=self.path(value,True)
                if not p.is_file() or p.stat().st_size>MAX_BYTES:raise ValueError('Inputs must be files under 12 MB.')
                shutil.copy2(p,source/p.name)
            output=self.home/'Code outputs'/name;output.mkdir(parents=True);output.chmod(0o777)
            command=[docker,'run','-d','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
                '--memory','512m','--cpus','1','--pids-limit','64','--user','65534:65534','--tmpfs','/tmp:rw,noexec,nosuid,size=64m',
                '--mount','type=bind,src='+str(source.resolve())+',dst=/input,readonly','--tmpfs','/output:rw,noexec,nosuid,size=64m,nr_inodes=1024,uid=65534,gid=65534',
                '--workdir','/output','python:3.12-slim','python','-I','-c','import time;time.sleep(90)']
            start=subprocess.run(command,capture_output=True,timeout=30,creationflags=HIDDEN)
            if start.returncode:raise RuntimeError('Docker could not start the Python sandbox. Start Docker Desktop and pull python:3.12-slim first.')
            runner="import subprocess,json; o=open('/tmp/stdout','wb'); e=open('/tmp/stderr','wb'); p=subprocess.run(['python','-I','/input/code.py'],stdout=o,stderr=e,timeout=45); o.close();e.close(); print(json.dumps({'exit_code':p.returncode,'stdout':open('/tmp/stdout','rb').read()[-12000:].decode('utf8','replace'),'stderr':open('/tmp/stderr','rb').read()[-6000:].decode('utf8','replace')}))"
            command=[docker,'exec',name,'python','-I','-c',runner]
            process=self.runtime.spawn(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE);deadline=time.monotonic()+60
            try:
                while True:
                    self.runtime.jobs.check()
                    try:stdout,stderr=process.communicate(timeout=.2);break
                    except subprocess.TimeoutExpired:
                        if time.monotonic()>deadline:raise RuntimeError('Python exceeded its 60-second limit.')
                copied=subprocess.run([docker,'cp',name+':/output/.',str(output)],capture_output=True,timeout=20,creationflags=HIDDEN)
                if copied.returncode:raise RuntimeError('Could not collect the sandbox outputs.')
            finally:
                subprocess.run([docker,'rm','-f',name],capture_output=True,timeout=10,creationflags=HIDDEN)
                if process.poll() is None:process.kill();process.communicate(timeout=5)
            outcome=json.loads(stdout.decode('utf8')) if process.returncode==0 else {'exit_code':process.returncode,'stdout':'','stderr':stderr.decode('utf8','replace')[-6000:]}
            artifacts=[self.artifact(p) for p in self._walk(output) if p.stat().st_size<=MAX_BYTES][:20]
            return {**outcome,'artifacts':artifacts,'verified':outcome['exit_code']==0,'note':'Python container: no network, read-only inputs, bounded temporary output.'}
