"""Exercise actual multi-process sharing, preferences, migration and shutdown."""
import argparse
from collections import Counter
import concurrent.futures
import http.cookiejar
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def verify(executable=None,desktop=False):
    root=Path(__file__).resolve().parent.parent
    command=[str(Path(executable).resolve())] if executable else [sys.executable,str(root/'packaging/launcher.py')]
    instance=None
    with tempfile.TemporaryDirectory() as temp:
        folder=Path(temp);data=folder/'data';config=folder/'config'
        env={**os.environ,'JZ_CONFIG_DIR':str(config),'JZ_PASSWORD':'','PYTHONPATH':str(root/'src'),'PYTHONIOENCODING':'utf-8'}
        env.pop('JZ_DATA_DIR',None)
        def launch(arguments):
            print('Launching: '+arguments[0],flush=True)
            # WebView2 can inherit pipe handles. Waiting for pipe EOF can hang even
            # after the launcher exits; use a file and wait on the process itself.
            with open(folder/'launcher.log','w+b') as log:
                process=subprocess.Popen(command+arguments,env=env,stdout=log,stderr=log)
                try:process.wait(timeout=150)
                except subprocess.TimeoutExpired:
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=log,stderr=log,timeout=20)
                    else:process.kill()
                    raise RuntimeError('Launcher timed out: '+arguments[0])
                if process.returncode:
                    log.seek(0);raise RuntimeError(log.read().decode(errors='replace') or 'Launcher failed: '+arguments[0])
            print('Completed: '+arguments[0],flush=True)
        launch(['--configure-data',str(data)])
        try:
            def client(index):
                report=folder/f'client{index}.json';launch(['--launch-only','--port','0','--report',str(report)]);return json.loads(report.read_text())
            with concurrent.futures.ThreadPoolExecutor(2) as pool:first,second=list(pool.map(client,[1,2]))
            instance=first;assert first['pid']==second['pid'] and first['instance_id']==second['instance_id']
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            def request(path,body=None):
                req=urllib.request.Request(first['url']+path,data=None if body is None else json.dumps(body).encode(),headers={'Content-Type':'application/json'})
                with opener.open(req,timeout=30) as response:
                    blob=response.read()
                    return json.loads(blob) if response.headers.get_content_type()=='application/json' else blob
            request('/api/app/client',{'id':'browser-test-001','mode':'browser'})
            request('/api/app/client',{'id':'desktop-test-002','mode':'desktop'})
            assert request('/api/app/status')['clients']==2
            status=request('/api/app/status')
            try:request('/api/app/shutdown',{'token':status['exit_token']})
            except urllib.error.HTTPError as error:assert error.code==400;error.close()
            else:raise AssertionError('Shared exit must require confirmation')
            request('/api/app/client',{'id':'browser-test-001','closed':True})
            assert request('/api/app/status')['clients']==1
            if desktop:
                report=folder/'desktop.json';launch(['--desktop-smoke','--report',str(report)])
                gui=json.loads(report.read_text());assert gui['status']=='ok' and gui['native_window']
                assert gui['instance_id']==first['instance_id']
                assert request('/health')['instance_id']==first['instance_id'],'Closing a desktop window stopped the backend'
            print('Checking preferences, allocation and migration',flush=True)
            settings=request('/api/preferences');assert settings['match_defaults']['max_teacher_uses']==2
            defaults=settings['match_defaults'];defaults['max_teacher_uses']=1
            request('/api/preferences',{'match_defaults':defaults})
            result=request('/api/match/run',{'use_sample':True})
            counts=Counter(r['name'] for student in result['items'] for r in student['reviewers']);assert max(counts.values())<=1
            request('/api/match/export?format=csv');assert list((data/'exports').glob('*.csv'))
            marker=request('/api/db/create',{'name':'共享测试教师','title':'副教授','department':'测试学院'})
            target=folder/'migrated'
            request('/api/preferences',{'data_dir':str(target),'migration':'copy','match_defaults':defaults})
            assert (target/'sjtu_faculty_data.db').exists() and (data/'sjtu_faculty_data.db').exists()
            assert request('/api/db/list?keyword='+urllib.parse.quote('共享测试教师'))['total']==1
            third=client(3);assert third['pid']==first['pid'],'Migration created another backend'
            backup=request('/api/preferences/backup')
            request('/api/db/delete',{'id':marker['id']})
            assert request('/api/db/list?keyword='+urllib.parse.quote('共享测试教师'))['total']==0
            import base64
            request('/api/preferences/restore',{'file_base64':base64.b64encode(backup).decode()})
            assert request('/api/db/list?keyword='+urllib.parse.quote('共享测试教师'))['total']==1
            settings=request('/api/preferences');assert settings['match_defaults']['max_teacher_uses']==1
            status=request('/api/app/status');request('/api/app/shutdown',{'token':status['exit_token'],'confirm_all':True})
            print('Stopping shared backend',flush=True)
            deadline=time.monotonic()+15
            while (target/'shared-instance.json').exists() and time.monotonic()<deadline:time.sleep(.1)
            assert not (target/'shared-instance.json').exists()
            time.sleep(.6)
            instance=None
            return dict(status='ok',shared_backend=True,window_close_keeps_service=True,migration=True,backup_restore=True,allocation_cap=True,desktop_window=desktop)
        finally:
            if instance:
                try:
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(instance['url']+'/api/app/status',timeout=2) as response:status=json.load(response)
                    req=urllib.request.Request(instance['url']+'/api/app/shutdown',data=json.dumps({'token':status['exit_token'],'confirm_all':True}).encode(),headers={'Content-Type':'application/json'})
                    with opener.open(req,timeout=2):pass
                    time.sleep(.5)
                except Exception:
                    if os.name=='nt':subprocess.run(['taskkill','/PID',str(instance['pid']),'/T','/F'],capture_output=True)
                    else:
                        try:os.kill(instance['pid'],15)
                        except ProcessLookupError:pass


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe');parser.add_argument('--desktop',action='store_true');parser.add_argument('--report');args=parser.parse_args()
    result=verify(args.exe,args.desktop)
    if args.report:Path(args.report).write_text(json.dumps(result),encoding='utf-8')
    print(json.dumps(result))
