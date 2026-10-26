"""Cross-process backend reuse: one service per selected data folder."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from . import paths


class FolderLock:
    def __init__(self,folder,name='.service.lock'):self.path=Path(folder)/name;self.handle=None
    def acquire(self,wait=0):
        self.path.parent.mkdir(parents=True,exist_ok=True);deadline=time.monotonic()+wait
        while True:
            handle=open(self.path,'a+b');handle.seek(0)
            if self.path.stat().st_size==0:handle.write(b'0');handle.flush();handle.seek(0)
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                self.handle=handle;return self
            except OSError:
                handle.close()
                if time.monotonic()>=deadline:raise RuntimeError('此数据目录的后台已在运行或正在启动。')
                time.sleep(.15)
    def release(self):
        if self.handle:
            self.handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_UN)
            self.handle.close();self.handle=None
    def __enter__(self):return self.acquire(wait=60)
    def __exit__(self,*args):self.release()


def command():
    if getattr(sys,'frozen',False):return [sys.executable]
    return [sys.executable,str(paths.RESOURCE_ROOT/'packaging/launcher.py')]


def registry_path(folder):return Path(folder)/'shared-instance.json'


def write_instance(folder,port,instance_id):
    payload=dict(url=f'http://127.0.0.1:{port}',pid=os.getpid(),instance_id=instance_id,data_identity=paths.data_identity(folder))
    target=registry_path(folder);temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(payload),encoding='utf-8');temp.chmod(0o600);os.replace(temp,target)
    return payload


def find_instance(folder):
    try:
        payload=json.loads(registry_path(folder).read_text())
        from urllib.parse import urlsplit
        url=urlsplit(payload['url'])
        if url.scheme!='http' or url.hostname!='127.0.0.1' or url.path: return None
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(payload['url']+'/health',timeout=1) as r:health=json.load(r)
        if health.get('service')=='SJTU-JunZhengMatch' and health.get('instance_id')==payload['instance_id'] and health.get('data_identity')==paths.data_identity(folder):return payload
    except (OSError,ValueError,KeyError):pass
    return None


def ensure_backend(folder,port=8765,config_root=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with FolderLock(folder,'.launch.lock'):
        existing=find_instance(folder)
        if existing:return existing
        (folder/'logs').mkdir(exist_ok=True)
        env={**os.environ,'JZ_DATA_DIR':str(folder),'JZ_CONFIG_DIR':str(config_root or paths.CONFIG_ROOT),'PYTHONIOENCODING':'utf-8','PYINSTALLER_RESET_ENVIRONMENT':'1'}
        with open(folder/'logs/service.log','ab') as log:
            options=dict(stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env)
            if os.name=='nt':options['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
            else:options['start_new_session']=True
            process=subprocess.Popen(command()+['--serve','--port',str(port),'--data-dir',str(folder)],**options)
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            existing=find_instance(folder)
            if existing:return existing
            if process.poll() is not None:raise RuntimeError('后台启动失败，请查看数据目录中的logs/service.log。')
            time.sleep(.2)
        raise RuntimeError('后台启动超时，请查看数据目录中的logs/service.log。')
