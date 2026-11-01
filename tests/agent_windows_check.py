"""Exercise Windows UIAutomation against a disposable native form, never the user's apps."""
import os,sys,tempfile,time,subprocess,json
sys.path[:0]=['app'];os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime,HIDDEN
import pc_agent
r=Runtime()
script=r'''
Add-Type -AssemblyName System.Windows.Forms
$f=New-Object System.Windows.Forms.Form;$f.Text='Cortana Agent Test Fixture';$f.Width=500;$f.Height=240
$t=New-Object System.Windows.Forms.TextBox;$t.Name='FixtureInput';$t.AccessibleName='Fixture input';$t.Top=20;$t.Width=250;$f.Controls.Add($t)
$b=New-Object System.Windows.Forms.Button;$b.Text='Fixture button';$b.Top=70;$b.Width=200;$f.Controls.Add($b)
$b.Add_Click({$t.Text='clicked'})
[System.Windows.Forms.Application]::Run($f)
'''
p=subprocess.Popen(['powershell','-NoProfile','-STA','-Command',script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
try:
    deadline=time.monotonic()+30;window=None
    while time.monotonic()<deadline:
        rows=pc_agent.desktop(r.agent,{'action':'windows'})['windows'];window=next((w for w in rows if w['name']=='Cortana Agent Test Fixture'),None)
        if window:break
        time.sleep(.5)
    assert window,rows
    snapshot=pc_agent.desktop(r.agent,{'action':'inspect','window':window['window']})
    control=next(c for c in snapshot['controls'] if 'Fixture input' in c['name'])
    args={'action':'set_value','window':snapshot['window'],'ref':control['ref'],'revision':snapshot['revision'],'text':'verified text'}
    pending=r.agent.run('desktop',args,['desktop'])[0];assert pending['approval_required'],pending
    result=r.agent.review(pending['approval_id'],True);assert result.get('verified'),result
    assert pc_agent.diagnostics(r.agent,{'action':'summary'})['verified']
    assert pc_agent.diagnostics(r.agent,{'action':'processes'})['processes']
    print('WINDOWS: observed accessibility control, reviewed text edit and actual PC diagnostics PASS',flush=True)
finally:p.terminate();p.wait(timeout=10);r.close();r.store.close()
