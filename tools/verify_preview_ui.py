"""Exercise preview folding in a real browser against the built application."""
import argparse,csv,io,json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser();parser.add_argument('--exe');parser.add_argument('--report',default='preview-ui-test.json');args=parser.parse_args()
root=Path(__file__).resolve().parent.parent
with tempfile.TemporaryDirectory() as directory:
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={**os.environ,'JZ_DATA_DIR':directory,'JZ_CONFIG_DIR':directory,'JZ_PASSWORD':''}
    command=[str(Path(args.exe).resolve())] if args.exe else [sys.executable,str(root/'packaging/launcher.py')]
    with open(Path(directory)/'server.log','wb') as log:
        process=subprocess.Popen(command+['--no-open','--port',str(port)],env=env,stdout=log,stderr=log)
        try:
            url=f'http://127.0.0.1:{port}';opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline=time.monotonic()+60
            while True:
                try:
                    with opener.open(url+'/health',timeout=1):break
                except OSError:
                    if time.monotonic()>deadline:raise RuntimeError('Preview test service did not start')
                    time.sleep(.2)
            with sync_playwright() as p:
                browser=p.chromium.launch(channel='chrome',headless=True)
                page=browser.new_page(viewport={'width':1600,'height':1000})
                page.goto(url);page.get_by_role('button',name='使用此位置',exact=True).click()
                page.get_by_role('button',name='载入示例表',exact=True).click()
                page.wait_for_function("!document.getElementById('btn-export-csv').disabled")
                before=page.locator('#match-preview-wrap').inner_text()
                shots=root/'installer-ui-preview';shots.mkdir(exist_ok=True)
                page.screenshot(path=str(shots/'match-expanded.png'))
                page.get_by_role('button',name='收起预览',exact=True).click()
                assert not page.locator('#match-preview-content').is_visible()
                assert page.locator('#btn-fold-preview').get_attribute('aria-expanded')=='false'
                assert page.locator('#btn-export-xlsx').is_enabled()
                page.screenshot(path=str(shots/'match-collapsed.png'))
                with page.expect_download() as download:
                    page.locator('#btn-export-csv').click()
                text=Path(download.value.path()).read_text(encoding='utf-8-sig')
                assert len(next(csv.reader(io.StringIO(text))))==31
                page.get_by_role('button',name='展开预览',exact=True).click()
                assert page.locator('#match-preview-wrap').inner_text()==before
                browser.close()
            result=dict(status='ok',collapse_hides_table=True,expand_preserves_results=True,collapsed_export_csv_columns=31)
            Path(args.report).write_text(json.dumps(result),encoding='utf-8');print(json.dumps(result))
        finally:
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:process.terminate()
            process.wait(timeout=15)
