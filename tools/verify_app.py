"""Launch the actual Python/EXE server and verify the browser-facing workflow."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def verify(executable=None):
    root=Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory() as directory:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        address=f'http://127.0.0.1:{port}'
        command=[str(Path(executable).resolve())] if executable else [sys.executable,str(root/'entrypoint.py')]
        env={**os.environ,'JZ_DATA_DIR':directory,'JZ_PASSWORD':'','JZ_HOST':'127.0.0.1'}
        with open(Path(directory)/'process.log','wb') as log:
            process=subprocess.Popen(command+['--port',str(port),'--no-open'],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log)
            try:
                client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                def request(path,payload=None):
                    data=None if payload is None else json.dumps(payload).encode()
                    req=urllib.request.Request(address+path,data=data,headers={'Content-Type':'application/json'})
                    with client.open(req,timeout=20) as response:return response.read(),response.headers
                deadline=time.monotonic()+90
                while True:
                    try:
                        health,_=request('/health')
                        assert json.loads(health)['service']=='SJTU-JunZhengMatch';break
                    except (OSError,urllib.error.URLError):
                        if time.monotonic()>deadline or process.poll() is not None:
                            raise RuntimeError('Application failed to start: '+(Path(directory)/'process.log').read_text(errors='replace'))
                        time.sleep(.25)
                for path in ['/','/app.js','/theme.css','/frontend/kotone-mascot.png']:
                    body,_=request(path);assert body,path
                for name in ('README','ARCHITECTURE'):
                    body,_=request('/api/docs?name='+name);assert json.loads(body)['content'].startswith('#')
                body,_=request('/api/db/stats');assert json.loads(body)['total']>0
                body,_=request('/api/template?type=example&format=xlsx');assert body.startswith(b'PK')
                body,_=request('/api/match/run',{'use_sample':True,'params':{}})
                result=json.loads(body);assert result['matched_full']==6,result
                assert all(len(s['reviewers'])==3 for s in result['items'])
                for student in result['items']:
                    assert all(r['name']!=student['advisor'] for r in student['reviewers'])
                csv,_=request('/api/match/export?format=csv');assert '评审1相近程度' in csv.decode('utf-8-sig')
                xlsx,_=request('/api/match/export?format=xlsx');assert xlsx.startswith(b'PK')
                return dict(status='ok',students=6,reviewers=18,http_workflow=True)
            finally:
                if os.name=='nt':
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                elif process.poll() is None:process.terminate()
                process.wait(timeout=15)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--exe');parser.add_argument('--report')
    args=parser.parse_args();result=verify(args.exe)
    if args.report:Path(args.report).write_text(json.dumps(result),encoding='utf-8')
    print(json.dumps(result))
