"""Real browser + real gateway with fake Ollama and silent speech."""
import os
import sys
import tempfile
import threading
sys.path[:0]=['tests','app']
OUT=tempfile.mkdtemp(prefix='cortana-out-');os.environ['CORTANA_OUTPUT_DIR']=OUT
import test_offline as b
from playwright.sync_api import sync_playwright
r=b.runtime.Runtime();r.store.close();r.store=b.store.Store(':memory:');r.ai_ready=True;r.stt_ready=True
r.tag_exists={m['tag']:True for m in b.hardware.CATALOG};r.voice.speak=b.silent_voice
r.voice.switch=lambda engine=None,voice=None:r.store.set('voice_engine',engine) if engine else None
srv=b.server.AppServer(('127.0.0.1',0),r);threading.Thread(target=srv.serve_forever,daemon=True).start()
url='http://127.0.0.1:'+str(srv.server_address[1])
try:
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'],env={k:v for k,v in os.environ.items() if 'proxy' not in k.lower()})
        page=browser.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        for width,height in [(320,568),(360,640),(390,844),(430,932),(844,390),(1280,900)]:
            page.set_viewport_size({'width':width,'height':height});page.goto(url)
            page.wait_for_function('window.CortanaPages !== undefined')
            if width==320:
                page.evaluate("window.CortanaPages.open('setup')");page.wait_for_selector('#setupExpression')
                page.select_option('#setupExpression','expressive');page.click('[data-act=setup-save]');page.wait_for_selector('#chatInput')
            page.evaluate("window.CortanaPages.open('settings')");page.wait_for_selector('#sExpression')
            page.select_option('#sExpression','expressive')
            # 'Saved.' only shows for ~0.7 s before the page re-renders; with the 3D avatar drawing in software, frame-based
            # polling can miss it, so check the save request itself and then wait for the re-render to finish.
            with page.expect_response(lambda resp:resp.url.endswith('/api/settings') and resp.request.method=='POST') as saved:
                page.click('[data-act=save]')
            assert saved.value.ok,saved.value.status
            with page.expect_response(lambda resp:resp.url.endswith('/api/settings') and resp.request.method=='GET'):pass
            panel=page.locator('#holoPanel').bounding_box();nav=page.locator('.nav-wrap').bounding_box()
            assert panel['y']+panel['height']<=nav['y']+1,(width,panel,nav)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
            print('LAYOUT',width,height,'OK',flush=True)
        page.wait_for_function('window.CortanaAvatar?.ready',timeout=60000)
        page.evaluate("window.CortanaAvatar.setCharacter(1.8);window.CortanaAvatar.startSpeech([{time:0,duration:1,id:2}],()=>.6,1,'curious')")
        page.wait_for_function('window.CortanaAvatar.inspect().leftForearmAngle > .01')
        page.evaluate('window.CortanaAvatar.setCharacter(1.3)')
        page.wait_for_function('window.CortanaAvatar.inspect().leftForearmAngle < .001')
        page.evaluate('window.CortanaAvatar.stopSpeech()')
        print('EXPRESSIVE RIG GESTURE / NORMAL RESET OK',flush=True)
        page.evaluate("window.CortanaPages.open('chat')");page.fill('#chatInput','Remember my dog is called Max')
        page.click('#chatForm [type=submit]')
        page.wait_for_function("window.Cortana.chat.some(m=>m.role==='assistant'&&!m.pending&&m.text)")
        page.reload();page.wait_for_function("window.Cortana?.chat.some(m=>m.text.includes('Max'))")
        page.evaluate("window.CortanaPages.open('memory')");page.wait_for_selector('[data-fact]')
        page.locator('[data-fact]').first.fill('My dog is called Rex')
        with page.expect_response(lambda resp:'/api/documents' in resp.url):   # the Memory page re-renders after saving; let it finish
            page.locator('[data-act=edit-fact]').first.click()
        page.wait_for_function("document.querySelector('[data-fact]')?.value==='My dog is called Rex'")
        print('HISTORY RESTORE / MEMORY EDIT OK',flush=True)
        # 1.6: ask-before-doing card (tap Approve, then a spoken/typed "yes"), deep thinking toggle, new Systems sections
        page.evaluate("window.CortanaPages.open('chat')");page.fill('#chatInput','Please save a document of my plan');page.click('#chatForm [type=submit]')
        page.wait_for_selector('.chat-confirm[data-state=waiting] [data-act=confirm-yes]')
        assert not os.listdir(OUT),os.listdir(OUT)
        page.click('.chat-confirm [data-act=confirm-yes]');page.wait_for_selector('.chat-confirm[data-state=done]')
        assert os.listdir(OUT)==['Plan.docx'],os.listdir(OUT)
        page.fill('#chatInput','Please save a document of my plan');page.click('#chatForm [type=submit]')
        page.wait_for_selector('.chat-confirm[data-state=waiting]');page.wait_for_function("!window.Cortana.chat.some(m=>m.pending)")
        page.fill('#chatInput','yes please');page.click('#chatForm [type=submit]')
        page.wait_for_function("document.querySelectorAll('.chat-confirm[data-state=done]').length===2")
        assert sorted(os.listdir(OUT))==['Plan (2).docx','Plan.docx'],os.listdir(OUT)
        page.click('[data-act=deep]');assert page.get_attribute('[data-act=deep]','aria-pressed')=='true'
        page.evaluate("window.CortanaPages.open('settings')");page.wait_for_selector('#sContext');page.wait_for_selector('#sBriefAt')
        print('APPROVAL CARD / VOICE YES / DEEP TOGGLE / SYSTEMS OK',flush=True)
        assert not errors,errors
        print('CONSOLE OK',flush=True)
        browser.close()
finally:srv.shutdown();srv.server_close();r.store.close()
