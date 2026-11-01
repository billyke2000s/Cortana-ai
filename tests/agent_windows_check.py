"""Exercise Windows UIAutomation against a disposable native form, never the user's apps."""
import os,sys,tempfile,time,subprocess,json
sys.path[:0]=['app'];os.environ.setdefault('CORTANA_DATA_DIR',tempfile.mkdtemp())
from runtime import Runtime,HIDDEN
import pc_agent
r=Runtime()
script=r'''
Add-Type -AssemblyName PresentationFramework
$x=@'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="Cortana Agent Test Fixture" Width="500" Height="240" Topmost="True" WindowStartupLocation="CenterScreen">
 <StackPanel Margin="20"><TextBox Name="FixtureInput" AutomationProperties.Name="Fixture input" Height="30"/><Button Name="FixtureButton" Content="Fixture button" Height="35" Margin="0,15,0,0"/></StackPanel>
</Window>
'@
$f=[Windows.Markup.XamlReader]::Parse($x);$t=$f.FindName('FixtureInput');$b=$f.FindName('FixtureButton')
$b.Add_Click({$t.Text='clicked'});$f.Add_ContentRendered({$f.Activate();$t.Focus()});$f.ShowDialog()|Out-Null
'''
p=subprocess.Popen(['powershell','-NoProfile','-STA','-Command',script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
try:
    deadline=time.monotonic()+30;window=None
    while time.monotonic()<deadline:
        rows=pc_agent.desktop(r.agent,{'action':'windows'})['windows'];window=next((w for w in rows if w['name']=='Cortana Agent Test Fixture'),None)
        if window:break
        time.sleep(.5)
    assert window,rows
    control=None
    while time.monotonic()<deadline:
        snapshot=pc_agent.desktop(r.agent,{'action':'inspect','window':window['window']})
        control=next((c for c in snapshot['controls'] if c['type']=='ControlType.Edit'),None)
        if control:break
        time.sleep(.5)
    assert control,snapshot
    print('WINDOWS SNAPSHOT',json.dumps(snapshot),flush=True)
    args={'action':'set_value','window':snapshot['window'],'ref':control['ref'],'revision':snapshot['revision'],'text':'verified text'}
    pending=r.agent.run('desktop',args,['desktop'])[0];assert pending['approval_required'],pending
    result=r.agent.review(pending['approval_id'],True);assert result.get('verified'),result
    assert pc_agent.diagnostics(r.agent,{'action':'summary'})['verified']
    assert pc_agent.diagnostics(r.agent,{'action':'processes'})['processes']
    print('WINDOWS: observed accessibility control, reviewed text edit and actual PC diagnostics PASS',flush=True)
finally:p.terminate();p.wait(timeout=10);r.close();r.store.close()
